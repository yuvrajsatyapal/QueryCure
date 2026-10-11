"""Inspection gateway against a seeded target database (SECURITY.md §4-5, TESTING_STRATEGY §3-4)."""

import asyncio
import json
import secrets
import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict
from pydantic import SecretStr

from querydoctor.connectors.inspection_gateway import (
    GatewayLimits,
    InspectionGateway,
    TargetConnection,
)
from querydoctor.connectors.ssrf_guard import TargetPolicy
from querydoctor.core.errors import (
    RoleTooPrivilegedError,
    SqlNotAllowedError,
    TargetBlockedError,
    TargetTimeoutError,
    TargetUnreachableError,
)
from querydoctor.sql.validator import SqlPolicy

from .conftest import ADMIN_URL, _db_url

pytestmark = pytest.mark.integration

LOCAL = TargetPolicy(allow_private=True)
FAST = GatewayLimits(statement_timeout_ms=300, lock_timeout_ms=200)


@pytest.fixture(scope="module")
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


def conn_for(t: dict[str, Any], *, superuser: bool = False) -> TargetConnection:
    return TargetConnection(
        host=t["host"],
        port=t["port"],
        dbname=t["dbname"],
        username=t["admin_user"] if superuser else t["role"],
        password=SecretStr(t["admin_password"] if superuser else t["password"]),
        sslmode="disable",
    )


async def test_session_is_hardened_and_verified(target: dict[str, Any]) -> None:
    async with InspectionGateway.open(conn_for(target), policy=LOCAL, limits=FAST) as gw:
        settings = await gw.session_settings()

    assert settings["default_transaction_read_only"] == "on"
    assert settings["statement_timeout"] == "300ms"
    assert settings["lock_timeout"] == "200ms"
    assert settings["search_path"] == "pg_catalog, public"
    assert settings["application_name"] == "querydoctor-inspector"


async def test_capabilities_of_restricted_role(target: dict[str, Any]) -> None:
    async with InspectionGateway.open(conn_for(target), policy=LOCAL) as gw:
        caps = await gw.capabilities()

    assert caps.server_version_num >= 170000
    assert caps.is_superuser is False
    assert caps.can_read_all_stats is True
    assert caps.has_pg_stat_statements is False
    assert "public" in caps.schemas


async def test_superuser_connections_are_refused(target: dict[str, Any]) -> None:
    with pytest.raises(RoleTooPrivilegedError):
        async with InspectionGateway.open(conn_for(target, superuser=True), policy=LOCAL):
            pass


async def test_explain_returns_plain_plan_without_executing(target: dict[str, Any]) -> None:
    async with InspectionGateway.open(conn_for(target), policy=LOCAL) as gw:
        result = await gw.explain(
            "SELECT * FROM orders WHERE customer_id = 42 ORDER BY created_at DESC LIMIT 20"
        )

    plan = result.plan_document[0]["Plan"]
    assert plan["Node Type"] == "Limit"
    assert "Actual Rows" not in json.dumps(result.plan_document)
    assert result.generic_plan is False


async def test_parameterized_queries_use_generic_plan(target: dict[str, Any]) -> None:
    async with InspectionGateway.open(conn_for(target), policy=LOCAL) as gw:
        result = await gw.explain("SELECT * FROM orders WHERE customer_id = $1 LIMIT 20")

    assert result.generic_plan is True
    assert result.plan_document[0]["Plan"]["Node Type"] == "Limit"


async def test_dml_is_refused_by_the_validator(target: dict[str, Any]) -> None:
    async with InspectionGateway.open(conn_for(target), policy=LOCAL) as gw:
        with pytest.raises(SqlNotAllowedError):
            await gw.explain("DELETE FROM orders")


async def test_read_only_session_holds_even_if_validator_is_bypassed(
    target: dict[str, Any],
) -> None:
    async with InspectionGateway.open(conn_for(target), policy=LOCAL) as gw:
        # Layer 3 (SECURITY §4.1): run writes through the hardened session directly.
        for statement in (
            "EXPLAIN ANALYZE DELETE FROM orders",
            "CREATE TABLE sneaky (id int)",
            "SET default_transaction_read_only = off; DELETE FROM orders",
        ):
            with pytest.raises(SqlNotAllowedError):
                await gw._unsafe_execute_for_tests(statement)

    with psycopg.connect(_db_url(target["dbname"])) as check:
        assert check.execute("SELECT count(*) FROM orders").fetchone() == (3000,)


