"""SSE stream + history endpoint (T2.3). The resume test uses a real uvicorn server over TCP:
httpx's ASGI transport buffers whole responses and cannot exercise a live stream."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx2 as httpx
import psycopg
import pytest
import uvicorn
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.api.main import create_app
from querycure.core.config import Settings
from querycure.db.engine import make_engine
from querycure.domain.runs import RunOutcome, RunStatus
from querycure.events.emitter import change_status, emit
from querycure.events.types import EventType

pytestmark = pytest.mark.integration

HEARTBEAT = 0.3


@dataclass
class Api:
    app: FastAPI
    engine: AsyncEngine
    client: httpx.AsyncClient
    user_id: uuid.UUID


@pytest.fixture
async def api(migrated_db: str) -> AsyncIterator[Api]:
    engine = make_engine(migrated_db, set_role="qc_app")
    app = create_app(Settings(_env_file=None, sse_heartbeat_seconds=HEARTBEAT), engine=engine)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/v1/session")
        user_id = uuid.UUID((await client.get("/api/v1/me")).json()["user"]["id"])
        yield Api(app, engine, client, user_id)
    if app.state.event_hub is not None:
        await app.state.event_hub.close()
    await engine.dispose()


@pytest.fixture
async def server_url(api: Api) -> AsyncIterator[str]:
    config = uvicorn.Config(api.app, host="127.0.0.1", port=0, log_level="warning", lifespan="off")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:  # noqa: ASYNC110 - uvicorn exposes a flag, not an event
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    await task


def new_run(owner: psycopg.Connection, user_id: uuid.UUID, status: str = "running") -> uuid.UUID:
    inv = owner.execute(
        "INSERT INTO investigations (user_id, title, objective, modes) "
        "VALUES (%s, 't', 'o', ARRAY['offline']) RETURNING id",
        (user_id,),
    ).fetchone()
    assert inv is not None
    run = owner.execute(
        "INSERT INTO investigation_runs (investigation_id, run_number, kind, status, budget, "
        "usage) VALUES (%s, 1, 'initial', %s, '{}', '{}') RETURNING id",
        (inv[0], status),
    ).fetchone()
    assert run is not None
    return run[0]  # type: ignore[no-any-return]


async def emit_many(engine: AsyncEngine, run_id: uuid.UUID, n: int, delay: float = 0.0) -> None:
    for i in range(n):
        async with engine.begin() as conn:
            await emit(conn, run_id, EventType.AGENT_SUMMARY, {"agent": "qa", "text": str(i)})
        if delay:
            await asyncio.sleep(delay)


async def finish(engine: AsyncEngine, run_id: uuid.UUID) -> None:
    async with engine.begin() as conn:
        await change_status(conn, run_id, RunStatus.COMPLETED, outcome=RunOutcome.INCONCLUSIVE)


async def sse_events(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    """Minimal SSE parser: yields {id, event, data} per dispatched event and {comment} lines."""
    fields: dict[str, Any] = {}
    async for line in response.aiter_lines():
        if line == "":
            if "data" in fields:
                yield fields
            fields = {}
        elif line.startswith(":"):
            yield {"comment": line[1:].strip()}
        else:
            name, _, value = line.partition(": ")
            fields[name] = json.loads(value) if name == "data" else value


def cookies(api: Api) -> dict[str, str]:
    return {"qc_session": api.client.cookies["qc_session"]}


async def test_reconnect_with_last_event_id_delivers_every_event_exactly_once(
    api: Api, server_url: str, owner: psycopg.Connection
) -> None:
    run_id = new_run(owner, api.user_id)
    total = 40
    received: list[int] = []

    async def producer() -> None:
        await emit_many(api.engine, run_id, total, delay=0.01)
        await finish(api.engine, run_id)

    async with httpx.AsyncClient(base_url=server_url, cookies=cookies(api), timeout=10) as c:
        url = f"/api/v1/runs/{run_id}/events"
        async with c.stream("GET", url) as first:
            assert first.status_code == 200
            assert first.headers["content-type"].startswith("text/event-stream")
            produce = asyncio.create_task(producer())  # live events, not only backlog
            async for ev in sse_events(first):
                if "data" in ev:
                    received.append(int(ev["id"]))
                    if len(received) == 10:
                        break  # drop the connection mid-run
        await asyncio.sleep(0.1)  # events keep arriving while disconnected

        async with c.stream("GET", url, headers={"Last-Event-ID": str(received[-1])}) as second:
            last: dict[str, Any] = {}
            async for ev in sse_events(second):
                if "data" in ev:
                    received.append(int(ev["id"]))
                    last = ev
        await produce

    assert received == list(range(1, total + 2))  # 40 summaries + the terminal status event
    assert last["event"] == "run.status_changed"
    assert last["data"]["payload"] == {
        "from": "running",
        "to": "completed",
        "outcome": "inconclusive",
    }


async def test_wire_format(api: Api, server_url: str, owner: psycopg.Connection) -> None:
    run_id = new_run(owner, api.user_id)
    await emit_many(api.engine, run_id, 1)
    await finish(api.engine, run_id)

    async with (
        httpx.AsyncClient(base_url=server_url, cookies=cookies(api), timeout=10) as c,
        c.stream("GET", f"/api/v1/runs/{run_id}/events") as r,
    ):
        events = [ev async for ev in sse_events(r) if "data" in ev]

    first = events[0]
    assert first["id"] == "1"
    assert first["event"] == "agent.summary"
    data = first["data"]
    assert set(data) == {"run_id", "seq", "ts", "type", "payload"}
    assert data["run_id"] == str(run_id)
    assert data["seq"] == 1
    assert data["ts"].endswith("Z")
    assert len(events) == 2


async def test_after_seq_query_parameter_skips_seen_events(
    api: Api, server_url: str, owner: psycopg.Connection
) -> None:
    run_id = new_run(owner, api.user_id)
    await emit_many(api.engine, run_id, 5)
    await finish(api.engine, run_id)

    async with (
        httpx.AsyncClient(base_url=server_url, cookies=cookies(api), timeout=10) as c,
        c.stream("GET", f"/api/v1/runs/{run_id}/events?after_seq=3") as r,
    ):
        ids = [int(ev["id"]) async for ev in sse_events(r) if "data" in ev]

    assert ids == [4, 5, 6]


async def test_idle_stream_sends_heartbeats(
    api: Api, server_url: str, owner: psycopg.Connection
) -> None:
    run_id = new_run(owner, api.user_id)

    async with (
        httpx.AsyncClient(base_url=server_url, cookies=cookies(api), timeout=10) as c,
        c.stream("GET", f"/api/v1/runs/{run_id}/events") as r,
    ):
        async for ev in sse_events(r):
            if ev.get("comment") == "heartbeat":
                break


async def test_caught_up_terminal_run_closes_immediately(
    api: Api, server_url: str, owner: psycopg.Connection
) -> None:
    run_id = new_run(owner, api.user_id)
    await finish(api.engine, run_id)

    async with (
        httpx.AsyncClient(base_url=server_url, cookies=cookies(api), timeout=10) as c,
        c.stream("GET", f"/api/v1/runs/{run_id}/events", headers={"Last-Event-ID": "1"}) as r,
    ):
        events = [ev async for ev in sse_events(r)]

    assert [e for e in events if "data" in e] == []


async def test_stream_requires_session(api: Api, owner: psycopg.Connection) -> None:
    run_id = new_run(owner, api.user_id)
    api.client.cookies.clear()

    r = await api.client.get(f"/api/v1/runs/{run_id}/events")

    assert r.status_code == 401


async def test_other_users_run_is_not_found(api: Api, owner: psycopg.Connection) -> None:
    run_id = new_run(owner, uuid.uuid4())

    stream = await api.client.get(f"/api/v1/runs/{run_id}/events")
    history = await api.client.get(f"/api/v1/runs/{run_id}/events/history")

    assert stream.status_code == 404
    assert history.status_code == 404
    assert stream.json()["error"]["code"] == "NOT_FOUND"


async def test_malformed_last_event_id_is_rejected(api: Api, owner: psycopg.Connection) -> None:
    run_id = new_run(owner, api.user_id)

    r = await api.client.get(f"/api/v1/runs/{run_id}/events", headers={"Last-Event-ID": "-1"})

    assert r.status_code == 400


async def test_history_paginates_in_seq_order(api: Api, owner: psycopg.Connection) -> None:
    run_id = new_run(owner, api.user_id)
    await emit_many(api.engine, run_id, 5)

    seen: list[int] = []
    cursor: str | None = None
    while True:
        params: dict[str, str | int] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = (await api.client.get(f"/api/v1/runs/{run_id}/events/history", params=params)).json()
        seen.extend(item["seq"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert seen == [1, 2, 3, 4, 5]


async def test_history_rejects_forged_cursor(api: Api, owner: psycopg.Connection) -> None:
    run_id = new_run(owner, api.user_id)

    r = await api.client.get(f"/api/v1/runs/{run_id}/events/history", params={"cursor": "%%%"})

    assert r.status_code == 400
