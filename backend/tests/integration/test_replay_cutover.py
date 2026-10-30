"""In-flight replay safety at the activation boundary (REPLAY_OUTCOME_AUDIT §18.4).

Real API, real worker handler, real sandbox PG 17, no LLM. Since the ADR-0032 activation every
test runs the production code: `_close` classifies snapshot-era replays, report-builder@2 is
current, and a replay keeps the contract it was created under (`finalize_run` seals a `legacy`
replay with report-builder@1 / report-md@1 on every path: completed, failed, dead-lettered,
cancelled). The pre-snapshot start code is reproduced by `as_legacy_start`; the pre-activation
build, needed only for skew and rollback, by `tests/rehearsal/pre_activation.py` inside a
named `monkeypatch.context()`.

Cases: a legacy replay queued or running at cutover, a new replay with a valid or a missing
snapshot, a worker restart (reclaimed job), duplicate delivery, API/worker version skew, a
builder version the reader does not know, rollback after a v2 report has been sealed, and the
failed, dead-lettered and cancelled ends of legacy and snapshot replays.
"""

# ruff: noqa: F811 - pytest fixtures are imported by name and used as parameters

import json
import uuid
from typing import Any

import httpx2 as httpx
import psycopg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.benchmark.engine import EngineOptions
from querycure.replay import experiment_replay
from querycure.replay.cutover import in_flight_replays, replay_contract
from querycure.replay.experiment_replay import execute_experiment_replay
from querycure.replay.report_replay import verify_report
from querycure.replay.source_snapshot import ROLE_REPORT_JSON
from querycure.reports import registry
from querycure.sandbox.provisioner import SandboxProvisioner
from tests.integration.test_experiment_replay import (  # noqa: F401 - fixtures
    _no_active_runs,
    api,
    as_legacy_start,
    creation_events,
    drop_link,
    finalized_sandbox_run,
    no_llm,
    start_and_seal,
    stored_report,
    without_marker,
)
from tests.rehearsal import pre_activation

pytestmark = pytest.mark.integration


def sealed(owner: psycopg.Connection, run_id: uuid.UUID) -> dict[str, Any]:
    row = owner.execute(
        "SELECT ir.builder_version, ir.md_renderer_version, ir.report_schema_version, "
        "r.status, r.outcome, (SELECT count(*) FROM investigation_reports WHERE run_id = r.id), "
        "(SELECT payload FROM investigation_events WHERE run_id = r.id AND type = "
        "'run.concluded') FROM investigation_runs r LEFT JOIN investigation_reports ir "
        "ON ir.run_id = r.id WHERE r.id = %s",
        (str(run_id),),
    ).fetchone()
    assert row is not None
    keys = ("builder", "renderer", "schema", "status", "outcome", "reports", "concluded")
    return dict(zip(keys, row, strict=True))


def legacy_outcome(owner: psycopg.Connection, run_id: uuid.UUID) -> str:
    """What the pre-activation `_close` seals: the replay experiment's own winner."""
    row = owner.execute(
        "SELECT a.content FROM experiments e JOIN artifacts a ON a.id = e.result_artifact_id "
        "WHERE e.run_id = %s",
        (str(run_id),),
    ).fetchone()
    assert row is not None
    return "verified_recommendation" if json.loads(bytes(row[0]))["winner"] else "inconclusive"


async def run_replay(
    app_engine: AsyncEngine,
    provisioner: SandboxProvisioner,
    run_id: uuid.UUID,
    *,
    reclaimed: bool = False,
) -> None:
    await execute_experiment_replay(
        app_engine, run_id, sandbox=provisioner, options=EngineOptions(), reclaimed=reclaimed
    )


async def contract_and_in_flight(app_engine: AsyncEngine, run_id: uuid.UUID) -> tuple[str, Any]:
    async with app_engine.connect() as conn:
        contract = await replay_contract(conn, run_id)
        flight = {r.replay_run_id: r for r in await in_flight_replays(conn)}
    return contract, flight.get(run_id)


async def verified(app_engine: AsyncEngine, run_id: uuid.UUID) -> tuple[str, list[str]]:
    async with app_engine.connect() as conn:
        result = await verify_report(conn, run_id)
    return result.status, list(result.warnings)


# --- Legacy replays in flight at cutover ---------------------------------------------------


