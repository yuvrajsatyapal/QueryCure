import os
import secrets
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg.conninfo import conninfo_to_dict

BACKEND = Path(__file__).parents[2]
ADMIN_URL = os.environ.get(
    "QD_TEST_ADMIN_URL", "postgresql://qd_owner:qd_local_dev_only@127.0.0.1:5432/postgres"
)


def _db_url(name: str) -> str:
    base, _, _ = ADMIN_URL.rpartition("/")
    return f"{base}/{name}"


@pytest.fixture(scope="session")
def migrated_db() -> Iterator[str]:
    """A fresh database per test session, upgraded to head. Dropped afterwards."""
    try:
        admin = psycopg.connect(ADMIN_URL, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        reason = f"metadata DB not reachable ({exc.__class__.__name__}); run docker compose up"
        # CI sets QD_REQUIRE_DB so a missing database fails loudly instead of silently skipping.
        if os.environ.get("QD_REQUIRE_DB") == "1":
            pytest.fail(reason)
        pytest.skip(reason)
    name = f"qd_test_{uuid.uuid4().hex[:12]}"
    with admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    url = _db_url(name)
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url.replace("postgresql://", "postgresql+psycopg://", 1))
    command.upgrade(cfg, "head")
    try:
        yield url
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def owner(migrated_db: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        yield conn


@pytest.fixture
def as_app(migrated_db: str) -> Iterator[psycopg.Connection]:
    """Connection with exactly the qd_app role's privileges."""
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        conn.execute("SET ROLE qd_app")
        yield conn


@pytest.fixture
def as_retention(migrated_db: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        conn.execute("SET ROLE qd_retention")
        yield conn


@pytest.fixture(scope="session")
def target() -> Iterator[dict[str, Any]]:
    try:
        admin = psycopg.connect(ADMIN_URL, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("metadata DB not reachable")
    suffix = uuid.uuid4().hex[:10]
    db, role, password = f"qd_target_{suffix}", f"qd_test_inspector_{suffix}", secrets.token_hex(16)
    with admin:
        admin.execute(f'CREATE DATABASE "{db}"')
        admin.execute(f"CREATE ROLE {role} LOGIN PASSWORD '{password}'")
    with psycopg.connect(_db_url(db), autocommit=True) as conn:
        conn.execute(
            """
            CREATE TABLE orders (
                id bigserial PRIMARY KEY,
                customer_id int NOT NULL,
                created_at timestamptz NOT NULL,
                total numeric(10, 2),
                email text
            );
            INSERT INTO orders (customer_id, created_at, total, email)
            SELECT g % 200, now() - g * interval '1 minute', g % 97,
                   'secret-' || g || '@customer.example'
            FROM generate_series(1, 3000) g;
            CREATE INDEX orders_customer_id_idx ON orders (customer_id);
            ANALYZE orders;
            CREATE FUNCTION public.myfn(i int) RETURNS int LANGUAGE sql IMMUTABLE AS 'SELECT i';
            """
        )
        conn.execute(f'GRANT CONNECT ON DATABASE "{db}" TO {role}')
        conn.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
        conn.execute(f"GRANT SELECT ON orders TO {role}")
        conn.execute(f"GRANT pg_read_all_stats TO {role}")
    admin_info = conninfo_to_dict(ADMIN_URL)
    yield {
        "host": admin_info.get("host", "127.0.0.1"),
        "port": int(admin_info.get("port", 5432)),
        "dbname": db,
        "role": role,
        "password": password,
        "admin_user": admin_info["user"],
        "admin_password": admin_info["password"],
    }
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)')
        admin.execute(f"DROP ROLE IF EXISTS {role}")
