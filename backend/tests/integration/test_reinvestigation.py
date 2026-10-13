"""AI re-investigation start contract (REPLAY_ENGINE §1, API_DESIGN `reinvestigate`).

A new `reinvestigation` run on the same inputs, with its own budget and provenance and a link
to the run it re-investigates; it needs explicit consent and free-model capacity, and it is
never started implicitly by a replay. The conclusion diff stays Post-MVP.
"""

import base64
import hashlib
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx2 as httpx
import psycopg
import pytest
from pydantic import SecretStr

from querycure.agents.run import RunServices, execute_run
from querycure.agents.runtime import LlmClients
from querycure.api.main import create_app
from querycure.core.config import Settings
from querycure.db.engine import make_engine
from querycure.db.repositories.investigations import RunInputs
from querycure.llm.stub import StubClient
from tests.integration.test_investigations_api import body

pytestmark = pytest.mark.integration
KEY = base64.b64encode(os.urandom(32)).decode()
STUB = Settings(_env_file=None, master_key=KEY, llm_provider="stub")
NO_KEY = Settings(
    _env_file=None, master_key=KEY, llm_provider="openrouter", openrouter_api_key=None
)
SPENT = Settings(
    _env_file=None,
    master_key=KEY,
    llm_provider="openrouter",
    openrouter_api_key=SecretStr("test-key-not-used"),
    llm_daily_request_limit=1,
)