@pytest.mark.parametrize("state", ["queued", "running"])
async def test_legacy_replay_in_flight_at_cutover_keeps_its_creation_contract(
    state: str,
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Created by the old start code, still queued (or running on a worker that then died)
    when the activated build (this code) takes over: the cutover check reports it, and once it
    finishes it is sealed under report-builder@1 with its legacy outcome, never reclassified."""
    _, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    no_llm(monkeypatch)
    with monkeypatch.context() as old_code:
        as_legacy_start(old_code)
        replay_run = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=False)
    if state == "running":
        owner.execute(
            "UPDATE investigation_runs SET status = 'running' WHERE id = %s", (str(replay_run),)
        )
        owner.execute(
            "UPDATE replay_attempts SET status = 'running' WHERE replay_run_id = %s",
            (str(replay_run),),
        )

    contract, flight = await contract_and_in_flight(app_engine, replay_run)
    assert contract == "legacy"
    assert flight is not None
    assert (flight.contract, flight.attempt_status) == ("legacy", state)

    await run_replay(app_engine, provisioner, replay_run, reclaimed=state == "running")

    row = sealed(owner, replay_run)
    assert (row["builder"], row["renderer"], row["schema"]) == (
        "report-builder@1",
        "report-md@1",
        1,
    )
    assert row["outcome"] == legacy_outcome(owner, replay_run)
    assert "replay_basis" not in row["concluded"]
    report, _, _ = stored_report(owner, str(replay_run))
    assert "replay_result" not in report
    assert await verified(app_engine, replay_run) == ("verified", [])
    _, flight = await contract_and_in_flight(app_engine, replay_run)
    assert flight is None


# --- New replays (created with a snapshot) --------------------------------------------------


async def test_new_replay_with_a_valid_snapshot_is_classified_after_activation(
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    no_llm(monkeypatch)
    replay_run = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=False)
    contract, flight = await contract_and_in_flight(app_engine, replay_run)
    assert (contract, flight.contract if flight else None) == ("snapshot", "snapshot")

    await run_replay(app_engine, provisioner, replay_run)

    row = sealed(owner, replay_run)
    assert (row["builder"], row["renderer"], row["schema"]) == (
        "report-builder@2",
        "report-md@2",
        2,
    )
    basis = row["concluded"]["replay_basis"]
    assert basis["code"] != "source_snapshot_missing"
    assert (row["outcome"] == "verified_recommendation") == (
        basis["code"] == "reproduced_source_recommendation"
    )
    assert await verified(app_engine, replay_run) == ("verified", [])


async def test_new_replay_that_lost_a_snapshot_link_fails_closed_never_legacy(
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    no_llm(monkeypatch)
    replay_run = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=False)
    assert creation_events(owner, str(replay_run))[0].get("source_snapshot")
    owner.execute(drop_link(ROLE_REPORT_JSON).replace(":r", "%(r)s"), {"r": str(replay_run)})
    contract, _ = await contract_and_in_flight(app_engine, replay_run)
    assert contract == "snapshot"

    await run_replay(app_engine, provisioner, replay_run)

    row = sealed(owner, replay_run)
    assert row["builder"] == "report-builder@2"
    assert (row["outcome"], row["concluded"]["replay_basis"]["code"]) == (
        "inconclusive",
        "source_snapshot_missing",
    )


# --- Delivery, restarts, skew and rollback ---------------------------------------------------


async def test_restart_and_duplicate_delivery_seal_once(
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A worker dies mid-replay (job reclaimed), then the job is delivered twice more: one
    experiment, one report, one manifest, unchanged bytes."""
    _, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    no_llm(monkeypatch)
    replay_run = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=False)
    owner.execute(
        "UPDATE investigation_runs SET status = 'running' WHERE id = %s", (str(replay_run),)
    )
    owner.execute(
        "UPDATE replay_attempts SET status = 'running' WHERE replay_run_id = %s", (str(replay_run),)
    )
    await run_replay(app_engine, provisioner, replay_run, reclaimed=True)
    first = stored_report(owner, str(replay_run))
    for reclaimed in (False, True):
        await run_replay(app_engine, provisioner, replay_run, reclaimed=reclaimed)

    assert stored_report(owner, str(replay_run)) == first
    counts = owner.execute(
        "SELECT (SELECT count(*) FROM experiments WHERE run_id = %(r)s), "
        "(SELECT count(*) FROM investigation_reports WHERE run_id = %(r)s), "
        "(SELECT count(*) FROM replay_manifests WHERE run_id = %(r)s), "
        "(SELECT count(*) FROM investigation_events WHERE run_id = %(r)s "
        "AND type = 'run.concluded')",
        {"r": str(replay_run)},
    ).fetchone()
    assert counts == (1, 1, 1, 1)
    assert sealed(owner, replay_run)["builder"] == "report-builder@2"


