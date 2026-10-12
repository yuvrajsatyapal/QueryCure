"""Investigations and runs API (T2.11), as qc_app, through the real app and middleware."""

import asyncio
import base64
import json
import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx2 as httpx
import psycopg
import pytest

from querycure.api.main import create_app
from querycure.core.config import Settings
from querycure.db.engine import make_engine

pytestmark = pytest.mark.integration

PLANS = Path(__file__).parents[1] / "fixtures" / "plans"
SQL = "SELECT * FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 20"
SETTINGS = Settings(_env_file=None, master_key=base64.b64encode(os.urandom(32)).decode())


async def client_for(migrated_db: str) -> AsyncIterator[httpx.AsyncClient]:
    engine = make_engine(migrated_db, set_role="qc_app")
    app = create_app(SETTINGS, engine=engine)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        await client.post("/api/v1/session")
        client.headers["X-CSRF-Token"] = client.cookies["qc_csrf"]
        yield client
    await engine.dispose()


@pytest.fixture
async def api(migrated_db: str) -> AsyncIterator[httpx.AsyncClient]:
    async for c in client_for(migrated_db):
        yield c


@pytest.fixture
async def other_user(
    migrated_db: str, owner: psycopg.Connection
) -> AsyncIterator[httpx.AsyncClient]:
    """A second, distinct user: the local profile has one user, so add an anonymous one."""
    user_id = owner.execute("INSERT INTO users (kind) VALUES ('anonymous') RETURNING id").fetchone()
    assert user_id is not None
    token = uuid.uuid4().hex
    import hashlib

    owner.execute(
        "INSERT INTO sessions (user_id, token_hash, expires_at) "
        "VALUES (%s, %s, now() + interval '1 hour')",
        (user_id[0], hashlib.sha256(token.encode()).hexdigest()),
    )
    async for c in client_for(migrated_db):
        c.cookies.set("qc_session", token)
        yield c


def body(**overrides: Any) -> dict[str, Any]:
    return {
        "title": "Slow customer orders page",
        "objective": "Why is this query slow?",
        "modes": ["offline"],
        "query": SQL,
        "param_sets": [{"name": "hot_customer", "values": [1024]}],
        **overrides,
    }


async def create(api: httpx.AsyncClient, **overrides: Any) -> dict[str, Any]:
    r = await api.post("/api/v1/investigations", json=body(**overrides))
    assert r.status_code == 202, r.text
    return r.json()  # type: ignore[no-any-return]


