"""A client that disconnects while the SSE stream is talking to the database must close cleanly.

Starlette cancels a streaming response through an anyio cancel scope, which is level-triggered,
so every await in the cleanup is cancelled too.

F1 (2026-10-18, intermittent e2e 500: "can't change 'autocommit' now: connection in transaction
status ACTIVE") was a disconnect landing during the pool's pre-ping `SELECT 1` of a reused
connection. psycopg's attempt to cancel the query is itself cancelled, so the query stays ACTIVE,
and the `finally` in SQLAlchemy's psycopg `do_ping` then tries to restore `autocommit`, raising a
ProgrammingError that replaces the CancelledError. The connection is invalidated (the pool
stays usable), but the error escaped the stream and was logged as an unhandled 500. Reproduced
by `test_a_disconnect_during_the_pre_ping_closes_the_stream_cleanly`; fixed by shielding each
database round trip in `api/sse.py`."""

import uuid
from typing import Any

import anyio
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.api import sse
from querycure.api.process_metrics import ProcessMetrics
from querycure.db.engine import make_engine
from querycure.domain.runs import RunStatus

pytestmark = pytest.mark.integration


class _Subscription:
    async def wait(self, seconds: float) -> bool:
        await anyio.sleep(seconds)
        return False

    def close(self) -> None:
        pass


class _Hub:
    def subscribe(self, run_id: uuid.UUID) -> _Subscription:
        return _Subscription()


async def _slow_list_events(conn: AsyncConnection, **_: Any) -> list[Any]:
    await conn.execute(text("SELECT pg_sleep(0.5)"))
    return []


async def test_a_disconnect_mid_query_leaves_the_pool_usable(
    migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sse, "list_events", _slow_list_events)
    # One connection, so the next checkout must reuse the one the stream held.
    engine = make_engine(migrated_db, set_role="qc_app", pool_size=1, max_overflow=0)
    hub: Any = _Hub()  # stands in for EventHub: no LISTEN connection needed
    try:
        with anyio.move_on_after(0.1):  # the client goes away while pg_sleep runs
            async for _ in sse.event_stream(
                engine, hub, uuid.uuid4(), after_seq=0, heartbeat_seconds=5
            ):
                pass
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT 1"))).scalar_one() == 1
    finally:
        await engine.dispose()


async def _running(conn: AsyncConnection, run_id: uuid.UUID) -> RunStatus:
    return RunStatus.RUNNING


async def test_a_disconnect_during_the_pre_ping_closes_the_stream_cleanly(
    migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A live run, so the stream would keep waiting: the disconnect must end it, not a status.
    monkeypatch.setattr(sse, "get_run_status", _running)
    engine = make_engine(migrated_db, set_role="qc_app", pool_size=1, max_overflow=0)
    hub: Any = _Hub()
    try:
        async with engine.connect() as conn:  # a reused connection is pre-pinged; a fresh one not
            await conn.execute(text("SELECT 1"))
        # Stretch the pre-ping so the disconnect lands inside it deterministically.
        engine.dialect.__dict__["_dialect_specific_select_one"] = "SELECT pg_sleep(0.5)"
        with anyio.move_on_after(0.1) as scope:
            async for _ in sse.event_stream(
                engine, hub, uuid.uuid4(), after_seq=0, heartbeat_seconds=5
            ):
                pass
        assert scope.cancelled_caught
        engine.dialect.__dict__["_dialect_specific_select_one"] = "SELECT 1"
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT 1"))).scalar_one() == 1
    finally:
        await engine.dispose()


async def _broken_list_events(conn: AsyncConnection, **_: Any) -> list[Any]:
    raise RuntimeError("boom")


async def test_a_server_error_ends_the_stream_and_is_counted(
    migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The response has already started, so a 500 can no longer be sent: the stream ends, the
    browser reconnects with Last-Event-ID, and the failure is logged and counted."""
    monkeypatch.setattr(sse, "list_events", _broken_list_events)
    engine = make_engine(migrated_db, set_role="qc_app", pool_size=1, max_overflow=0)
    metrics = ProcessMetrics()
    hub: Any = _Hub()
    try:
        chunks = [
            c
            async for c in sse.event_stream(
                engine, hub, uuid.uuid4(), after_seq=0, heartbeat_seconds=5, metrics=metrics
            )
        ]
        assert chunks == ["retry: 3000\n\n"]
        assert metrics.sse_closed_by["error"] == 1
        assert metrics.sse_active == 0
    finally:
        await engine.dispose()


async def test_stream_outcomes_are_counted(
    migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = make_engine(migrated_db, set_role="qc_app", pool_size=1, max_overflow=0)
    metrics = ProcessMetrics()
    hub: Any = _Hub()
    try:
        # A run that no longer exists: the stream ends by itself.
        async for _ in sse.event_stream(
            engine, hub, uuid.uuid4(), after_seq=0, heartbeat_seconds=5, metrics=metrics
        ):
            pass
        # A live run: only the client going away ends it.
        monkeypatch.setattr(sse, "get_run_status", _running)
        with anyio.move_on_after(0.2):
            async for _ in sse.event_stream(
                engine, hub, uuid.uuid4(), after_seq=0, heartbeat_seconds=5, metrics=metrics
            ):
                pass
        assert metrics.sse_closed_by["ended"] == 1
        assert metrics.sse_closed_by["client_gone"] == 1
        assert metrics.sse_active == 0
    finally:
        await engine.dispose()