async def test_api_worker_version_skew_keeps_every_sealed_report_verifiable(
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both skew directions during a deploy, with v2 registered everywhere (step 0):
    - the activated worker seals v2 while an old API (v1 current) reads and verifies it;
    - an old worker seals a marked replay with v1 while the activated API reads it.
    Report replay rebuilds each with its stored version; the API serves both."""
    _, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    no_llm(monkeypatch)
    new = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=True)
    assert sealed(owner, new)["builder"] == "report-builder@2"
    with monkeypatch.context() as old_api:
        pre_activation.deactivate(old_api.setattr)
        assert registry.CURRENT_BUILDER == "report-builder@1"
        assert await verified(app_engine, new) == ("verified", [])
        served = (await api.get(f"/api/v1/runs/{new}/report")).json()
        assert (served["builder_version"], served["report_schema_version"]) == (
            "report-builder@2",
            2,
        )

    with monkeypatch.context() as old_worker:
        pre_activation.deactivate(old_worker.setattr)
        old = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=True)
    assert creation_events(owner, str(old))[0].get("source_snapshot")  # marked, sealed by v1
    assert sealed(owner, old)["builder"] == "report-builder@1"
    assert registry.CURRENT_BUILDER == "report-builder@2"
    assert await verified(app_engine, old) == ("verified", [])
    assert await verified(app_engine, new) == ("verified", [])
    served = (await api.get(f"/api/v1/runs/{old}/report")).json()
    assert (served["builder_version"], served["report_schema_version"]) == ("report-builder@1", 1)


async def test_unknown_builder_version_is_reported_not_rebuilt(
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    migrated_db: str,
    provisioner: SandboxProvisioner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reader without report-builder@2 registered (an API older than step 0, or v2 wrongly
    unregistered) neither fails nor rebuilds: stored only, with a warning; the API still
    serves the stored report."""
    _, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    no_llm(monkeypatch)
    new = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=True)
    monkeypatch.delitem(registry.BUILDERS, "report-builder@2")
    status, warnings = await verified(app_engine, new)
    assert (status, warnings) == ("verified_stored_only", ["builder_retired"])
    served = await api.get(f"/api/v1/runs/{new}/report")
    assert served.status_code == 200
    assert served.json()["builder_version"] == "report-builder@2"


async def test_rollback_after_a_v2_seal_keeps_v2_reports_and_returns_to_v1(
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Revert the activation change only: v2 stays registered, the sealed v2 report keeps
    its bytes and verifies, and the next replay seals v1 (legacy-tagged in the UI)."""
    _, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    no_llm(monkeypatch)
    v2_run = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=True)
    before = stored_report(owner, str(v2_run))
    assert sealed(owner, v2_run)["builder"] == "report-builder@2"

    pre_activation.deactivate(monkeypatch.setattr)  # the activation commit reverted
    after_rollback = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=True)

    assert sealed(owner, after_rollback)["builder"] == "report-builder@1"
    assert stored_report(owner, str(v2_run)) == before
    assert await verified(app_engine, v2_run) == ("verified", [])
    assert await verified(app_engine, after_rollback) == ("verified", [])


def printed(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    """The command's JSON report (structured log lines may precede it on stdout)."""
    out = capsys.readouterr().out
    return json.loads(out[out.index('{\n "ready"') :])  # type: ignore[no-any-return]


async def test_cutover_check_blocks_while_a_legacy_replay_is_in_flight(
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`python -m querycure.ops replay-cutover-check`: read-only, exit 1 while a legacy replay
    is queued, 0 once it has concluded (here: cancelled by its user, never by the check)."""
    from querycure.ops.__main__ import _replay_cutover_check

    _, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    no_llm(monkeypatch)
    with monkeypatch.context() as old_code:
        as_legacy_start(old_code)
        started = await api.post(
            f"/api/v1/experiments/{experiment_id}/replay", json={"confirm_ddl": True}
        )
    attempt = started.json()
    monkeypatch.setenv("QC_CUTOVER_TEST_URL", migrated_db)

    assert await _replay_cutover_check("QC_CUTOVER_TEST_URL") == 1
    report = printed(capsys)
    assert report["ready"] is False
    mine = [r for r in report["replays"] if r["replay_run_id"] == attempt["replay_run_id"]]
    assert [(r["contract"], r["attempt_status"]) for r in mine] == [("legacy", "queued")]
    assert owner.execute(
        "SELECT status FROM replay_attempts WHERE id = %s", (attempt["id"],)
    ).fetchone() == ("queued",)

    assert (await api.post(f"/api/v1/replay-attempts/{attempt['id']}/cancel")).status_code == 202
    await _replay_cutover_check("QC_CUTOVER_TEST_URL")
    listed = [r["replay_run_id"] for r in printed(capsys)["replays"]]
    assert attempt["replay_run_id"] not in listed


async def test_a_replay_never_becomes_its_investigations_latest_run(
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    migrated_db: str,
    provisioner: SandboxProvisioner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """History and Dashboard show `latest_run` (`investigations.latest_run_id`), which only
    creation and re-investigation set (REPLAY_OUTCOME_AUDIT §18.2). A sealed replay, whatever
    its stored outcome, is therefore never what a list row or the outcome filter reads."""
    source_run, experiment_id = await finalized_sandbox_run(
        api, app_engine, migrated_db, provisioner
    )
    no_llm(monkeypatch)
    replay_run = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=True)

    items = (await api.get("/api/v1/investigations?limit=100")).json()["items"]
    latest = {i["latest_run"]["id"]: i["latest_run"] for i in items if i["latest_run"]}
    assert source_run in latest
    assert str(replay_run) not in latest
    assert all(r["kind"] != "experiment_replay" for r in latest.values())
    for outcome in ("verified_recommendation", "inconclusive"):
        page = (await api.get(f"/api/v1/investigations?outcome={outcome}&limit=100")).json()
        assert all(i["latest_run"]["kind"] != "experiment_replay" for i in page["items"])


# --- Failed, dead-lettered and cancelled ends keep the creation contract --------------------


async def test_legacy_replay_dead_lettered_after_activation_seals_v1(
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dead-letter path (`mark_replay_failed` + `fail_run`) seals outside `_close`; a
    legacy replay still gets report-builder@1 / report-md@1, a snapshot replay v2."""
    from querycure.agents.run import fail_run
    from querycure.replay.experiment_replay import mark_replay_failed

    _, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    no_llm(monkeypatch)
    with monkeypatch.context() as old_code:
        as_legacy_start(old_code)
        legacy = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=False)
    marked = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=False)
    for run_id in (legacy, marked):
        await mark_replay_failed(app_engine, run_id, "internal_error")
        await fail_run(app_engine, run_id, {"code": "JOB_DEAD_LETTERED"})

    assert {k: sealed(owner, legacy)[k] for k in ("builder", "renderer", "schema", "status")} == {
        "builder": "report-builder@1", "renderer": "report-md@1", "schema": 1, "status": "failed",
    }  # fmt: skip
    assert {k: sealed(owner, marked)[k] for k in ("builder", "renderer", "schema", "status")} == {
        "builder": "report-builder@2", "renderer": "report-md@2", "schema": 2, "status": "failed",
    }  # fmt: skip
    for run_id in (legacy, marked):
        assert sealed(owner, run_id)["outcome"] is None
        assert "replay_basis" not in sealed(owner, run_id)["concluded"]
        assert await verified(app_engine, run_id) == ("verified", [])