async def upload_plan(api: httpx.AsyncClient) -> str:
    raw = (PLANS / "pg17_canonical_hot_analyze.json").read_bytes()
    r = await api.post(
        "/api/v1/inspect/plan", content=raw, headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 200, r.text
    return r.json()["artifact_sha256"]  # type: ignore[no-any-return]


@pytest.fixture(autouse=True)
def _no_active_runs(owner: psycopg.Connection) -> None:
    # The concurrency limit counts active runs per user; tests start from a clean slate.
    owner.execute(
        "UPDATE investigation_runs SET status = 'completed', outcome = 'inconclusive' "
        "WHERE status IN ('queued', 'running', 'awaiting_approval', 'cancelling')"
    )


async def test_create_queues_a_run_with_inputs_and_a_job(
    api: httpx.AsyncClient, owner: psycopg.Connection
) -> None:
    plan_sha = await upload_plan(api)

    created = await create(api, plan_artifact_sha256=plan_sha)

    run = created["run"]
    assert created["investigation"]["title"] == "Slow customer orders page"
    assert run["status"] == "queued"
    assert run["run_number"] == 1
    assert run["budget"]["llm_calls"] == 40
    roles = {
        r[0]
        for r in owner.execute("SELECT role FROM run_artifacts WHERE run_id = %s", (run["id"],))
    }
    assert roles == {"input.query", "input.plan", "input.param_sets"}
    job = owner.execute(
        "SELECT kind, status, dedupe_key FROM jobs WHERE run_id = %s", (run["id"],)
    ).fetchone()
    assert job == ("run_start", "pending", f"run_start:{run['id']}")
    first_event = owner.execute(
        "SELECT type, payload FROM investigation_events WHERE run_id = %s AND seq = 1",
        (run["id"],),
    ).fetchone()
    assert first_event == ("run.status_changed", {"from": None, "to": "queued"})


@pytest.mark.parametrize(
    ("overrides", "status", "code"),
    [
        ({"query": "DELETE FROM orders"}, 422, "SQL_NOT_ALLOWED"),
        ({"query": None}, 422, "VALIDATION_ERROR"),
        ({"modes": ["sandbox_benchmark"]}, 403, "FEATURE_DISABLED"),
        ({"modes": ["live_inspection"]}, 422, "VALIDATION_ERROR"),
        ({"plan_artifact_sha256": "f" * 64}, 422, "VALIDATION_ERROR"),
        ({"workload_id": "nope"}, 422, "VALIDATION_ERROR"),
        ({"llm": {"credential_id": str(uuid.uuid4())}}, 403, "FEATURE_DISABLED"),
        ({"unexpected": 1}, 422, "VALIDATION_ERROR"),
        ({"title": ""}, 422, "VALIDATION_ERROR"),
    ],
)
async def test_create_validation(
    api: httpx.AsyncClient, overrides: dict[str, Any], status: int, code: str
) -> None:
    r = await api.post("/api/v1/investigations", json=body(**overrides))

    assert r.status_code == status, r.text
    assert r.json()["error"]["code"] == code


async def test_live_inspection_needs_an_owned_non_production_connection(
    api: httpx.AsyncClient, other_user: httpx.AsyncClient
) -> None:
    missing = await api.post(
        "/api/v1/investigations",
        json=body(modes=["live_inspection"], connection_id=str(uuid.uuid4())),
    )
    assert missing.status_code == 404

    conn = await api.post(
        "/api/v1/connections",
        json={
            "name": "prod",
            "host": "127.0.0.1",
            "port": 5432,
            "dbname": "x",
            "username": "u",
            "password": "p",
            "sslmode": "disable",
            "environment": "production",
            "purpose": "inspection",
        },
    )
    assert conn.status_code == 201, conn.text
    prod = await api.post(
        "/api/v1/investigations",
        json=body(modes=["live_inspection"], connection_id=conn.json()["id"]),
    )
    assert prod.status_code == 409
    assert prod.json()["error"]["code"] == "APPROVAL_REQUIRED"

    foreign = await other_user.post(
        "/api/v1/investigations",
        json=body(modes=["live_inspection"], connection_id=conn.json()["id"]),
    )
    assert foreign.status_code == 404


async def test_idempotency_key_replays_the_original_response(
    api: httpx.AsyncClient, owner: psycopg.Connection
) -> None:
    key = str(uuid.uuid4())
    first = await api.post("/api/v1/investigations", json=body(), headers={"Idempotency-Key": key})
    again = await api.post("/api/v1/investigations", json=body(), headers={"Idempotency-Key": key})

    assert first.status_code == again.status_code == 202
    assert again.json()["run"]["id"] == first.json()["run"]["id"]
    count = owner.execute(
        "SELECT count(*) FROM investigation_runs WHERE idempotency_key = %s", (key,)
    ).fetchone()
    assert count == (1,)


async def test_idempotency_key_with_a_different_body_conflicts(api: httpx.AsyncClient) -> None:
    key = str(uuid.uuid4())
    await api.post("/api/v1/investigations", json=body(), headers={"Idempotency-Key": key})

    r = await api.post(
        "/api/v1/investigations", json=body(title="Other"), headers={"Idempotency-Key": key}
    )

    assert r.status_code == 409
    assert r.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


async def test_another_users_idempotency_key_conflicts_without_leaking(
    api: httpx.AsyncClient, other_user: httpx.AsyncClient
) -> None:
    key = str(uuid.uuid4())
    mine = await api.post("/api/v1/investigations", json=body(), headers={"Idempotency-Key": key})

    theirs = await other_user.post(
        "/api/v1/investigations", json=body(), headers={"Idempotency-Key": key}
    )

    assert theirs.status_code == 409
    assert mine.json()["run"]["id"] not in theirs.text


async def test_concurrent_duplicates_create_one_run(
    api: httpx.AsyncClient, owner: psycopg.Connection
) -> None:
    key = str(uuid.uuid4())

    responses = await asyncio.gather(
        *(
            api.post("/api/v1/investigations", json=body(), headers={"Idempotency-Key": key})
            for _ in range(4)
        )
    )

    assert {r.status_code for r in responses} == {202}
    assert len({r.json()["run"]["id"] for r in responses}) == 1
    count = owner.execute(
        "SELECT count(*) FROM investigation_runs WHERE idempotency_key = %s", (key,)
    ).fetchone()
    assert count == (1,)


async def test_malformed_idempotency_key_is_rejected(api: httpx.AsyncClient) -> None:
    r = await api.post(
        "/api/v1/investigations", json=body(), headers={"Idempotency-Key": "not-a-uuid"}
    )

    assert r.status_code == 400


async def test_concurrent_run_limit(api: httpx.AsyncClient) -> None:
    await create(api)
    await create(api)

    r = await api.post("/api/v1/investigations", json=body())

    assert r.status_code == 429
    assert r.json()["error"]["code"] == "CONCURRENCY_LIMIT"


async def test_list_paginates_and_filters(api: httpx.AsyncClient) -> None:
    titles = []
    for i in range(3):
        created = await create(api, title=f"paged {uuid.uuid4().hex[:6]} #{i}")
        titles.append(created["investigation"]["title"])
        await api.post(f"/api/v1/runs/{created['run']['id']}/cancel")

    seen: list[str] = []
    cursor = None
    while True:
        params: dict[str, Any] = {"limit": 2, "q": "paged"}
        if cursor:
            params["cursor"] = cursor
        page = (await api.get("/api/v1/investigations", params=params)).json()
        seen += [i["title"] for i in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert set(titles) <= set(seen)
    assert len(seen) == len(set(seen))
    cancelled = (await api.get("/api/v1/investigations", params={"status": "cancelled"})).json()
    assert all(i["latest_run"]["status"] == "cancelled" for i in cancelled["items"])


async def test_detail_run_and_cross_user_404(
    api: httpx.AsyncClient, other_user: httpx.AsyncClient
) -> None:
    created = await create(api)
    inv_id, run_id = created["investigation"]["id"], created["run"]["id"]

    detail = (await api.get(f"/api/v1/investigations/{inv_id}")).json()
    assert [r["id"] for r in detail["runs"]] == [run_id]
    assert (await api.get(f"/api/v1/runs/{run_id}")).json()["status"] == "queued"

    for path in (
        f"/api/v1/investigations/{inv_id}",
        f"/api/v1/runs/{run_id}",
        f"/api/v1/runs/{run_id}/findings",
        f"/api/v1/runs/{run_id}/plans",
        f"/api/v1/runs/{run_id}/evidence/ev_000000000000",
    ):
        r = await other_user.get(path)
        assert r.status_code == 404, path
        assert r.json()["error"]["code"] == "NOT_FOUND"
    for path in (f"/api/v1/runs/{run_id}/cancel",):
        assert (await other_user.post(path)).status_code == 404
    assert (await other_user.delete(f"/api/v1/investigations/{inv_id}")).status_code == 404


async def test_cancel_is_idempotent_and_follows_the_state_machine(
    api: httpx.AsyncClient, owner: psycopg.Connection
) -> None:
    queued = await create(api)
    r1 = await api.post(f"/api/v1/runs/{queued['run']['id']}/cancel")
    r2 = await api.post(f"/api/v1/runs/{queued['run']['id']}/cancel")
    assert (r1.status_code, r2.status_code) == (202, 202)
    assert r2.json()["status"] == "cancelled"

    running = await create(api)
    owner.execute(
        "UPDATE investigation_runs SET status = 'running' WHERE id = %s", (running["run"]["id"],)
    )
    r = await api.post(f"/api/v1/runs/{running['run']['id']}/cancel")
    assert r.json()["status"] == "cancelling"
    assert r.json()["cancel_requested_at"] is not None


async def test_delete_and_restore(api: httpx.AsyncClient) -> None:
    created = await create(api)
    inv_id = created["investigation"]["id"]

    busy = await api.delete(f"/api/v1/investigations/{inv_id}")
    assert busy.status_code == 409  # cancel the active run first
    await api.post(f"/api/v1/runs/{created['run']['id']}/cancel")
    assert (await api.delete(f"/api/v1/investigations/{inv_id}")).status_code == 204
    assert (await api.get(f"/api/v1/investigations/{inv_id}")).status_code == 404
    restored = await api.post(f"/api/v1/investigations/{inv_id}/restore")
    assert restored.status_code == 200
    assert (await api.get(f"/api/v1/investigations/{inv_id}")).status_code == 200


async def test_findings_evidence_and_plans_for_a_run(
    api: httpx.AsyncClient, owner: psycopg.Connection
) -> None:
    plan_sha = await upload_plan(api)
    created = await create(api, plan_artifact_sha256=plan_sha)
    run_id = created["run"]["id"]
    owner.execute(
        "INSERT INTO evidence (id, run_id, kind, artifact_id, locator, summary, data, provenance) "
        "SELECT 'ev_aaaaaaaaaaaa', %s, 'plan_node', id, '/0/Plan', 'Seq Scan on orders', "
        "'{\"node_id\": 3}', 'imported' FROM artifacts WHERE sha256 = %s",
        (run_id, plan_sha),
    )
    owner.execute(
        "INSERT INTO findings (run_id, key, agent, title, detail, severity, evidence_ids) "
        "VALUES (%s, 'fd_aaaaaaaaaaaa', 'query_analyzer', 'Scan', 'Seq Scan dominates', 'high', "
        "ARRAY['ev_aaaaaaaaaaaa'])",
        (run_id,),
    )
    owner.execute(
        "INSERT INTO hypotheses (run_id, key, rank, statement, category, supporting_evidence, "
        "confidence, uncertainty_notes, verification_method, proposed_by) VALUES (%s, "
        "'hy_aaaaaaaaaaaa', 1, 'Missing index', 'missing_index', ARRAY['ev_aaaaaaaaaaaa'], "
        "'high', '', 'benchmark', ARRAY['query_analyzer'])",
        (run_id,),
    )

    findings = (await api.get(f"/api/v1/runs/{run_id}/findings")).json()
    assert findings["findings"][0]["key"] == "fd_aaaaaaaaaaaa"
    assert findings["hypotheses"][0]["category"] == "missing_index"

    evidence = (await api.get(f"/api/v1/runs/{run_id}/evidence/ev_aaaaaaaaaaaa")).json()
    assert evidence["evidence"]["locator"] == "/0/Plan"
    assert evidence["artifact"]["sha256"] == plan_sha
    assert evidence["cited_by_findings"] == ["fd_aaaaaaaaaaaa"]
    assert evidence["cited_by_hypotheses"] == ["hy_aaaaaaaaaaaa"]
    assert (await api.get(f"/api/v1/runs/{run_id}/evidence/ev_bbbbbbbbbbbb")).status_code == 404

    plans = (await api.get(f"/api/v1/runs/{run_id}/plans")).json()
    assert [p["role"] for p in plans["items"]] == ["input.plan"]
    assert plans["items"][0]["plan"]["root"]["node_type"] == "Limit"
    assert len(plans["items"][0]["metrics"]) == 4

    content = await api.get(f"/api/v1/artifacts/{plan_sha}")
    assert content.status_code == 200
    assert json.loads(content.content)[0]["Plan"]["Node Type"] == "Limit"


async def test_artifacts_are_only_readable_through_an_owned_run(
    api: httpx.AsyncClient, other_user: httpx.AsyncClient
) -> None:
    plan_sha = await upload_plan(api)
    await create(api, plan_artifact_sha256=plan_sha)

    assert (await other_user.get(f"/api/v1/artifacts/{plan_sha}")).status_code == 404


async def test_models_endpoint_reports_configuration_without_keys(api: httpx.AsyncClient) -> None:
    r = await api.get("/api/v1/settings/models")

    assert r.status_code == 200
    assert r.json()["provider"] == "openrouter"
    assert r.json()["model"].endswith(":free")
    assert r.json()["configured"] is False
    assert "key" not in json.dumps(r.json()).lower().replace("configured", "")
