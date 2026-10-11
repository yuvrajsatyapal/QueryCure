"""Workload statistics templates (T2.9) against the seeded target, as the restricted role."""

import asyncio
from typing import Any

import psycopg
import pytest

from querycure.connectors.inspection_gateway import InspectionGateway
from querycure.core.errors import TargetQueryError
from querycure.sql.validator import TableRef

from .conftest import _db_url
from .test_inspection_gateway import FAST, LOCAL, conn_for

pytestmark = pytest.mark.integration


async def test_statement_stats_are_refused_without_the_extension(target: dict[str, Any]) -> None:
    async with InspectionGateway.open(conn_for(target), policy=LOCAL, limits=FAST) as gw:
        with pytest.raises(TargetQueryError, match="pg_stat_statements"):
            await gw.statement_stats()


async def test_activity_summary_is_aggregate_only(target: dict[str, Any]) -> None:
    # Another session sits idle in a transaction so there is something to aggregate.
    other = await psycopg.AsyncConnection.connect(_db_url(target["dbname"]))
    await other.execute("BEGIN")
    await other.execute("SELECT 1")
    try:
        async with InspectionGateway.open(conn_for(target), policy=LOCAL, limits=FAST) as gw:
            buckets = await gw.activity_summary()
    finally:
        await other.rollback()
        await other.close()

    assert any(b.state == "idle in transaction" and b.sessions >= 1 for b in buckets)
    fields = set(buckets[0].model_dump())
    assert fields == {"state", "wait_event_type", "sessions", "longest_xact_seconds"}


async def test_lock_summary_counts_waiting_locks(target: dict[str, Any]) -> None:
    url = _db_url(target["dbname"])
    holder = await psycopg.AsyncConnection.connect(url)
    waiter = await psycopg.AsyncConnection.connect(url)
    await holder.execute("BEGIN")
    await holder.execute("LOCK TABLE orders IN ACCESS EXCLUSIVE MODE")
    blocked = asyncio.create_task(waiter.execute("SELECT count(*) FROM orders"))
    await asyncio.sleep(0.3)
    try:
        async with InspectionGateway.open(conn_for(target), policy=LOCAL, limits=FAST) as gw:
            locks = await gw.lock_summary()
    finally:
        await holder.rollback()
        await blocked
        await holder.close()
        await waiter.close()

    on_orders = [b for b in locks if b.relation == "public.orders"]
    assert any(b.waiting >= 1 for b in on_orders)
    assert any(b.mode == "AccessExclusiveLock" and b.granted >= 1 for b in on_orders)


async def test_table_io_for_named_tables(target: dict[str, Any]) -> None:
    async with InspectionGateway.open(conn_for(target), policy=LOCAL, limits=FAST) as gw:
        rows = await gw.table_io([TableRef(schema_name=None, name="orders")])

    assert [(r.schema_name, r.name) for r in rows] == [("public", "orders")]
    assert rows[0].heap_blks_hit is not None