async def test_queued_replay_cancelled_after_activation_keeps_its_contract(
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancel through the API while queued (`cancel_replay_attempt` seals immediately): legacy
    seals v1, snapshot seals v2; neither invents an outcome or a basis."""
    _, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    no_llm(monkeypatch)
    with monkeypatch.context() as old_code:
        as_legacy_start(old_code)
        legacy = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=False)
    marked = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=False)
    for run_id in (legacy, marked):
        assert (await api.post(f"/api/v1/runs/{run_id}/cancel")).status_code == 202

    assert (sealed(owner, legacy)["builder"], sealed(owner, legacy)["schema"]) == (
        "report-builder@1",
        1,
    )
    assert (sealed(owner, marked)["builder"], sealed(owner, marked)["schema"]) == (
        "report-builder@2",
        2,
    )
    for run_id in (legacy, marked):
        row = sealed(owner, run_id)
        assert (row["status"], row["outcome"]) == ("cancelled", None)
        assert "replay_basis" not in row["concluded"]
        assert await verified(app_engine, run_id) == ("verified", [])


async def test_replay_whose_sandbox_fails_after_activation_seals_failed_without_outcome(
    api: httpx.AsyncClient,
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An execution failure never reaches the classifier: run `failed`, no outcome, no basis,
    v2 report; the attempt records the failure code."""
    from querycure.core.errors import SandboxUnavailableError

    _, experiment_id = await finalized_sandbox_run(api, app_engine, migrated_db, provisioner)
    no_llm(monkeypatch)

    def down(*a: Any, **k: Any) -> Any:
        raise SandboxUnavailableError("sandbox down")

    monkeypatch.setattr(experiment_replay, "run_experiment", down)
    replay_run = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=True)

    row = sealed(owner, replay_run)
    assert (row["builder"], row["status"], row["outcome"]) == ("report-builder@2", "failed", None)
    assert "replay_basis" not in row["concluded"]
    assert owner.execute(
        "SELECT status, failure_code FROM replay_attempts WHERE replay_run_id = %s",
        (str(replay_run),),
    ).fetchone() == ("failed", "sandbox_unavailable")
    assert await verified(app_engine, replay_run) == ("verified", [])
