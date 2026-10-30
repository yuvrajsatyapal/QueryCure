"""Experiment replay end to end (T4.7): real API, real worker handler, real sandbox PG 17.

A Mode C investigation (scripted LLM, pre-authorized demo sandbox) is run and finalized; its
experiment is then replayed through `POST /experiments/{id}/replay` and the `experiment_replay`
job handler. No LLM is reachable during the replay. The replay measures anew (new experiment,
new samples, same seed), the comparison is recorded, the replay run gets its own manifest, and
the source run's seal is unchanged.
"""

import asyncio
import base64
import json
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx2 as httpx
import psycopg
import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.agents.run import RunServices, execute_run
from querycure.agents.runtime import LlmClients
from querycure.api.main import create_app
from querycure.benchmark.engine import EngineOptions
from querycure.core.config import Settings
from querycure.db.engine import make_engine
from querycure.db.repositories.investigations import RunInputs
from querycure.domain.runs import RunKind
from querycure.replay import experiment_replay
from querycure.replay.experiment_replay import check_preconditions, execute_experiment_replay
from querycure.replay.outcome import BASIS_CODES, classify_replay_outcome
from querycure.replay.report_replay import verify_report
from querycure.replay.source_snapshot import (
    MARKER_KEY,
    RECOMMENDATION_KEYS,
    ROLE_MANIFEST,
    ROLE_REPORT_JSON,
    SourceSnapshotError,
    load_source_snapshot,
)
from querycure.sandbox.provisioner import SandboxProvisioner
from tests.fake_llm import RoleClient
from tests.integration import virtual_clock as vc
from tests.integration.sandbox_fixtures import SANDBOX_URL, clone_names
from tests.integration.test_optimization_graph import INDEX, NOTHING_MORE, candidates, scripts
from tests.rehearsal import activation

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
    api: httpx.AsyncClient,
    engine: AsyncEngine,
    migrated_db: str,
    sandbox: SandboxProvisioner,
    options: EngineOptions | None = None,
    oe: list[Any] | None = None,
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
    client = RoleClient(scripts(oe or [candidates(INDEX), NOTHING_MORE]))

    def clients(inputs: RunInputs) -> LlmClients:
        return LlmClients(primary=client)

    services = RunServices(
        engine=engine,
        settings=SETTINGS,
        checkpoint_url=migrated_db,
        clients=clients,
        checkpoint_role="qc_app",
        sandbox=sandbox,
        engine_options=options,
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


# --- Source snapshot (REPLAY_OUTCOME_AUDIT §12.4, §13) ------------------------------------

SNAPSHOT_ROLES = (ROLE_MANIFEST, ROLE_REPORT_JSON)


def sealed_shas(owner: psycopg.Connection, run_id: str) -> tuple[str, str]:
    row = owner.execute(
        "SELECT m.manifest_sha256, r.report_json_sha256 FROM replay_manifests m "
        "JOIN investigation_reports r ON r.run_id = m.run_id WHERE m.run_id = %s",
        (run_id,),
    ).fetchone()
    assert row is not None
    return row[0], row[1]


def snapshot_links(owner: psycopg.Connection, run_id: str) -> dict[str, str]:
    return {
        r[0]: r[1]
        for r in owner.execute(
            "SELECT ra.role, a.sha256 FROM run_artifacts ra JOIN artifacts a "
            "ON a.id = ra.artifact_id WHERE ra.run_id = %s AND ra.role = ANY(%s)",
            (run_id, list(SNAPSHOT_ROLES)),
        )
    }


def counts(owner: psycopg.Connection, run_id: str, experiment_id: str) -> tuple[Any, ...]:
    return tuple(
        owner.execute(sql, params).fetchone()
        for sql, params in (
            (
                "SELECT count(*) FROM investigation_runs WHERE investigation_id = "
                "(SELECT investigation_id FROM investigation_runs WHERE id = %s)",
                (run_id,),
            ),
            (
                "SELECT count(*) FROM replay_attempts WHERE source_experiment_id = %s",
                (experiment_id,),
            ),
            ("SELECT count(*) FROM jobs WHERE kind = 'experiment_replay'", ()),
            (
                "SELECT count(*) FROM run_artifacts WHERE role = ANY(%s)",
                (list(SNAPSHOT_ROLES),),
            ),
        )
    )


def user_of(owner: psycopg.Connection, run_id: str) -> uuid.UUID:
    row = owner.execute(
        "SELECT i.user_id FROM investigations i JOIN investigation_runs r "
        "ON r.investigation_id = i.id WHERE r.id = %s",
        (run_id,),
    ).fetchone()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def test_replay_links_the_verified_source_snapshot_and_seals_it(
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    manifest_sha, report_sha = sealed_shas(owner, run_id)
    source_report = (await api.get(f"/api/v1/runs/{run_id}/report")).json()["report"]
    source_outcome = owner.execute(
        "SELECT outcome FROM investigation_reports WHERE run_id = %s", (run_id,)
    ).fetchone()
    result_sha = owner.execute(
        "SELECT a.sha256 FROM experiments e JOIN artifacts a ON a.id = e.result_artifact_id "
        "WHERE e.id = %s",
        (experiment_id,),
    ).fetchone()
    assert source_outcome is not None
    assert result_sha is not None
    async with app_engine.connect() as conn:
        assert await load_source_snapshot(conn, uuid.UUID(run_id)) is None  # not a replay
    no_llm(monkeypatch)

    started = await api.post(
        f"/api/v1/experiments/{experiment_id}/replay", json={"confirm_ddl": True}
    )
    assert started.status_code == 202, started.text
    replay_run = started.json()["replay_run_id"]
    # The source's own sealed manifest and report are linked, not copied.
    assert snapshot_links(owner, replay_run) == {
        ROLE_MANIFEST: manifest_sha,
        ROLE_REPORT_JSON: report_sha,
    }
    async with app_engine.connect() as conn:
        captured = await load_source_snapshot(conn, uuid.UUID(replay_run))
    assert captured is not None
    assert captured.source_run_id == run_id
    assert captured.source_run_kind is RunKind.INITIAL
    assert captured.source_experiment_id == experiment_id
    assert captured.source_experiment_result_sha256 == result_sha[0]
    assert captured.source_manifest_sha256 == manifest_sha
    assert captured.source_report_json_sha256 == report_sha
    assert captured.source_builder_version == "report-builder@1"
    assert captured.source_final_status == "completed"
    assert captured.source_outcome == source_outcome[0]
    assert captured.source_recommendation is not None
    assert captured.source_recommendation.model_dump() == {
        k: source_report["recommendation"][k] for k in RECOMMENDATION_KEYS
    }

    await execute_experiment_replay(
        app_engine, uuid.UUID(replay_run), sandbox=provisioner, options=EngineOptions(),
        reclaimed=False,
    )  # fmt: skip
    replay_manifest = owner.execute(
        "SELECT convert_from(a.content, 'UTF8')::jsonb FROM replay_manifests m "
        "JOIN artifacts a ON a.id = m.manifest_artifact_id WHERE m.run_id = %s",
        (replay_run,),
    ).fetchone()
    assert replay_manifest is not None
    sealed = {(a["role"], a["digest"]) for a in replay_manifest[0]["artifacts"]}
    assert (ROLE_MANIFEST, f"sha256:{manifest_sha}") in sealed
    assert (ROLE_REPORT_JSON, f"sha256:{report_sha}") in sealed
    # Deterministic reconstruction from the replay's sealed records.
    async with app_engine.connect() as conn:
        again = await load_source_snapshot(conn, uuid.UUID(replay_run))
        verified = await verify_report(conn, uuid.UUID(replay_run))
    assert again == captured
    assert verified.status == "verified", verified.result_json()
    # Historical compatibility: still report-builder@1, which never reads the snapshot.
    replay_report = (await api.get(f"/api/v1/runs/{replay_run}/report")).json()["report"]
    assert replay_report["builder_version"] == "report-builder@1"
    assert replay_report["schema_version"] == 1
    assert "replay_source" not in replay_report
    # Not activated: the sealed outcome still follows the legacy rule (the replay's winner).
    stored = owner.execute(
        "SELECT r.outcome, convert_from(a.content, 'UTF8')::jsonb -> 'winner' FROM "
        "investigation_runs r JOIN experiments e ON e.run_id = r.id JOIN artifacts a "
        "ON a.id = e.result_artifact_id WHERE r.id = %s",
        (replay_run,),
    ).fetchone()
    assert stored is not None
    assert stored[0] == ("verified_recommendation" if stored[1] else "inconclusive")
    # The pure classifier gives a contract-valid answer on these real records.
    attempt = (await api.get(f"/api/v1/replay-attempts/{started.json()['id']}")).json()
    decided = classify_replay_outcome(again, attempt["result"])
    assert decided.basis in BASIS_CODES
    assert sealed_shas(owner, run_id) == (manifest_sha, report_sha)


async def test_snapshot_survives_later_source_changes_and_deletion(
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
) -> None:
    run_id, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    started = await api.post(
        f"/api/v1/experiments/{experiment_id}/replay", json={"confirm_ddl": True}
    )
    replay_run = uuid.UUID(started.json()["replay_run_id"])
    async with app_engine.connect() as conn:
        captured = await load_source_snapshot(conn, replay_run)
    assert captured is not None

    owner_engine = make_engine(migrated_db)
    try:
        async with owner_engine.connect() as conn:
            trans = await conn.begin()
            for sql in (
                "UPDATE investigation_runs SET outcome = 'inconclusive', deleted_at = now() "
                "WHERE id = :id",
                "DELETE FROM investigation_reports WHERE run_id = :id",
                "DELETE FROM replay_manifests WHERE run_id = :id",
                "DELETE FROM run_artifacts WHERE run_id = :id",
                "DELETE FROM experiments WHERE run_id = :id",
                "DELETE FROM investigation_runs WHERE id = :id",
            ):
                await conn.execute(text(sql), {"id": run_id})
            assert await load_source_snapshot(conn, replay_run) == captured
            await trans.rollback()
    finally:
        await owner_engine.dispose()


async def test_missing_source_run_is_source_integrity_failed(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    """D6a: an experiment whose run row is gone (integrity bug) is refused, not a crash."""
    experiment_id = uuid.uuid4()
    owner.execute(
        "INSERT INTO experiments (id, run_id, round, kind, approval_request_id, "
        "config_artifact_id, engine_version, row_profile, seed, status) VALUES "
        "(%s, uuid_generate_v4(), 0, 'single', uuid_generate_v4(), uuid_generate_v4(), "
        "'bench@2', 'qc-row-v1', 1, 'completed')",
        (experiment_id,),
    )
    async with app_engine.connect() as conn:
        pre = await check_preconditions(conn, SETTINGS, experiment_id)
    assert (pre.code, pre.detail) == ("source_integrity_failed", "source run missing")
    assert pre.snapshot is None


async def test_source_failing_integrity_gets_no_snapshot(
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    migrated_db: str,
    provisioner: SandboxProvisioner,
) -> None:
    run_id, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    owner_engine = make_engine(migrated_db)
    try:
        async with owner_engine.connect() as conn:
            trans = await conn.begin()
            await conn.execute(
                text(
                    "UPDATE artifacts SET content = content || ' '::bytea WHERE id = "
                    "(SELECT report_json_artifact_id FROM investigation_reports WHERE run_id = :r)"
                ),
                {"r": run_id},
            )
            pre = await check_preconditions(conn, SETTINGS, uuid.UUID(experiment_id))
            await trans.rollback()
    finally:
        await owner_engine.dispose()
    assert pre.code == "source_integrity_failed"
    assert pre.snapshot is None


async def test_inconsistent_source_records_are_not_replayable_and_create_no_run(
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing recommendation evidence or a candidate/experiment hash mismatch in the source's
    sealed records (SourceSnapshotError) maps to the existing `source_integrity_failed`."""
    run_id, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    before = counts(owner, run_id, experiment_id)

    async def inconsistent(*a: Any, **k: Any) -> Any:
        raise SourceSnapshotError("source recommendation evidence is missing")

    monkeypatch.setattr("querycure.replay.experiment_replay.capture_source_snapshot", inconsistent)
    r = await api.post(f"/api/v1/experiments/{experiment_id}/replay", json={"confirm_ddl": True})
    assert r.status_code == 422, r.text
    detail = r.json()["error"]["details"][0]
    assert detail["code"] == "source_integrity_failed"
    assert detail["detail"] == "source recommendation evidence is missing"
    attempt = owner.execute(
        "SELECT status, replay_run_id FROM replay_attempts WHERE id = %s",
        (detail["replay_attempt_id"],),
    ).fetchone()
    assert attempt == ("not_replayable", None)
    after = counts(owner, run_id, experiment_id)
    assert after[0] == before[0]  # no run
    assert after[2:] == before[2:]  # no job, no snapshot link


@pytest.mark.parametrize("fault", ["link_source_snapshot", "insert_attempt"])
async def test_a_fault_during_start_rolls_back_the_run_and_its_snapshot(
    fault: str,
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    before = counts(owner, run_id, experiment_id)
    original = getattr(experiment_replay, fault)

    async def boom(*a: Any, **k: Any) -> Any:
        if fault == "insert_attempt" and k.get("status") == "not_replayable":
            return await original(*a, **k)
        raise RuntimeError(f"injected fault in {fault}")

    monkeypatch.setattr(experiment_replay, fault, boom)
    with pytest.raises(RuntimeError, match="injected fault"):
        async with app_engine.begin() as conn:
            await experiment_replay.start_replay(
                conn,
                settings=SETTINGS,
                user_id=user_of(owner, run_id),
                experiment_id=uuid.UUID(experiment_id),
            )
    assert counts(owner, run_id, experiment_id) == before


# --- Snapshot integrity and legacy compatibility (checkpoint 2026-10-30) -----------------


async def start_and_seal(
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    provisioner: SandboxProvisioner,
    experiment_id: str,
    *,
    seal: bool,
    options: EngineOptions | None = None,
) -> uuid.UUID:
    started = await api.post(
        f"/api/v1/experiments/{experiment_id}/replay", json={"confirm_ddl": True}
    )
    assert started.status_code == 202, started.text
    replay_run = uuid.UUID(started.json()["replay_run_id"])
    if seal:
        await execute_experiment_replay(
            app_engine,
            replay_run,
            sandbox=provisioner,
            options=options or EngineOptions(),
            reclaimed=False,
        )
    return replay_run


async def load_as_owner(migrated_db: str, replay_run: uuid.UUID, *sql: str) -> Any:
    """`load_source_snapshot` after owner-only tampering, inside a rolled-back transaction.
    Returns the snapshot or the exception it raised."""
    owner_engine = make_engine(migrated_db)
    try:
        async with owner_engine.connect() as conn:
            trans = await conn.begin()
            try:
                for statement in sql:
                    await conn.execute(text(statement), {"r": replay_run})
                return await load_source_snapshot(conn, replay_run)
            except SourceSnapshotError as exc:
                return exc
            finally:
                await trans.rollback()
    finally:
        await owner_engine.dispose()


def drop_link(role: str) -> str:
    return f"DELETE FROM run_artifacts WHERE run_id = :r AND role = '{role}'"


def corrupt(role: str) -> str:
    return (
        "UPDATE artifacts SET content = content || ' '::bytea WHERE id = "
        f"(SELECT artifact_id FROM run_artifacts WHERE run_id = :r AND role = '{role}')"
    )


async def test_historical_replay_without_snapshot_keeps_its_v1_contract(
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A replay started by the pre-snapshot code (no links) stays readable: its sealed manifest
    lists no snapshot role, so it is legacy (None), and its v1 report still verifies."""
    run_id, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    no_llm(monkeypatch)

    async def old_start(*a: Any, **k: Any) -> None:
        return None

    monkeypatch.setattr(experiment_replay, "link_source_snapshot", old_start)
    without_marker(monkeypatch)
    replay_run = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=True)
    assert snapshot_links(owner, str(replay_run)) == {}
    async with app_engine.connect() as conn:
        assert await load_source_snapshot(conn, replay_run) is None
        verified = await verify_report(conn, replay_run)
    assert verified.status == "verified", verified.result_json()
    report = (await api.get(f"/api/v1/runs/{replay_run}/report")).json()["report"]
    assert (report["builder_version"], report["schema_version"]) == ("report-builder@1", 1)
    # A link appearing after the seal (only possible outside the app role) is not legacy.
    tampered = await load_as_owner(
        migrated_db,
        replay_run,
        "INSERT INTO run_artifacts (run_id, artifact_id, role) SELECT :r, manifest_artifact_id, "
        f"'{ROLE_MANIFEST}' FROM replay_manifests WHERE run_id = '{run_id}'",
        "INSERT INTO run_artifacts (run_id, artifact_id, role) SELECT :r, "
        f"report_json_artifact_id, '{ROLE_REPORT_JSON}' FROM investigation_reports "
        f"WHERE run_id = '{run_id}'",
    )
    assert isinstance(tampered, SourceSnapshotError)


@pytest.mark.parametrize(
    "dropped",
    [(ROLE_MANIFEST,), (ROLE_REPORT_JSON,), (ROLE_MANIFEST, ROLE_REPORT_JSON)],
    ids=["manifest", "report", "both"],
)
async def test_sealed_new_replay_with_missing_snapshot_links_fails_closed(
    dropped: tuple[str, ...],
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    migrated_db: str,
    provisioner: SandboxProvisioner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The replay's own sealed manifest is the discriminator: it lists the snapshot roles, so
    a replay that lost its links is corrupted, never legacy, even when both links are gone."""
    _, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    no_llm(monkeypatch)
    replay_run = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=True)
    async with app_engine.connect() as conn:
        assert await load_source_snapshot(conn, replay_run) is not None
    result = await load_as_owner(migrated_db, replay_run, *(drop_link(r) for r in dropped))
    assert isinstance(result, SourceSnapshotError)


async def test_unsealed_new_replay_with_one_missing_link_fails_closed(
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    migrated_db: str,
    provisioner: SandboxProvisioner,
) -> None:
    _, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    replay_run = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=False)
    for role in (ROLE_MANIFEST, ROLE_REPORT_JSON):
        result = await load_as_owner(migrated_db, replay_run, drop_link(role))
        assert isinstance(result, SourceSnapshotError)


@pytest.mark.parametrize("role", [ROLE_MANIFEST, ROLE_REPORT_JSON])
async def test_corrupted_snapshot_artifact_fails_closed(
    role: str,
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    migrated_db: str,
    provisioner: SandboxProvisioner,
) -> None:
    _, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    replay_run = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=False)
    result = await load_as_owner(migrated_db, replay_run, corrupt(role))
    assert isinstance(result, SourceSnapshotError)


async def test_snapshot_artifact_of_the_wrong_kind_fails_closed(
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    migrated_db: str,
    provisioner: SandboxProvisioner,
) -> None:
    """A digest-valid JSON artifact of another kind under a snapshot role is rejected."""
    _, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    replay_run = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=False)
    for role in (ROLE_MANIFEST, ROLE_REPORT_JSON):
        result = await load_as_owner(
            migrated_db,
            replay_run,
            "UPDATE run_artifacts SET artifact_id = (SELECT artifact_id FROM run_artifacts "
            "WHERE run_id = :r AND role = 'input.experiment_config') "
            f"WHERE run_id = :r AND role = '{role}'",
        )
        assert isinstance(result, SourceSnapshotError)


@pytest.mark.parametrize("seal", [True, False], ids=["sealed", "unsealed"])
async def test_replay_reconstructs_without_its_source_run(
    seal: bool,
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    migrated_db: str,
    provisioner: SandboxProvisioner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    no_llm(monkeypatch)
    replay_run = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=seal)
    async with app_engine.connect() as conn:
        captured = await load_source_snapshot(conn, replay_run)
    assert captured is not None
    after = await load_as_owner(
        migrated_db,
        replay_run,
        *(
            sql.replace(":id", f"'{run_id}'")
            for sql in (
                "DELETE FROM investigation_reports WHERE run_id = :id",
                "DELETE FROM replay_manifests WHERE run_id = :id",
                "DELETE FROM run_artifacts WHERE run_id = :id",
                "DELETE FROM experiments WHERE run_id = :id",
                "DELETE FROM investigation_runs WHERE id = :id",
            )
        ),
    )
    assert after == captured


async def test_two_replays_share_the_source_artifacts_without_copying(
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    no_llm(monkeypatch)
    artifacts_before = owner.execute("SELECT count(*) FROM artifacts").fetchone()
    first = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=True)
    second = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=False)
    assert snapshot_links(owner, str(first)) == snapshot_links(owner, str(second))
    assert set(snapshot_links(owner, str(first)).values()) == set(sealed_shas(owner, run_id))
    async with app_engine.connect() as conn:
        a = await load_source_snapshot(conn, first)
        b = await load_source_snapshot(conn, second)
    assert a is not None
    assert a == b
    # Content-addressed: one row per digest, however many runs link it.
    for sha in sealed_shas(owner, run_id):
        assert owner.execute(
            "SELECT count(*) FROM artifacts WHERE sha256 = %s", (sha,)
        ).fetchone() == (1,)
    assert artifacts_before is not None


# --- Creation-time snapshot marker (Workstream 5, Phase 1) -------------------------------

CREATION = "run_id = :r AND type = 'replay.status_changed' AND payload->'from' = 'null'::jsonb"


def creation_events(owner: psycopg.Connection, run_id: str) -> list[dict[str, Any]]:
    return [
        r[0]
        for r in owner.execute(
            "SELECT payload FROM investigation_events WHERE run_id = %s "
            "AND type = 'replay.status_changed' AND payload->'from' = 'null'::jsonb ORDER BY seq",
            (run_id,),
        )
    ]


def without_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate the pre-marker start code: the creation event carries no marker."""
    original = experiment_replay.emit

    async def emit(conn: Any, run_id: Any, type: Any, payload: dict[str, Any]) -> int:
        return await original(
            conn, run_id, type, {k: v for k, v in payload.items() if k != MARKER_KEY}
        )

    monkeypatch.setattr(experiment_replay, "emit", emit)


def set_marker(value: str) -> str:
    return (
        f"UPDATE investigation_events SET payload = jsonb_set(payload, '{{{MARKER_KEY}}}', "
        f"'{value}'::jsonb) WHERE {CREATION}"
    )


DROP_MARKER = f"UPDATE investigation_events SET payload = payload - '{MARKER_KEY}' WHERE {CREATION}"


@pytest.mark.parametrize("seal", [True, False], ids=["sealed", "unsealed"])
async def test_new_replay_records_a_creation_marker_naming_its_snapshot(
    seal: bool,
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    no_llm(monkeypatch)
    replay_run = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=seal)
    events = creation_events(owner, str(replay_run))
    links = snapshot_links(owner, str(replay_run))
    assert len(events) == 1
    assert events[0][MARKER_KEY] == {
        "schema_version": 1,
        "manifest": f"sha256:{links[ROLE_MANIFEST]}",
        "report_json": f"sha256:{links[ROLE_REPORT_JSON]}",
    }
    assert set(links.values()) == set(sealed_shas(owner, run_id))
    # The marker is written before execution, in the event with seq 2 of the replay run.
    seq = owner.execute(
        "SELECT seq FROM investigation_events WHERE run_id = %s AND payload ? %s",
        (str(replay_run), MARKER_KEY),
    ).fetchone()
    assert seq == (2,)
    async with app_engine.connect() as conn:
        snapshot = await load_source_snapshot(conn, replay_run)
        assert snapshot is not None
        if seal:
            assert (await verify_report(conn, replay_run)).status == "verified"


@pytest.mark.parametrize(
    "dropped",
    [(ROLE_MANIFEST,), (ROLE_REPORT_JSON,), (ROLE_MANIFEST, ROLE_REPORT_JSON)],
    ids=["manifest", "report", "both"],
)
async def test_unsealed_marked_replay_with_missing_links_fails_closed(
    dropped: tuple[str, ...],
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    migrated_db: str,
    provisioner: SandboxProvisioner,
) -> None:
    """The residual case of §15.2: an unsealed replay that lost both links is no longer
    indistinguishable from a historical one. Its creation marker says a snapshot is required."""
    _, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    replay_run = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=False)
    result = await load_as_owner(migrated_db, replay_run, *(drop_link(r) for r in dropped))
    assert isinstance(result, SourceSnapshotError)
    assert "marker" in result.detail or "incomplete" in result.detail


@pytest.mark.parametrize("seal", [True, False], ids=["sealed", "unsealed"])
@pytest.mark.parametrize(
    "tamper",
    [
        set_marker('"yes"'),
        set_marker("null"),
        set_marker('{"schema_version": 2}'),
        set_marker(
            '{"schema_version": 1, "manifest": "sha256:' + "0" * 64 + '", "report_json": '
            '"sha256:' + "0" * 64 + '"}'
        ),
    ],
    ids=["string", "null", "schema", "other-digests"],
)
async def test_malformed_or_mismatched_marker_fails_closed(
    tamper: str,
    seal: bool,
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    migrated_db: str,
    provisioner: SandboxProvisioner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    no_llm(monkeypatch)
    replay_run = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=seal)
    result = await load_as_owner(migrated_db, replay_run, tamper)
    assert isinstance(result, SourceSnapshotError)


@pytest.mark.parametrize("seal", [True, False], ids=["sealed", "unsealed"])
async def test_snapshot_links_without_a_marker_fail_closed(
    seal: bool,
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    migrated_db: str,
    provisioner: SandboxProvisioner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    no_llm(monkeypatch)
    replay_run = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=seal)
    result = await load_as_owner(migrated_db, replay_run, DROP_MARKER)
    assert isinstance(result, SourceSnapshotError)
    # Losing marker and links together cannot pass for legacy once sealed: the sealed
    # manifest still lists the snapshot roles.
    if seal:
        both = await load_as_owner(
            migrated_db, replay_run, DROP_MARKER, *(drop_link(r) for r in SNAPSHOT_ROLES)
        )
        assert isinstance(both, SourceSnapshotError)


async def test_a_second_creation_event_fails_closed(
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    migrated_db: str,
    provisioner: SandboxProvisioner,
) -> None:
    _, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    replay_run = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=False)
    result = await load_as_owner(
        migrated_db,
        replay_run,
        "INSERT INTO investigation_events (run_id, seq, type, payload) SELECT run_id, 1000, "
        "type, payload - 'source_snapshot' FROM investigation_events WHERE " + CREATION,
    )
    assert isinstance(result, SourceSnapshotError)


async def test_historical_unsealed_replay_without_marker_or_links_is_legacy(
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)

    async def old_start(*a: Any, **k: Any) -> None:
        return None

    monkeypatch.setattr(experiment_replay, "link_source_snapshot", old_start)
    without_marker(monkeypatch)
    replay_run = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=False)
    assert MARKER_KEY not in creation_events(owner, str(replay_run))[0]
    async with app_engine.connect() as conn:
        assert await load_source_snapshot(conn, replay_run) is None


async def test_a_fault_after_the_marker_rolls_back_the_whole_start(
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    before = counts(owner, run_id, experiment_id)
    marked_before = owner.execute(
        "SELECT count(*) FROM investigation_events WHERE payload ? %s", (MARKER_KEY,)
    ).fetchone()

    async def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("injected fault in enqueue")

    monkeypatch.setattr(experiment_replay.queue, "enqueue", boom)
    with pytest.raises(RuntimeError, match="injected fault"):
        async with app_engine.begin() as conn:
            await experiment_replay.start_replay(
                conn,
                settings=SETTINGS,
                user_id=user_of(owner, run_id),
                experiment_id=uuid.UUID(experiment_id),
            )
    assert counts(owner, run_id, experiment_id) == before
    assert (
        owner.execute(
            "SELECT count(*) FROM investigation_events WHERE payload ? %s", (MARKER_KEY,)
        ).fetchone()
        == marked_before
    )


async def test_concurrent_starts_each_get_a_marker_and_their_own_links(
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
) -> None:
    run_id, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    user = user_of(owner, run_id)

    async def start() -> Any:
        async with app_engine.begin() as conn:
            return await experiment_replay.start_replay(
                conn, settings=SETTINGS, user_id=user, experiment_id=uuid.UUID(experiment_id)
            )

    results = await asyncio.gather(start(), start(), return_exceptions=True)
    started = [r for r in results if not isinstance(r, BaseException)]
    assert started, results
    replays = [
        str(r[0])
        for r in owner.execute(
            "SELECT id FROM investigation_runs WHERE kind = 'experiment_replay' "
            "AND parent_run_id = %s",
            (run_id,),
        )
    ]
    # Every replay that exists has exactly one creation marker that names its own links; a
    # start that lost a race left nothing behind.
    assert sorted(replays) == sorted(str(a.replay_run_id) for a in started)
    for replay in replays:
        events = creation_events(owner, replay)
        links = snapshot_links(owner, replay)
        assert len(events) == 1
        assert events[0][MARKER_KEY]["manifest"] == f"sha256:{links[ROLE_MANIFEST]}"
        async with app_engine.connect() as conn:
            assert await load_source_snapshot(conn, uuid.UUID(replay)) is not None


# --- report-builder@2 on real sealed replays (Workstream 5, Phases 2to5) -------------------
# Activation is simulated inside these tests only: v2 is made current and finalize_run is
# wrapped so the replay's conclusion comes from the classifier. `_close` is unchanged.


def simulate_activation(monkeypatch: pytest.MonkeyPatch, *, status: str | None = None) -> None:
    """The shared test-only activation seam (`tests/rehearsal/activation.py`); `status` also
    fixes the comparison verdict at its boundary, for rules a real comparison cannot reach."""
    real_compare = experiment_replay.compare_experiments

    def compare(**kw: Any) -> dict[str, Any]:
        result = real_compare(**kw)
        if status is None:
            return result
        pairs = [{**p, "status": status, "code": None} for p in result["pairs"]]
        return {**result, "status": status, "failure_code": None, "pairs": pairs,
                "comparison_mode": "same_environment"}  # fmt: skip

    activation.activate(monkeypatch.setattr)
    monkeypatch.setattr(experiment_replay, "compare_experiments", compare)


def stored_report(owner: psycopg.Connection, run_id: str) -> tuple[dict[str, Any], str, Any]:
    row = owner.execute(
        "SELECT j.content, m.content, r.outcome FROM investigation_reports ir "
        "JOIN artifacts j ON j.id = ir.report_json_artifact_id "
        "JOIN artifacts m ON m.id = ir.report_md_artifact_id "
        "JOIN investigation_runs r ON r.id = ir.run_id WHERE ir.run_id = %s",
        (run_id,),
    ).fetchone()
    assert row is not None
    return json.loads(bytes(row[0])), bytes(row[1]).decode(), row[2]


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("reproduced", ("verified_recommendation", "original_reproduced")),
        ("reproduced_with_drift", ("inconclusive", "performance_drift")),
        ("not_reproduced", ("inconclusive", "not_reproduced")),
        ("inconclusive", ("inconclusive", "inconclusive")),
    ],
)
async def test_v2_replay_report_is_consistent_and_rebuilds_byte_identically(
    status: str,
    expected: tuple[str, str],
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The virtual clock (virtual_clock.py) fixes the samples: the source is always a clean
    # verified seal, so host noise can never turn this row into another rule.
    clock = vc.install(monkeypatch, vc.CLEAN, seed=7)
    run_id, experiment_id = await finalized_sandbox_run(
        api, app_engine, migrated_db, provisioner, clock.options()
    )
    source_report, _, source_outcome = stored_report(owner, run_id)
    assert (source_outcome, source_report["recommendation"]["status"]) == (
        "verified_recommendation",
        "verified",
    ), source_report["headline"]
    no_llm(monkeypatch)
    simulate_activation(monkeypatch, status=status)
    clock.use(vc.CLEAN, seed=8)
    replay_run = await start_and_seal(
        api, app_engine, provisioner, experiment_id, seal=True, options=clock.options()
    )

    report, md, outcome = stored_report(owner, str(replay_run))
    rr = report["replay_result"]
    assert (report["schema_version"], report["builder_version"]) == (2, "report-builder@2")
    assert (outcome, rr["result"]) == expected, rr["basis"]
    # One sealed decision: run row, manifest, report, basis and recommendation agree.
    assert report["outcome"] == outcome
    assert rr["basis"]["comparison_status"] == status
    verified = outcome == "verified_recommendation"
    assert (report["recommendation"]["origin"] == "source_run") is verified
    assert rr["claims_reproduction"] is verified
    if verified:
        rec = source_report["recommendation"]
        assert report["recommendation"]["candidate_key"] == rec["candidate_key"]
        assert report["recommendation"]["source_run_id"] == run_id
        assert report["recommendation"]["primary_measurement"] == rec["primary_measurement"]
    else:
        assert report["recommendation"]["status"] == "none"
    assert rr["source"]["run_id"] == run_id
    assert "## Experiment Replay Result" in md
    assert "Verified recommendation" not in md
    api_report = (await api.get(f"/api/v1/runs/{replay_run}/report")).json()
    assert api_report["report"] == report
    async with app_engine.connect() as conn:
        result = await verify_report(conn, replay_run)
        source = await verify_report(conn, uuid.UUID(run_id))
    assert result.status == "verified", result.result_json()
    assert {c.name: c.status for c in result.checks}["rebuild_json"] == "ok"
    assert {c.name: c.status for c in result.checks}["rebuild_markdown"] == "ok"
    assert source.status == "verified"


async def test_v2_replay_report_verifies_after_its_source_run_is_deleted(
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    migrated_db: str,
    provisioner: SandboxProvisioner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    no_llm(monkeypatch)
    simulate_activation(monkeypatch, status="reproduced")
    replay_run = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=True)
    owner_engine = make_engine(migrated_db)
    try:
        async with owner_engine.connect() as conn:
            trans = await conn.begin()
            for sql in (
                "DELETE FROM investigation_reports WHERE run_id = :id",
                "DELETE FROM replay_manifests WHERE run_id = :id",
                "DELETE FROM run_artifacts WHERE run_id = :id",
                "DELETE FROM investigation_events WHERE run_id = :id",
                "DELETE FROM experiments WHERE run_id = :id",
                "DELETE FROM investigation_runs WHERE id = :id",
            ):
                await conn.execute(text(sql), {"id": run_id})
            result = await verify_report(conn, replay_run)
            await trans.rollback()
    finally:
        await owner_engine.dispose()
    assert result.status == "verified", [c for c in result.checks if c.status != "ok"]
    assert result.checks[-1].name == "rebuild_markdown"


@pytest.mark.parametrize("role", [ROLE_MANIFEST, ROLE_REPORT_JSON])
async def test_v2_report_with_a_snapshot_link_removed_after_sealing_fails_closed(
    role: str,
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    migrated_db: str,
    provisioner: SandboxProvisioner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rebuild then cannot load the snapshot, and the v2 builder refuses the sealed basis:
    report replay reports a rebuild mismatch instead of raising or verifying."""
    _, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    no_llm(monkeypatch)
    simulate_activation(monkeypatch, status="reproduced")
    replay_run = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=True)
    owner_engine = make_engine(migrated_db)
    try:
        async with owner_engine.connect() as conn:
            trans = await conn.begin()
            await conn.execute(text(drop_link(role)), {"r": replay_run})
            result = await verify_report(conn, replay_run)
            await trans.rollback()
    finally:
        await owner_engine.dispose()
    assert result.status == "integrity_failed", result.result_json()
    assert result.failure_code == "rebuild_mismatch"


async def test_v2_finalization_refuses_a_legacy_winner_outcome(
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Why v2 must not become current before `_close` is corrected: the legacy winner-based
    outcome with no basis is a contradiction, so sealing fails closed instead of producing a
    verified replay report. The attempt is not left half-sealed."""
    from querycure.reports import registry
    from querycure.reports.builders.v2 import ReportContractError

    _, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    no_llm(monkeypatch)
    monkeypatch.setattr(registry, "CURRENT_BUILDER", "report-builder@2")
    monkeypatch.setattr(registry, "CURRENT_RENDERER", "report-md@2")
    real_run = experiment_replay.run_experiment

    def with_winner(config: Any, *a: Any, **k: Any) -> Any:
        # the legacy `_close` seals verified_recommendation whenever the replay has a winner
        return real_run(config, *a, **k).model_copy(update={"winner": config.candidates[0].arm})

    monkeypatch.setattr(experiment_replay, "run_experiment", with_winner)
    started = await api.post(
        f"/api/v1/experiments/{experiment_id}/replay", json={"confirm_ddl": True}
    )
    replay_run = uuid.UUID(started.json()["replay_run_id"])
    with pytest.raises(ReportContractError):
        await execute_experiment_replay(
            app_engine,
            replay_run,
            sandbox=provisioner,
            options=EngineOptions(),
            reclaimed=False,
        )
    row = owner.execute(
        "SELECT finalized_at, (SELECT count(*) FROM investigation_reports WHERE run_id = %s) "
        "FROM investigation_runs WHERE id = %s",
        (str(replay_run), str(replay_run)),
    ).fetchone()
    assert row == (None, 0)
