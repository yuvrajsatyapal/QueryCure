"""Experiment replay end to end (T4.7): real API, real worker handler, real sandbox PG 17.

A Mode C investigation (scripted LLM, pre-authorized demo sandbox) is run and finalized; its
experiment is then replayed through `POST /experiments/{id}/replay` and the `experiment_replay`
job handler. No LLM is reachable during the replay. The replay measures anew (new experiment,
new samples, same seed), the comparison is recorded, the replay run gets its own manifest, and
the source run's seal is unchanged.
"""

import base64
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx2 as httpx
import psycopg
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.agents.run import RunServices, execute_run
from querycure.agents.runtime import LlmClients
from querycure.api.main import create_app
from querycure.benchmark.engine import EngineOptions
from querycure.core.config import Settings
from querycure.db.engine import make_engine
from querycure.db.repositories.investigations import RunInputs
from querycure.replay.experiment_replay import execute_experiment_replay
from querycure.sandbox.provisioner import SandboxProvisioner
from tests.fake_llm import RoleClient
from tests.integration.sandbox_fixtures import SANDBOX_URL, clone_names
from tests.integration.test_optimization_graph import INDEX, NOTHING_MORE, candidates, scripts

pytestmark = pytest.mark.integration

SETTINGS = Settings(
    _env_file=None,
    master_key=base64.b64encode(os.urandom(32)).decode(),
    sandbox_admin_url=SecretStr(SANDBOX_URL),
    sandbox_bench_password=SecretStr("unused-by-the-api"),
)
RECENT = "SELECT * FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 20"
REPLAY_STATUSES = {"reproduced", "reproduced_with_drift", "not_reproduced", "inconclusive"}


@pytest.fixture
async def api(migrated_db: str) -> AsyncIterator[httpx.AsyncClient]:
    engine = make_engine(migrated_db, set_role="qc_app")
    app = create_app(SETTINGS, engine=engine)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        await client.post("/api/v1/session")
        client.headers["X-CSRF-Token"] = client.cookies["qc_csrf"]
        yield client
    await engine.dispose()


@pytest.fixture(autouse=True)
def _no_active_runs(owner: psycopg.Connection) -> None:
    owner.execute(
        "UPDATE investigation_runs SET status = 'cancelled', finalized_at = now() "
        "WHERE status IN ('queued', 'running', 'awaiting_approval', 'cancelling')"
    )


def no_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*a: Any, **k: Any) -> Any:
        raise AssertionError("an LLM was used during experiment replay")

    monkeypatch.setattr("querycure.llm.providers.build_client", refuse)
    monkeypatch.setattr("querycure.llm.openrouter.OpenRouterClient.complete_json", refuse)
    monkeypatch.setattr("tests.fake_llm.ScriptedClient.complete_json", refuse)


async def finalized_sandbox_run(
    api: httpx.AsyncClient, engine: AsyncEngine, migrated_db: str, sandbox: SandboxProvisioner
) -> tuple[str, str]:
    created = await api.post(
        "/api/v1/investigations",
        json={
            "title": "Orders page",
            "objective": "Make the orders page fast",
            "modes": ["sandbox_benchmark"],
            "workload_id": "orders_ecommerce@v1:sf=0.1:seed=42",
            "query": RECENT,
            "pre_authorize_demo_sandbox": True,
        },
    )
    assert created.status_code == 202, created.text
    run_id = created.json()["run"]["id"]
    client = RoleClient(scripts([candidates(INDEX), NOTHING_MORE]))

    def clients(inputs: RunInputs) -> LlmClients:
        return LlmClients(primary=client)

    services = RunServices(
        engine=engine,
        settings=SETTINGS,
        checkpoint_url=migrated_db,
        clients=clients,
        checkpoint_role="qc_app",
        sandbox=sandbox,
    )
    await execute_run(services, uuid.UUID(run_id), attempt=1, reclaimed=False)
    experiments = (await api.get(f"/api/v1/runs/{run_id}/experiments")).json()["items"]
    primary = next(e for e in experiments if e["replicate"] == 0)
    return run_id, primary["id"]


