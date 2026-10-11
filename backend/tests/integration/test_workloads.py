import uuid
from collections.abc import Iterator

import psycopg
import pytest

from querycure.workloads.loader import load_workload, table_checksums
from querycure.workloads.registry import WORKLOADS, WorkloadRef

from .conftest import ADMIN_URL, _db_url

pytestmark = pytest.mark.integration


@pytest.fixture
def fresh_db() -> Iterator[str]:
    try:
        admin = psycopg.connect(ADMIN_URL, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("metadata DB not reachable")
    names: list[str] = []

    def make() -> str:
        name = f"qc_wl_{uuid.uuid4().hex[:10]}"
        admin.execute(f'CREATE DATABASE "{name}"')
        names.append(name)
        return _db_url(name)

    yield make  # type: ignore[misc]
    for name in names:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    admin.close()


def load(url: str, ref: str) -> dict[str, str]:
    with psycopg.connect(url, autocommit=True) as conn:
        parsed = WorkloadRef.parse(ref)
        load_workload(conn, parsed)
        return table_checksums(conn, WORKLOADS[parsed.name].tables)


def test_same_seed_produces_identical_tables(fresh_db) -> None:  # type: ignore[no-untyped-def]
    ref = "orders_ecommerce@v1:sf=0.01:seed=42"

    assert load(fresh_db(), ref) == load(fresh_db(), ref)


def test_different_seed_produces_different_data(fresh_db) -> None:  # type: ignore[no-untyped-def]
    a = load(fresh_db(), "orders_ecommerce@v1:sf=0.01:seed=42")
    b = load(fresh_db(), "orders_ecommerce@v1:sf=0.01:seed=7")

    assert a["orders"] != b["orders"]


def test_scale_factor_controls_row_counts(fresh_db) -> None:  # type: ignore[no-untyped-def]
    url = fresh_db()
    with psycopg.connect(url, autocommit=True) as conn:
        load_workload(conn, WorkloadRef.parse("orders_ecommerce@v1:sf=0.01:seed=42"))
        orders = conn.execute("SELECT count(*) FROM orders").fetchone()
        customers = conn.execute("SELECT count(*) FROM customers").fetchone()
        hot = conn.execute("SELECT count(*) FROM orders WHERE customer_id = 1024").fetchone()
        indexes = conn.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'orders' ORDER BY 1"
        ).fetchall()

    assert orders == (10_000,)
    assert customers == (2_000,)
    assert hot is not None
    assert hot[0] > 50  # hot customer for the canonical query's param set
    assert indexes == [("orders_pkey",)]  # the missing composite index is the injected problem


def test_rewrite_trap_not_in_and_not_exists_really_differ(fresh_db) -> None:  # type: ignore[no-untyped-def]
    url = fresh_db()
    with psycopg.connect(url, autocommit=True) as conn:
        load_workload(conn, WorkloadRef.parse("rewrite_trap@v1:sf=0.01:seed=42"))
        not_in = conn.execute(
            "SELECT count(*) FROM accounts "
            "WHERE region_code NOT IN (SELECT region_code FROM closed_regions)"
        ).fetchone()
        not_exists = conn.execute(
            "SELECT count(*) FROM accounts a WHERE NOT EXISTS "
            "(SELECT 1 FROM closed_regions c WHERE c.region_code = a.region_code)"
        ).fetchone()

    assert not_in == (0,)  # a NULL in the subquery makes NOT IN match nothing
    assert not_exists is not None
    assert not_exists[0] > 0


def test_no_benefit_query_is_already_an_index_lookup(fresh_db) -> None:  # type: ignore[no-untyped-def]
    url = fresh_db()
    with psycopg.connect(url, autocommit=True) as conn:
        load_workload(conn, WorkloadRef.parse("no_benefit@v1:sf=1:seed=42"))
        plan = conn.execute(
            "EXPLAIN (FORMAT JSON) SELECT value FROM app_settings WHERE key = 'feature_17'"
        ).fetchone()

    assert plan is not None
    assert plan[0][0]["Plan"]["Node Type"] in {"Index Scan", "Index Only Scan", "Seq Scan"}
    assert plan[0][0]["Plan"]["Total Cost"] < 10