async def test_statement_timeout_is_enforced(target: dict[str, Any]) -> None:
    async with InspectionGateway.open(conn_for(target), policy=LOCAL, limits=FAST) as gw:
        with pytest.raises(TargetTimeoutError):
            await gw._unsafe_execute_for_tests("SELECT pg_sleep(5)")


async def test_lock_timeout_is_enforced(target: dict[str, Any]) -> None:
    with psycopg.connect(_db_url(target["dbname"])) as locker:
        locker.execute("LOCK TABLE orders IN ACCESS EXCLUSIVE MODE")
        async with InspectionGateway.open(conn_for(target), policy=LOCAL, limits=FAST) as gw:
            with pytest.raises(TargetTimeoutError):
                await gw.explain("SELECT * FROM orders WHERE id = 1")
        locker.rollback()


async def test_unqualified_user_function_is_refused_by_pg_proc_check(
    target: dict[str, Any],
) -> None:
    async with InspectionGateway.open(conn_for(target), policy=LOCAL) as gw:
        with pytest.raises(SqlNotAllowedError) as info:
            await gw.explain("SELECT myfn(customer_id) FROM orders")

    assert "public.myfn" in str(info.value.details)


async def test_user_function_allowed_with_opt_in(target: dict[str, Any]) -> None:
    async with InspectionGateway.open(conn_for(target), policy=LOCAL) as gw:
        result = await gw.explain(
            "SELECT myfn(customer_id) FROM orders", sql_policy=SqlPolicy(allow_user_functions=True)
        )

    assert result.plan_document[0]["Plan"]["Node Type"] == "Seq Scan"


async def test_schema_snapshot_redacts_value_statistics(target: dict[str, Any]) -> None:
    async with InspectionGateway.open(conn_for(target), policy=LOCAL) as gw:
        result = await gw.explain("SELECT * FROM orders WHERE customer_id = 1")
        snapshot = await gw.schema_snapshot(result.validated.metadata.tables)

    text = snapshot.model_dump_json()
    assert "secret-" not in text
    assert "customer.example" not in text
    assert "most_common_vals" not in text
    assert "histogram_bounds" not in text
    table = snapshot.tables[0]
    assert (table.schema_name, table.name) == ("public", "orders")
    assert table.estimated_rows == pytest.approx(3000, rel=0.05)
    assert {i.name for i in snapshot.indexes} == {"orders_pkey", "orders_customer_id_idx"}
    email = next(c for c in snapshot.columns if c.name == "email")
    assert email.data_type == "text"
    assert email.n_distinct is not None


async def test_blocked_target_never_connects(target: dict[str, Any]) -> None:
    public_only = TargetPolicy(allow_private=False)

    with pytest.raises(TargetBlockedError):
        async with InspectionGateway.open(conn_for(target), policy=public_only):
            pass


async def test_wrong_password_is_unreachable_and_does_not_leak(target: dict[str, Any]) -> None:
    bad = conn_for(target).model_copy(update={"password": SecretStr("wrong-password-xyz")})

    with pytest.raises(TargetUnreachableError) as info:
        async with InspectionGateway.open(bad, policy=LOCAL):
            pass

    assert "wrong-password-xyz" not in str(info.value)
    assert "wrong-password-xyz" not in repr(bad)


async def test_concurrent_gateways_do_not_interfere(target: dict[str, Any]) -> None:
    async def one() -> str:
        async with InspectionGateway.open(conn_for(target), policy=LOCAL) as gw:
            r = await gw.explain("SELECT id FROM orders WHERE id = 7")
            return str(r.plan_document[0]["Plan"]["Node Type"])

    node_types = set(await asyncio.gather(one(), one(), one()))

    assert len(node_types) == 1
    assert node_types <= {"Index Scan", "Index Only Scan"}
