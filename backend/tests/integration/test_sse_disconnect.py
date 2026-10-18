"""A client that disconnects while the SSE stream is mid-query must not poison the pool.

Starlette cancels a streaming response through an anyio cancel scope, which is level-triggered,
so the `async with engine.connect()` cleanup runs under cancellation too. This path is safe (the
test passes). It was written while investigating an intermittent e2e error, 1 in 3 runs on
2026-10-18: "can't change 'autocommit' now: connection in transaction status ACTIVE" during the
pre-ping of an SSE checkout. It does **not** reproduce that error; its cause is still open
(FINAL_BACKEND_DEPLOYMENT_READINESS §8)."""

import uuid
from typing import Any

import anyio
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.api import sse
from querycure.db.engine import make_engine

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
