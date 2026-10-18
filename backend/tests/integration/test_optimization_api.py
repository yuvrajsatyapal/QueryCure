"""Candidates, approvals and experiments API (T3.10/T3.12) as qc_app, through the real app."""

import asyncio
import hashlib
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx2 as httpx
import psycopg
import pytest

from querycure.core.config import Settings
from tests.integration import test_investigations_api as base
from tests.integration.test_investigations_api import SETTINGS, body

pytestmark = pytest.mark.integration

RECENT = "SELECT * FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 20"
SANDBOX = {
    "modes": ["sandbox_benchmark"],
    "workload_id": "orders_ecommerce@v1:sf=0.1:seed=42",
    "query": RECENT,
}


@pytest.fixture
async def api(migrated_db: str) -> AsyncIterator[httpx.AsyncClient]:
    async for c in base.client_for(migrated_db):
        yield c


@pytest.fixture
async def other_user(
    migrated_db: str, owner: psycopg.Connection
) -> AsyncIterator[httpx.AsyncClient]:
    """A second, distinct user (same setup as the investigations API tests)."""
    user_id = owner.execute("INSERT INTO users (kind) VALUES ('anonymous') RETURNING id").fetchone()
    assert user_id is not None
    token = uuid.uuid4().hex
    owner.execute(
        "INSERT INTO sessions (user_id, token_hash, expires_at) "
        "VALUES (%s, %s, now() + interval '1 hour')",
        (user_id[0], hashlib.sha256(token.encode()).hexdigest()),
    )
    async for c in base.client_for(migrated_db):
        c.cookies.set("qc_session", token)
        yield c


@pytest.fixture(autouse=True)
def _no_active_runs(owner: psycopg.Connection) -> None:
    """The session database is shared; earlier tests' runs would hit the concurrency limit."""
    owner.execute(
        "UPDATE investigation_runs SET status = 'cancelled' "
        "WHERE status IN ('queued', 'running', 'awaiting_approval', 'cancelling')"
    )


async def _create(api: httpx.AsyncClient, **overrides: Any) -> dict[str, Any]:
    r = await api.post("/api/v1/investigations", json=body(**{**SANDBOX, **overrides}))
    assert r.status_code == 202, r.text
    return r.json()  # type: ignore[no-any-return]


def _pending_approval(owner: psycopg.Connection, run_id: str, n_candidates: int = 2) -> str:
    """Seed what approval_gate writes: candidates, a pending approval, awaiting_approval."""
    ids = []
    for i in range(n_candidates):
        row = owner.execute(
            "INSERT INTO optimization_candidates (run_id, key, round, kind, addresses_hypotheses, "
            "ddl, sql_sha256, expected_benefit, estimated_cost, proposed_by) VALUES "
            "(%s, %s, 0, 'create_index', '{hy_000000000001}', %s, 'x', 'b', '{}', "
            "'optimization_engineer') RETURNING id",
            (run_id, f"oc_00000000000{i}", [f"CREATE INDEX ON orders (c{i})"]),
        ).fetchone()
        assert row is not None
        ids.append(str(row[0]))
    user = owner.execute(
        "SELECT i.user_id FROM investigation_runs r JOIN investigations i "
        "ON i.id = r.investigation_id WHERE r.id = %s",
        (run_id,),
    ).fetchone()
    assert user is not None
    payload = {
        "schema_version": 1,
        "workload_id": SANDBOX["workload_id"],
        "sandbox": "sandbox",
        "baseline_query": RECENT,
        "param_sets": [{"name": "hot", "values": [1024], "edge_case": False}],
        "candidates": [
            {
                "candidate_id": cid,
                "key": f"oc_00000000000{i}",
                "kind": "create_index",
                "ddl": [f"CREATE INDEX ON orders (c{i})"],
                "query_sql": None,
                "sql_sha256": "x",
                "expected_benefit": "b",
                "risks": [],
            }
            for i, cid in enumerate(ids)
        ],
    }
    approval = owner.execute(
        "INSERT INTO approval_requests (run_id, user_id, round, kind, payload, expires_at) "
        "VALUES (%s, %s, 0, 'sandbox_execution', %s, now() + interval '1 day') RETURNING id",
        (run_id, user[0], json.dumps(payload)),
    ).fetchone()
    assert approval is not None
    owner.execute(
        "UPDATE investigation_runs SET status = 'awaiting_approval', started_at = now() "
        "WHERE id = %s",
        (run_id,),
    )
    return str(approval[0])


