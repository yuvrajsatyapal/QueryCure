"""Idempotency-Key on `POST /experiments/{id}/replay` (API_DESIGN §1, Phase 5 priority 1).

A replay queues expensive sandbox benchmarks, so a retried request (double click, browser
retry after a timeout, a client that resends on a dropped connection) must return the original
attempt, never queue a second benchmark. Keys are scoped to the user and the operation.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx2 as httpx
import psycopg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.api.main import create_app
from querycure.db.engine import make_engine
from querycure.sandbox.provisioner import SandboxProvisioner
from tests.integration.test_experiment_replay import RECENT, SETTINGS, finalized_sandbox_run

pytestmark = pytest.mark.integration


async def _client(app: Any) -> httpx.AsyncClient:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test")
    await client.post("/api/v1/session")
    client.headers["X-CSRF-Token"] = client.cookies["qc_csrf"]
    return client


@pytest.fixture
async def app(migrated_db: str) -> AsyncIterator[Any]:
    engine = make_engine(migrated_db, set_role="qc_app")
    yield create_app(SETTINGS, engine=engine)
    await engine.dispose()


@pytest.fixture
async def api(app: Any) -> AsyncIterator[httpx.AsyncClient]:
    client = await _client(app)
    yield client
    await client.aclose()


@pytest.fixture(autouse=True)
def _no_active_runs(owner: psycopg.Connection) -> None:
    owner.execute(
        "UPDATE investigation_runs SET status = 'cancelled', finalized_at = now() "
        "WHERE status IN ('queued', 'running', 'awaiting_approval', 'cancelling')"
    )


def _counts(owner: psycopg.Connection, experiment_id: str) -> tuple[int, int, int]:
    row = owner.execute(
        "SELECT (SELECT count(*) FROM replay_attempts WHERE source_experiment_id = %(e)s), "
        "(SELECT count(*) FROM investigation_runs r JOIN replay_attempts a "
        " ON a.replay_run_id = r.id WHERE a.source_experiment_id = %(e)s), "
        "(SELECT count(*) FROM jobs j JOIN replay_attempts a ON a.replay_run_id = j.run_id "
        " WHERE a.source_experiment_id = %(e)s AND j.kind = 'experiment_replay')",
        {"e": experiment_id},
    ).fetchone()
    assert row is not None
    return row[0], row[1], row[2]


def _replay(api: httpx.AsyncClient, experiment_id: str, key: str | None) -> Any:
    headers = {"Idempotency-Key": key} if key else {}
    return api.post(
        f"/api/v1/experiments/{experiment_id}/replay", json={"confirm_ddl": True}, headers=headers
    )


async def _unfinalized_experiment(api: httpx.AsyncClient, owner: psycopg.Connection) -> str:
    created = await api.post(
        "/api/v1/investigations",
        json={
            "title": "t",
            "objective": "o",
            "modes": ["sandbox_benchmark"],
            "workload_id": "orders_ecommerce@v1:sf=0.1:seed=42",
            "query": RECENT,
        },
    )
    experiment_id = str(uuid.uuid4())
    owner.execute(
        "INSERT INTO experiments (id, run_id, round, kind, approval_request_id, "
        "config_artifact_id, engine_version, row_profile, seed, status) VALUES "
        "(%s, %s, 0, 'single', uuid_generate_v4(), uuid_generate_v4(), 'bench@2', "
        "'qc-row-v1', 1, 'completed')",
        (experiment_id, created.json()["run"]["id"]),
    )
    # Stopped but never finalized: frees the run slot, stays `source_not_finalized`.
    owner.execute(
        "UPDATE investigation_runs SET status = 'cancelled' WHERE id = %s",
        (created.json()["run"]["id"],),
    )
    return experiment_id


async def test_key_must_be_a_uuid(api: httpx.AsyncClient) -> None:
    r = await _replay(api, str(uuid.uuid4()), "not-a-uuid")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "BAD_REQUEST"


async def test_not_replayable_retry_returns_the_same_attempt(
    api: httpx.AsyncClient, owner: psycopg.Connection
) -> None:
    experiment_id = await _unfinalized_experiment(api, owner)
    key = str(uuid.uuid4())

    first = await _replay(api, experiment_id, key)
    second = await _replay(api, experiment_id, key)

    assert first.status_code == second.status_code == 422
    ids = [r.json()["error"]["details"][0]["replay_attempt_id"] for r in (first, second)]
    assert ids[0] == ids[1]
    assert _counts(owner, experiment_id) == (1, 0, 0)


async def test_same_key_for_another_experiment_is_a_conflict(
    api: httpx.AsyncClient, owner: psycopg.Connection
) -> None:
    key = str(uuid.uuid4())
    one = await _unfinalized_experiment(api, owner)
    two = await _unfinalized_experiment(api, owner)
    await _replay(api, one, key)

    r = await _replay(api, two, key)

    assert r.status_code == 409
    assert r.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert one not in r.text  # nothing about the original request is disclosed
    assert _counts(owner, two) == (0, 0, 0)


async def test_keys_are_scoped_per_user(
    app: Any, api: httpx.AsyncClient, owner: psycopg.Connection
) -> None:
    """Another user's identical key neither conflicts nor reveals the first user's attempt."""
    key = str(uuid.uuid4())
    mine = await _unfinalized_experiment(api, owner)
    await _replay(api, mine, key)
    # The local profile has one user; make the second session belong to a different user.
    other = await _client(app)
    try:
        user_id = owner.execute(
            "INSERT INTO users (kind, display_name) VALUES ('anonymous', 'other') RETURNING id"
        ).fetchone()
        assert user_id is not None
        owner.execute(
            "UPDATE sessions SET user_id = %s WHERE id = (SELECT id FROM sessions "
            "ORDER BY created_at DESC LIMIT 1)",
            (user_id[0],),
        )
        theirs = await _unfinalized_experiment(other, owner)

        r = await _replay(other, theirs, key)
        foreign = await _replay(other, mine, str(uuid.uuid4()))
    finally:
        await other.aclose()

    assert r.status_code == 422  # their own attempt, not a conflict with mine
    assert foreign.status_code == 404  # my experiment stays invisible, key or not
    assert _counts(owner, theirs) == (1, 0, 0)


async def test_retries_and_concurrent_duplicates_create_one_replay(
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)

    # 1. A crash between creating the replay run and committing (here: the job insert fails)
    #    rolls everything back; the retry with the same key then succeeds exactly once.
    from querycure.jobs import queue

    real_enqueue = queue.enqueue
    calls = {"n": 0}

    async def failing_enqueue(*a: Any, **k: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated crash before commit")
        return await real_enqueue(*a, **k)

    monkeypatch.setattr("querycure.replay.experiment_replay.queue.enqueue", failing_enqueue)
    key = str(uuid.uuid4())
    crashed = await _replay(api, experiment_id, key)
    assert crashed.status_code == 500
    assert _counts(owner, experiment_id) == (0, 0, 0)

    # 2. Five identical requests at once (a double-clicking user plus retries).
    responses = await asyncio.gather(*(_replay(api, experiment_id, key) for _ in range(5)))
    assert {r.status_code for r in responses} == {202}, [r.text for r in responses]
    attempt_ids = {r.json()["id"] for r in responses}
    assert len(attempt_ids) == 1
    assert _counts(owner, experiment_id) == (1, 1, 1)

    # 3. A later retry returns the original even though that replay now occupies a run slot:
    #    fill the user's remaining slot so a *new* replay would be refused with 429.
    owner.execute(
        "UPDATE investigation_runs SET status = 'running' WHERE id = ("
        "SELECT id FROM investigation_runs WHERE kind = 'initial' LIMIT 1)"
    )
    later = await _replay(api, experiment_id, key)
    assert later.status_code == 202
    assert later.json()["id"] in attempt_ids
    fresh = await _replay(api, experiment_id, str(uuid.uuid4()))
    assert fresh.status_code == 429
    assert _counts(owner, experiment_id) == (1, 1, 1)
    stored = owner.execute(
        "SELECT idempotency_key, idempotency_request_hash IS NOT NULL FROM replay_attempts "
        "WHERE source_experiment_id = %s",
        (experiment_id,),
    ).fetchone()
    assert stored == (key, True)

    # 4. Without a key, each confirmation is still a new attempt (unchanged behaviour).
    owner.execute(
        "UPDATE investigation_runs SET status = 'cancelled', finalized_at = now() "
        "WHERE status IN ('queued', 'running')"
    )
    unkeyed = await _replay(api, experiment_id, None)
    assert unkeyed.status_code == 202
    assert unkeyed.json()["id"] not in attempt_ids