async def client(migrated_db: str, settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    engine = make_engine(migrated_db, set_role="qc_app")
    app = create_app(settings, engine=engine)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.post("/api/v1/session")
        c.headers["X-CSRF-Token"] = c.cookies["qc_csrf"]
        yield c
    await engine.dispose()


@pytest.fixture
async def api(migrated_db: str) -> AsyncIterator[httpx.AsyncClient]:
    async for c in client(migrated_db, STUB):
        yield c


@pytest.fixture(autouse=True)
def _no_active_runs(owner: psycopg.Connection) -> None:
    owner.execute(
        "UPDATE investigation_runs SET status = 'cancelled', finalized_at = now() "
        "WHERE status IN ('queued', 'running', 'awaiting_approval', 'cancelling')"
    )


async def finished_investigation(api: httpx.AsyncClient) -> tuple[str, str]:
    created = (await api.post("/api/v1/investigations", json=body())).json()
    run_id = created["run"]["id"]
    assert (await api.post(f"/api/v1/runs/{run_id}/cancel")).status_code == 202
    return created["investigation"]["id"], run_id


CONSENT = {"confirm_new_llm_run": True}


async def test_reinvestigation_is_a_new_linked_run_with_its_own_budget(
    api: httpx.AsyncClient, owner: psycopg.Connection
) -> None:
    inv_id, parent = await finished_investigation(api)

    r = await api.post(f"/api/v1/investigations/{inv_id}/reinvestigate", json=CONSENT)

    assert r.status_code == 202, r.text
    run = r.json()["run"]
    assert run["id"] != parent
    row = owner.execute(
        "SELECT kind, parent_run_id, run_number, status, usage FROM investigation_runs "
        "WHERE id = %s",
        (run["id"],),
    ).fetchone()
    assert row is not None
    assert (row[0], str(row[1]), row[2], row[3], row[4]) == (
        "reinvestigation",
        parent,
        2,
        "queued",
        {},
    )
    roles = sorted(
        (r[0], r[1])
        for r in owner.execute(
            "SELECT role, artifact_id FROM run_artifacts WHERE run_id = %s", (run["id"],)
        )
    )
    parent_roles = sorted(
        (r[0], r[1])
        for r in owner.execute(
            "SELECT role, artifact_id FROM run_artifacts WHERE run_id = %s "
            "AND role LIKE 'input.%%'",
            (parent,),
        )
    )
    assert roles == parent_roles  # same inputs, by reference
    job = owner.execute("SELECT kind, status FROM jobs WHERE run_id = %s", (run["id"],)).fetchone()
    assert job == ("run_start", "pending")
    latest = owner.execute(
        "SELECT latest_run_id FROM investigations WHERE id = %s", (inv_id,)
    ).fetchone()
    assert latest is not None
    assert str(latest[0]) == run["id"]


async def test_consent_is_required(api: httpx.AsyncClient) -> None:
    inv_id, _ = await finished_investigation(api)

    for payload in ({}, {"confirm_new_llm_run": False}):
        r = await api.post(f"/api/v1/investigations/{inv_id}/reinvestigate", json=payload)
        assert r.status_code == 422


async def test_an_active_run_blocks_reinvestigation(api: httpx.AsyncClient) -> None:
    created = (await api.post("/api/v1/investigations", json=body())).json()

    r = await api.post(
        f"/api/v1/investigations/{created['investigation']['id']}/reinvestigate", json=CONSENT
    )

    assert r.status_code == 409
    assert r.json()["error"]["code"] == "INVALID_STATE"


async def test_idempotency_key_returns_the_same_run(api: httpx.AsyncClient) -> None:
    inv_id, _ = await finished_investigation(api)
    key = {"Idempotency-Key": str(uuid.uuid4())}

    first = await api.post(
        f"/api/v1/investigations/{inv_id}/reinvestigate", json=CONSENT, headers=key
    )
    again = await api.post(
        f"/api/v1/investigations/{inv_id}/reinvestigate", json=CONSENT, headers=key
    )

    assert first.status_code == again.status_code == 202
    assert first.json()["run"]["id"] == again.json()["run"]["id"]


async def test_missing_model_configuration_starts_nothing(
    api: httpx.AsyncClient, migrated_db: str, owner: psycopg.Connection
) -> None:
    inv_id, _ = await finished_investigation(api)
    before = owner.execute("SELECT count(*) FROM investigation_runs").fetchone()

    async for other in client(migrated_db, NO_KEY):
        other.cookies.set("qc_session", api.cookies["qc_session"])
        r = await other.post(f"/api/v1/investigations/{inv_id}/reinvestigate", json=CONSENT)
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "CONFIGURATION_ERROR"
    assert owner.execute("SELECT count(*) FROM investigation_runs").fetchone() == before


async def test_exhausted_free_quota_starts_nothing(
    api: httpx.AsyncClient, migrated_db: str, owner: psycopg.Connection
) -> None:
    inv_id, run_id = await finished_investigation(api)
    owner.execute(
        "INSERT INTO agent_executions (run_id, agent, node, invocation_key, attempt, "
        "prompt_version, model, requested_model, status) VALUES (%s, 'query_analyzer', 'x', "
        "'k', 1, 'p', 'm:free', 'm:free', 'succeeded')",
        (run_id,),
    )

    async for other in client(migrated_db, SPENT):
        other.cookies.set("qc_session", api.cookies["qc_session"])
        r = await other.post(f"/api/v1/investigations/{inv_id}/reinvestigate", json=CONSENT)
        assert r.status_code == 429
        assert r.json()["error"]["code"] == "LLM_QUOTA_EXHAUSTED"


async def test_other_users_get_404(
    api: httpx.AsyncClient, migrated_db: str, owner: psycopg.Connection
) -> None:
    inv_id, _ = await finished_investigation(api)
    user = owner.execute("INSERT INTO users (kind) VALUES ('anonymous') RETURNING id").fetchone()
    assert user is not None
    token = uuid.uuid4().hex
    owner.execute(
        "INSERT INTO sessions (user_id, token_hash, expires_at) "
        "VALUES (%s, %s, now() + interval '1 hour')",
        (user[0], hashlib.sha256(token.encode()).hexdigest()),
    )
    async for other in client(migrated_db, STUB):
        other.cookies.set("qc_session", token)
        r = await other.post(f"/api/v1/investigations/{inv_id}/reinvestigate", json=CONSENT)
        assert r.status_code == 404


async def test_reinvestigation_runs_to_a_sealed_report_with_its_own_provenance(
    api: httpx.AsyncClient, migrated_db: str, app_engine: Any, owner: psycopg.Connection
) -> None:
    inv_id, parent = await finished_investigation(api)
    run_id = (
        await api.post(f"/api/v1/investigations/{inv_id}/reinvestigate", json=CONSENT)
    ).json()["run"]["id"]
    model = StubClient()  # offline, canned, labelled stub in every record

    def clients(inputs: RunInputs) -> LlmClients:
        return LlmClients(primary=model)

    services = RunServices(
        engine=app_engine,
        settings=STUB,
        checkpoint_url=migrated_db,
        clients=clients,
        checkpoint_role="qc_app",
    )
    await execute_run(services, uuid.UUID(run_id), attempt=1, reclaimed=False)

    report = (await api.get(f"/api/v1/runs/{run_id}/report")).json()
    assert report["final_status"] == "completed"
    assert report["report"]["run"]["kind"] == "reinvestigation"
    assert report["report"]["run"]["parent_run_id"] == parent
    assert report["report"]["provenance"]["llm"], "the new run made its own model calls"
    parent_report = (await api.get(f"/api/v1/runs/{parent}/report")).json()
    assert parent_report["report"]["provenance"]["llm"] == []  # the original is untouched
    verified = (await api.post(f"/api/v1/runs/{run_id}/replay/report")).json()
    assert verified["status"] == "verified"