async def test_sandbox_investigation_is_accepted_with_workload_and_preauthorization(
    api: httpx.AsyncClient, owner: psycopg.Connection
) -> None:
    created = await _create(api, pre_authorize_demo_sandbox=True)

    row = owner.execute(
        "SELECT modes, workload_id, pre_authorize_sandbox FROM investigations WHERE id = %s",
        (created["investigation"]["id"],),
    ).fetchone()
    assert row == (["sandbox_benchmark"], SANDBOX["workload_id"], True)


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"workload_id": None}, "workload_id"),
        ({"param_sets": [{"name": "x", "values": [1, 2]}]}, "param_sets"),
        ({"param_sets": [{"name": f"p{i}", "values": [i]} for i in range(6)]}, "param_sets"),
        ({"query": "SELECT * FROM orders WHERE id = $1", "param_sets": []}, "param_sets"),
    ],
)
async def test_sandbox_creation_validation(
    api: httpx.AsyncClient, overrides: dict[str, Any], field: str
) -> None:
    r = await api.post("/api/v1/investigations", json=body(**{**SANDBOX, **overrides}))

    assert r.status_code == 422, r.text
    assert r.json()["error"]["details"][0]["field"] == field


def test_sandbox_disabled_deployment_refuses() -> None:
    from querycure.api.routers.investigations import _check_sandbox
    from querycure.api.schemas.investigations import CreateInvestigationRequest
    from querycure.core.errors import FeatureDisabledError

    disabled = Settings(_env_file=None, feature_sandbox=False, master_key=SETTINGS.master_key)
    request = CreateInvestigationRequest.model_validate(body(**SANDBOX))

    with pytest.raises(FeatureDisabledError):
        _check_sandbox(request, disabled)


async def test_approval_flow_partial_decision_resumes_the_run(
    api: httpx.AsyncClient, owner: psycopg.Connection
) -> None:
    run_id = (await _create(api))["run"]["id"]
    approval_id = _pending_approval(owner, run_id)

    listed = (await api.get(f"/api/v1/runs/{run_id}/approvals")).json()["items"]
    assert [a["status"] for a in listed] == ["pending"]
    offered = [c["candidate_id"] for c in listed[0]["payload"]["candidates"]]
    assert listed[0]["payload"]["candidates"][0]["ddl"] == ["CREATE INDEX ON orders (c0)"]

    r = await api.post(
        f"/api/v1/approvals/{approval_id}/decision",
        json={"decision": "partial", "candidate_ids": [offered[1]], "comment": "only the 2nd"},
    )

    assert r.status_code == 202, r.text
    assert r.json()["status"] == "partially_approved"
    assert r.json()["approved_candidate_ids"] == [offered[1]]
    run = owner.execute("SELECT status FROM investigation_runs WHERE id = %s", (run_id,)).fetchone()
    assert run == ("queued",)
    job = owner.execute(
        "SELECT kind, dedupe_key FROM jobs WHERE run_id = %s AND kind = 'run_resume'", (run_id,)
    ).fetchone()
    assert job == ("run_resume", f"run_resume:{run_id}:{approval_id}")
    events = [
        r[0]
        for r in owner.execute(
            "SELECT type FROM investigation_events WHERE run_id = %s ORDER BY seq", (run_id,)
        )
    ]
    assert "approval.decided" in events

    again = await api.post(
        f"/api/v1/approvals/{approval_id}/decision", json={"decision": "decline"}
    )
    assert again.status_code == 202
    assert again.json()["status"] == "partially_approved"  # the first decision stands