async def test_experiment_replay_measures_anew_and_compares(
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    source_report = (await api.get(f"/api/v1/runs/{run_id}/report")).json()
    audits = (await api.get(f"/api/v1/runs/{run_id}/verifications")).json()["items"]
    assert audits, "the auditor's verdicts are listed"
    assert {c["name"] for c in audits[0]["checks"]} >= {"rescore", "approval", "plan_change"}
    source_samples = owner.execute(
        "SELECT count(*) FROM benchmark_runs WHERE experiment_id = %s", (experiment_id,)
    ).fetchone()
    no_llm(monkeypatch)

    started = await api.post(
        f"/api/v1/experiments/{experiment_id}/replay", json={"confirm_ddl": True}
    )
    assert started.status_code == 202, started.text
    attempt = started.json()
    assert attempt["status"] == "queued"
    replay_run = attempt["replay_run_id"]
    approval = owner.execute(
        "SELECT status, decided_by, payload->'candidates'->0->>'sql_sha256' "
        "FROM approval_requests WHERE run_id = %s",
        (replay_run,),
    ).fetchone()
    assert approval is not None
    assert approval[0] == "approved"
    assert approval[1].startswith("user:")

    await execute_experiment_replay(
        app_engine,
        uuid.UUID(replay_run),
        sandbox=provisioner,
        options=EngineOptions(),
        reclaimed=False,
    )

    done = (await api.get(f"/api/v1/replay-attempts/{attempt['id']}")).json()
    assert done["status"] in REPLAY_STATUSES, done
    result = done["result"]
    assert result["comparison_mode"] == "same_environment"
    assert result["pairs"], result
    assert result["original_experiment_id"] == experiment_id
    assert result["config"]["margin"] == 1.25
    # New measurements: a new experiment, new append-only rows, the same seed.
    replay_exp = done["replay_experiment_id"]
    assert replay_exp != experiment_id
    row = owner.execute(
        "SELECT replay_of_experiment_id, seed, engine_version, status FROM experiments "
        "WHERE id = %s",
        (replay_exp,),
    ).fetchone()
    source_seed = owner.execute(
        "SELECT seed FROM experiments WHERE id = %s", (experiment_id,)
    ).fetchone()
    assert row is not None
    assert source_seed is not None
    assert str(row[0]) == experiment_id
    assert row[1] == source_seed[0]
    assert row[2] == "bench@2"
    assert row[3] == "completed"
    replay_samples = owner.execute(
        "SELECT count(*) FROM benchmark_runs WHERE experiment_id = %s", (replay_exp,)
    ).fetchone()
    assert replay_samples is not None
    assert replay_samples[0] > 0
    # The source experiment and its seal are untouched.
    assert (
        owner.execute(
            "SELECT count(*) FROM benchmark_runs WHERE experiment_id = %s", (experiment_id,)
        ).fetchone()
        == source_samples
    )
    assert (await api.get(f"/api/v1/runs/{run_id}/report")).json()["manifest_sha256"] == (
        source_report["manifest_sha256"]
    )
    verify_source = (await api.post(f"/api/v1/runs/{run_id}/replay/report")).json()
    assert verify_source["status"] == "verified"
    # The replay run is finalized with its own report and manifest, and verifies.
    replay_report = (await api.get(f"/api/v1/runs/{replay_run}/report")).json()
    assert replay_report["report"]["run"]["kind"] == "experiment_replay"
    assert replay_report["report"]["replay"]["comparison"]["status"] == done["status"]
    verify_replay = (await api.post(f"/api/v1/runs/{replay_run}/replay/report")).json()
    assert verify_replay["status"] == "verified", verify_replay
    llm = replay_report["report"]["provenance"]["llm"]
    assert llm == []  # zero LLM calls in the replay run
    events = [
        r[0]
        for r in owner.execute(
            "SELECT type FROM investigation_events WHERE run_id = %s ORDER BY seq", (replay_run,)
        )
    ]
    assert "replay.compared" in events
    assert "replay.status_changed" in events
    assert clone_names() == []
    listed = (await api.get(f"/api/v1/runs/{run_id}/replay/attempts")).json()["items"]
    assert {a["id"] for a in listed} >= {attempt["id"]}


async def test_unfinalized_source_is_not_replayable_and_creates_no_run(
    api: httpx.AsyncClient, owner: psycopg.Connection
) -> None:
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
    run_id = created.json()["run"]["id"]
    experiment_id = uuid.uuid4()
    owner.execute(
        "INSERT INTO experiments (id, run_id, round, kind, approval_request_id, "
        "config_artifact_id, engine_version, row_profile, seed, status) VALUES "
        "(%s, %s, 0, 'single', uuid_generate_v4(), uuid_generate_v4(), 'bench@2', "
        "'qc-row-v1', 1, 'completed')",
        (experiment_id, run_id),
    )
    runs_before = owner.execute("SELECT count(*) FROM investigation_runs").fetchone()

    r = await api.post(f"/api/v1/experiments/{experiment_id}/replay", json={"confirm_ddl": True})

    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "EXPERIMENT_NOT_REPLAYABLE"
    assert err["details"][0]["code"] == "source_not_finalized"
    attempt = await api.get(f"/api/v1/replay-attempts/{err['details'][0]['replay_attempt_id']}")
    assert attempt.json()["status"] == "not_replayable"
    assert owner.execute("SELECT count(*) FROM investigation_runs").fetchone() == runs_before


async def test_confirmation_is_required(api: httpx.AsyncClient) -> None:
    r = await api.post(f"/api/v1/experiments/{uuid.uuid4()}/replay", json={"confirm_ddl": False})
    assert r.status_code == 422


async def test_other_users_cannot_replay_or_see_experiments(
    api: httpx.AsyncClient, owner: psycopg.Connection, migrated_db: str
) -> None:
    experiment_id = uuid.uuid4()
    other_run = owner.execute(
        "INSERT INTO investigations (user_id, title, objective, modes) VALUES "
        "(uuid_generate_v4(), 't', 'o', ARRAY['sandbox_benchmark']) RETURNING id"
    ).fetchone()
    assert other_run is not None
    run = owner.execute(
        "INSERT INTO investigation_runs (investigation_id, run_number, kind, status, budget, "
        "usage) VALUES (%s, 1, 'initial', 'completed', '{}', '{}') RETURNING id",
        (other_run[0],),
    ).fetchone()
    assert run is not None
    owner.execute(
        "INSERT INTO experiments (id, run_id, round, kind, approval_request_id, "
        "config_artifact_id, engine_version, row_profile, seed) VALUES "
        "(%s, %s, 0, 'single', uuid_generate_v4(), uuid_generate_v4(), 'bench@2', "
        "'qc-row-v1', 1)",
        (experiment_id, run[0]),
    )

    r = await api.post(f"/api/v1/experiments/{experiment_id}/replay", json={"confirm_ddl": True})

    assert r.status_code == 404


async def test_queued_replay_can_be_cancelled(
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
) -> None:
    _, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    attempt = (
        await api.post(f"/api/v1/experiments/{experiment_id}/replay", json={"confirm_ddl": True})
    ).json()

    cancelled = await api.post(f"/api/v1/replay-attempts/{attempt['id']}/cancel")

    assert cancelled.status_code == 202
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["failure_code"] == "cancelled_by_user"
    run = owner.execute(
        "SELECT status, finalized_at IS NOT NULL FROM investigation_runs WHERE id = %s",
        (attempt["replay_run_id"],),
    ).fetchone()
    assert run == ("cancelled", True)
    # A later job claim is a no-op: nothing is measured.
    await execute_experiment_replay(
        app_engine,
        uuid.UUID(attempt["replay_run_id"]),
        sandbox=provisioner,
        options=EngineOptions(),
        reclaimed=False,
    )
    assert owner.execute(
        "SELECT count(*) FROM experiments WHERE run_id = %s", (attempt["replay_run_id"],)
    ).fetchone() == (0,)


async def test_reclaimed_replay_job_resumes_and_completes(
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
) -> None:
    """A worker died after claiming the job: the run is `running`, the attempt `running`. The
    reclaimed job records the hand-over and finishes the same (deterministic) experiment."""
    _, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    attempt = (
        await api.post(f"/api/v1/experiments/{experiment_id}/replay", json={"confirm_ddl": True})
    ).json()
    replay_run = attempt["replay_run_id"]
    owner.execute("UPDATE investigation_runs SET status = 'running' WHERE id = %s", (replay_run,))
    owner.execute("UPDATE replay_attempts SET status = 'running' WHERE id = %s", (attempt["id"],))

    await execute_experiment_replay(
        app_engine,
        uuid.UUID(replay_run),
        sandbox=provisioner,
        options=EngineOptions(),
        reclaimed=True,
    )

    done = (await api.get(f"/api/v1/replay-attempts/{attempt['id']}")).json()
    assert done["status"] in REPLAY_STATUSES
    statuses = [
        r[0]
        for r in owner.execute(
            "SELECT payload->>'to' FROM investigation_events WHERE run_id = %s "
            "AND type = 'run.status_changed' ORDER BY seq",
            (replay_run,),
        )
    ]
    assert statuses == ["queued", "queued", "running", "completed"]
    assert owner.execute(
        "SELECT count(*) FROM experiments WHERE run_id = %s", (replay_run,)
    ).fetchone() == (1,)


async def test_dead_lettered_replay_fails_its_attempt_and_seals_the_run(
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
) -> None:
    from querycure.jobs.handlers import dead_job_handler
    from querycure.jobs.queue import Job

    _, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    attempt = (
        await api.post(f"/api/v1/experiments/{experiment_id}/replay", json={"confirm_ddl": True})
    ).json()
    replay_run = uuid.UUID(attempt["replay_run_id"])
    services = RunServices(
        engine=app_engine,
        settings=SETTINGS,
        checkpoint_url=migrated_db,
        clients=lambda inputs: LlmClients(primary=RoleClient({})),
    )
    job_row = owner.execute(
        "SELECT id, kind, run_id, payload, attempts, max_attempts FROM jobs WHERE run_id = %s",
        (replay_run,),
    ).fetchone()
    assert job_row is not None

    await dead_job_handler(services)(
        Job(
            id=job_row[0],
            kind=job_row[1],
            run_id=job_row[2],
            payload=job_row[3],
            attempts=job_row[4],
            max_attempts=job_row[5],
            reclaimed=False,
        )
    )

    done = (await api.get(f"/api/v1/replay-attempts/{attempt['id']}")).json()
    assert (done["status"], done["failure_code"]) == ("failed", "internal_error")
    assert owner.execute(
        "SELECT status, finalized_at IS NOT NULL FROM investigation_runs WHERE id = %s",
        (replay_run,),
    ).fetchone() == ("failed", True)
