import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config

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