async def test_concurrent_decisions_record_one_decision_and_one_resume(
    api: httpx.AsyncClient, owner: psycopg.Connection
) -> None:
    """A double click or two tabs: concurrent approve/decline requests serialize on the
    approval row; exactly one decision, one `approval.decided` event and one resume job."""
    run_id = (await _create(api))["run"]["id"]
    approval_id = _pending_approval(owner, run_id)

    url = f"/api/v1/approvals/{approval_id}/decision"
    replies = await asyncio.gather(
        *(api.post(url, json={"decision": d}) for d in ["approve", "decline"] * 4)
    )

    assert all(r.status_code in (202, 409) for r in replies), [r.text for r in replies]
    statuses = {r.json()["status"] for r in replies if r.status_code == 202}
    assert len(statuses) == 1  # every success reports the same, single decision
    counts = owner.execute(
        "SELECT (SELECT count(*) FROM jobs WHERE run_id = %s AND kind = 'run_resume'), "
        "(SELECT count(*) FROM investigation_events WHERE run_id = %s "
        "AND type = 'approval.decided')",
        (run_id, run_id),
    ).fetchone()
    assert counts == (1, 1)


@pytest.mark.parametrize(
    "payload",
    [
        {"decision": "partial", "candidate_ids": []},
        {"decision": "partial", "candidate_ids": [str(uuid.uuid4())]},
        {"decision": "maybe"},
    ],
)
async def test_invalid_decisions_are_refused(
    api: httpx.AsyncClient, owner: psycopg.Connection, payload: dict[str, Any]
) -> None:
    run_id = (await _create(api))["run"]["id"]
    approval_id = _pending_approval(owner, run_id)

    r = await api.post(f"/api/v1/approvals/{approval_id}/decision", json=payload)

    assert r.status_code == 422
    pending = owner.execute(
        "SELECT status FROM approval_requests WHERE id = %s", (approval_id,)
    ).fetchone()
    assert pending == ("pending",)


async def test_expired_approval_cannot_be_decided(
    api: httpx.AsyncClient, owner: psycopg.Connection
) -> None:
    run_id = (await _create(api))["run"]["id"]
    approval_id = _pending_approval(owner, run_id)
    owner.execute(
        "UPDATE approval_requests SET status = 'expired', decided_at = now() WHERE id = %s",
        (approval_id,),
    )

    r = await api.post(f"/api/v1/approvals/{approval_id}/decision", json={"decision": "approve"})

    assert r.status_code == 409
    assert r.json()["error"]["code"] == "INVALID_STATE"


async def test_other_users_get_404_for_runs_approvals_and_experiments(
    api: httpx.AsyncClient, other_user: httpx.AsyncClient, owner: psycopg.Connection
) -> None:
    run_id = (await _create(api))["run"]["id"]
    approval_id = _pending_approval(owner, run_id)

    for path in ("candidates", "approvals", "experiments"):
        assert (await other_user.get(f"/api/v1/runs/{run_id}/{path}")).status_code == 404
    decision = await other_user.post(
        f"/api/v1/approvals/{approval_id}/decision", json={"decision": "approve"}
    )
    assert decision.status_code == 404
    assert (await other_user.get(f"/api/v1/experiments/{uuid.uuid4()}")).status_code == 404
    still = owner.execute(
        "SELECT status FROM approval_requests WHERE id = %s", (approval_id,)
    ).fetchone()
    assert still == ("pending",)


async def test_candidates_and_empty_experiments_are_listed(
    api: httpx.AsyncClient, owner: psycopg.Connection
) -> None:
    run_id = (await _create(api))["run"]["id"]
    _pending_approval(owner, run_id, n_candidates=1)

    candidates = (await api.get(f"/api/v1/runs/{run_id}/candidates")).json()["items"]
    experiments = (await api.get(f"/api/v1/runs/{run_id}/experiments")).json()["items"]

    assert [(c["key"], c["status"]) for c in candidates] == [("oc_000000000000", "proposed")]
    assert experiments == []
