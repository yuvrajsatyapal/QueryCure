"""EventHub (T2.3): one LISTEN connection per process; survives losing it."""

import asyncio
import uuid
from collections.abc import AsyncIterator

import psycopg
import pytest

from querycure.events.hub import EventHub
from querycure.events.types import NOTIFY_CHANNEL

pytestmark = pytest.mark.integration


@pytest.fixture
async def hub(migrated_db: str) -> AsyncIterator[EventHub]:
    async def connect() -> psycopg.AsyncConnection:
        conn = await psycopg.AsyncConnection.connect(migrated_db, autocommit=True)
        await conn.execute("SET application_name = 'qc_test_event_hub'")
        return conn

    h = EventHub(connect)
    yield h
    await h.close()


def notify(owner: psycopg.Connection, run_id: uuid.UUID) -> None:
    owner.execute("SELECT pg_notify(%s, %s)", (NOTIFY_CHANNEL, str(run_id)))


async def test_notification_wakes_only_that_runs_subscribers(
    hub: EventHub, owner: psycopg.Connection
) -> None:
    run_a, run_b = uuid.uuid4(), uuid.uuid4()
    sub_a, sub_b = hub.subscribe(run_a), hub.subscribe(run_b)
    await asyncio.wait_for(hub.listening.wait(), 5)
    await sub_a.wait(0.05)  # drain the wake-up sent when listening started
    await sub_b.wait(0.05)

    notify(owner, run_a)

    assert await sub_a.wait(2)
    assert not await sub_b.wait(0.3)


async def test_listener_reconnects_and_wakes_everyone_after_losing_its_connection(
    hub: EventHub, owner: psycopg.Connection
) -> None:
    run_id = uuid.uuid4()
    sub = hub.subscribe(run_id)
    await asyncio.wait_for(hub.listening.wait(), 5)
    await sub.wait(0.05)

    owner.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE application_name = 'qc_test_event_hub'"
    )
    # Woken by the reconnect itself: events committed during the outage get re-read.
    assert await sub.wait(5)
    await asyncio.wait_for(hub.listening.wait(), 5)

    notify(owner, run_id)
    assert await sub.wait(2)


async def test_unsubscribed_runs_are_forgotten(hub: EventHub) -> None:
    sub = hub.subscribe(uuid.uuid4())
    sub.close()

    assert hub._subscribers == {}
