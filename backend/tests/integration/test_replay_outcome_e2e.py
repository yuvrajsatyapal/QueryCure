"""Deterministic replay outcome scenarios on the real stack (Workstream 5, Phases 2 and 3).

Every scenario runs a real Mode C investigation (scripted LLM, real sandbox), seals it, starts
a replay through the API and executes it with the real replay handler, comparison, classifier
and report-builder@2 / report-md@2. Timing comes from the virtual clock (`virtual_clock.py`):
the measured samples are fixed per scenario, so each test exercises exactly its own rule and
never substitutes another. Production thresholds are untouched.

Since the ADR-0032 activation these exercise the production path: `_close` classifies the
replay and `finalize_run` seals it with the current report-builder@2 / report-md@2. Nothing
here substitutes the classifier, `_close`, `finalize_run` or the registry (`test_production_
path_is_not_substituted`); only rule 9a's comparison verdict is fixed at the comparison
boundary (`fix_comparison_status`), because a real comparison of a noise-warning original
cannot be `reproduced`.

Expected values come from the cross-layer matrix `frontend/src/test/fixtures/
replay-consistency.json`, which the builder unit tests and the frontend tests also read.
"""

import json
import uuid
from pathlib import Path
from typing import Any

import httpx2 as httpx
import psycopg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.replay.report_replay import verify_report
from querycure.reports import registry
from querycure.sandbox.provisioner import SandboxProvisioner
from tests.integration import virtual_clock as vc
from tests.integration.test_experiment_replay import (  # noqa: F401 - fixtures
    _no_active_runs,
    api,
    as_legacy_start,
    corrupt,
    drop_link,
    finalized_sandbox_run,
    fix_comparison_status,
    no_llm,
    start_and_seal,
    stored_report,
)
from tests.integration.test_optimization_graph import INDEX, NOTHING_MORE, candidates

pytestmark = pytest.mark.integration

MATRIX: dict[str, dict[str, Any]] = json.loads(
    (
        Path(__file__).parents[3] / "frontend" / "src" / "test" / "fixtures"
        / "replay-consistency.json"
    ).read_text()
)  # fmt: skip
SEED = 7
# Round 1's candidate: timed as a clear regression, so the loop asks for round 2.
UNUSED = {"kind": "create_index", "ddl": ["CREATE INDEX ON orders (total)"]}


async def concluded(owner: psycopg.Connection, run_id: str) -> dict[str, Any]:
    row = owner.execute(
        "SELECT payload FROM investigation_events WHERE run_id = %s AND type = 'run.concluded'",
        (run_id,),
    ).fetchone()
    assert row is not None
    return dict(row[0])


def manifest_outcome(owner: psycopg.Connection, run_id: str) -> Any:
    row = owner.execute(
        "SELECT a.content FROM replay_manifests m JOIN artifacts a ON a.sha256 = "
        "m.manifest_sha256 WHERE m.run_id = %s",
        (run_id,),
    ).fetchone()
    assert row is not None
    return json.loads(bytes(row[0]))["outcome"]


def attempt(owner: psycopg.Connection, replay_run: uuid.UUID) -> dict[str, Any]:
    row = owner.execute(
        "SELECT status, result FROM replay_attempts WHERE replay_run_id = %s", (str(replay_run),)
    ).fetchone()
    assert row is not None
    return {"status": row[0], "result": row[1] or {}}


async def check_row(
    name: str,
    replay_run: uuid.UUID,
    *,
    source_run: str,
    api: httpx.AsyncClient,  # noqa: F811
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
) -> dict[str, Any]:
    """Every layer of one sealed replay against the matrix row. Returns the report."""
    want = MATRIX[name]
    report, md, run_outcome = stored_report(owner, str(replay_run))
    att = attempt(owner, replay_run)
    event = await concluded(owner, str(replay_run))
    status_row = owner.execute(
        "SELECT status FROM investigation_runs WHERE id = %s", (str(replay_run),)
    ).fetchone()
    assert status_row is not None

    # persisted run, manifest and stored comparison verdict
    assert (status_row[0], run_outcome) == (want["run_status"], want["outcome"])
    assert manifest_outcome(owner, str(replay_run)) == want["outcome"]
    assert att["status"] == want["comparison_status"], att
    assert att["result"].get("comparison_mode") == want["comparison_mode"]
    # report JSON
    assert (report["schema_version"], report["builder_version"]) == (
        want["schema_version"],
        want["builder_version"],
    )
    assert report["outcome"] == want["outcome"]
    assert report["recommendation"]["status"] == want["recommendation_status"]
    assert report["recommendation"].get("origin") == want["recommendation_origin"]
    if want["legacy"]:
        assert "replay_basis" not in event
        assert "replay_result" not in report
    else:
        basis = event["replay_basis"]
        assert basis["code"] == want["basis"], basis
        assert (basis["comparison_status"], basis["comparison_mode"]) == (
            want["comparison_status"],
            want["comparison_mode"],
        )
        rr = report["replay_result"]
        assert rr["basis"] == basis  # the builder maps the sealed decision, never reclassifies
        assert (rr["result"], rr["title"]) == (want["result"], want["title"])
        assert rr["claims_reproduction"] is want["claims_reproduction"]
        assert rr["original_reproduced"] is want["original_reproduced"]
        assert rr["comparison_status"] == want["comparison_status"]
        assert report["headline"].startswith(want["title"])
        for key in ("material_drift", "correctness_reproduced"):
            if key in want:
                assert rr[key] is want[key], (key, rr[key])
        # invariants that hold in every scenario
        verified = report["outcome"] == "verified_recommendation"
        assert verified is (want["basis"] == "reproduced_source_recommendation")
        assert (report["recommendation"]["status"] != "none") is verified
        assert rr["source"] is None or rr["source"]["run_id"] == source_run
        # Markdown agrees with the JSON
        assert f"**{want['title']}**" in md or want["title"] in md
        assert "Verified recommendation" not in md
        assert ("## Original recommendation" in md) is verified
        assert "## Experiment Replay Result" in md
        if not want["claims_reproduction"]:
            assert "reproduced by replay" not in md.lower().replace("not reproduced by replay", "")
    # API returns the sealed report unchanged
    api_report = (await api.get(f"/api/v1/runs/{replay_run}/report")).json()
    assert api_report["report"] == report
    assert api_report["outcome"] == want["outcome"]
    assert (api_report["builder_version"], api_report["report_schema_version"]) == (
        want["builder_version"],
        want["schema_version"],
    )
    # exports carry the same sealed JSON and Markdown (the footer is outside the stored body)
    exported = (await api.get(f"/api/v1/runs/{replay_run}/report.json")).json()
    assert exported["report"] == report
    exported_md = (await api.get(f"/api/v1/runs/{replay_run}/report.md")).text
    assert exported_md.split("<!-- qc-export-footer -->")[0] == md
    # report replay reconstructs the same bytes
    async with app_engine.connect() as conn:
        result = await verify_report(conn, replay_run)
    checks = {c.name: c.status for c in result.checks}
    assert result.status == "verified", result.result_json()
    assert (checks["rebuild_json"], checks["rebuild_markdown"]) == ("ok", "ok")
    return report


Fixtures = tuple[httpx.AsyncClient, AsyncEngine, psycopg.Connection, str, SandboxProvisioner]


@pytest.fixture
def stack(
    api: httpx.AsyncClient,  # noqa: F811
    app_engine: AsyncEngine,
    owner: psycopg.Connection,
    migrated_db: str,
    provisioner: SandboxProvisioner,
) -> Fixtures:
    return api, app_engine, owner, migrated_db, provisioner


async def source(
    stack: Fixtures,
    clock: vc.VirtualClock,
    *,
    expect: str,
    oe: list[Any] | None = None,
) -> tuple[str, str]:
    api, app_engine, owner, migrated_db, provisioner = stack  # noqa: F811
    run_id, experiment_id = await finalized_sandbox_run(
        api, app_engine, migrated_db, provisioner, clock.options(), oe=oe
    )
    report, _, outcome = stored_report(owner, run_id)
    # the scenario's precondition, fixed by the clock: never silently another case
    assert (outcome, report["recommendation"]["status"]) == (
        "verified_recommendation",
        expect,
    ), report["headline"]
    return run_id, experiment_id


async def replay(
    stack: Fixtures,
    clock: vc.VirtualClock,
    experiment_id: str,
    profile: vc.Profile,
    **options: Any,
) -> uuid.UUID:
    api, app_engine, _, _, provisioner = stack  # noqa: F811
    clock.use(profile, seed=SEED + 1)
    return await start_and_seal(
        api, app_engine, provisioner, experiment_id, seal=True, options=clock.options(**options)
    )


def test_production_path_is_not_substituted() -> None:
    """These scenarios must prove the activated production code, not a stand-in: `_close`
    seals through the real `finalize_run`, classifies with the real classifier, and the
    registry's current contract is v2. No test-only activation module exists any more."""
    import importlib.util

    from querycure.replay import experiment_replay, finalize, outcome

    assert experiment_replay.finalize_run is finalize.finalize_run
    assert experiment_replay.classify_replay_outcome is outcome.classify_replay_outcome
    assert registry.current_versions() == registry.ReportVersions(
        "report-builder@2", "report-md@2", 2
    )
    assert importlib.util.find_spec("tests.rehearsal.activation") is None
    sources = Path(__file__).parents[1].rglob("*.py")
    seams = ('"finalize_run"', '"classify_replay_outcome"', '"_close"', '"CURRENT_BUILDER"')
    offenders = [
        str(f) for f in sources if f.name != Path(__file__).name
        and any(seam in f.read_text() for seam in seams)
    ]  # fmt: skip
    assert offenders == [str(Path(__file__).parents[1] / "rehearsal" / "pre_activation.py")]


# --- 1-5: a clean verified original, replayed under five measured conditions ---------------


@pytest.mark.parametrize(
    ("name", "profile", "options"),
    [
        ("reproduced", vc.CLEAN, {}),
        ("performance_drift", vc.DRIFTED, {}),
        ("not_reproduced", vc.REVERSED, {}),
        ("inconclusive_comparison", vc.UNDECIDABLE, {}),
        ("cross_environment", vc.CLEAN, {"container_runtime": "docker-relay"}),
    ],
)
async def test_clean_original(
    name: str,
    profile: vc.Profile,
    options: dict[str, Any],
    stack: Fixtures,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = vc.install(monkeypatch, vc.CLEAN, seed=SEED)
    run_id, experiment_id = await source(stack, clock, expect="verified")
    source_before = stored_report(stack[2], run_id)
    no_llm(monkeypatch)
    replay_run = await replay(stack, clock, experiment_id, profile, **options)
    report = await check_row(
        name, replay_run, source_run=run_id, api=stack[0], app_engine=stack[1], owner=stack[2]
    )
    if name == "reproduced":
        rec = source_before[0]["recommendation"]
        assert report["recommendation"]["candidate_key"] == rec["candidate_key"]
        assert report["recommendation"]["primary_measurement"] == rec["primary_measurement"]
        assert report["recommendation"]["source_run_id"] == run_id
    if name == "not_reproduced":
        assert report["replay_result"]["comparison_failure_code"] == "verdict_changed"
    # the source run's seal never changes
    assert stored_report(stack[2], run_id) == source_before


# --- 6: a noise-warning original -----------------------------------------------------------


async def test_noise_warning_original_real_comparison_is_inconclusive(
    stack: Fixtures, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The realistic path: the original's dispersion fails gate 4 in the comparison itself, so
    the comparison is inconclusive and the recommendation is not confirmed."""
    clock = vc.install(monkeypatch, vc.NOISY, seed=SEED)
    run_id, experiment_id = await source(stack, clock, expect="verified_with_noise_warning")
    no_llm(monkeypatch)
    replay_run = await replay(stack, clock, experiment_id, vc.NOISY)
    report = await check_row(
        "inconclusive_comparison",
        replay_run,
        source_run=run_id,
        api=stack[0],
        app_engine=stack[1],
        owner=stack[2],
    )
    assert report["replay_result"]["source_recommendation"]["status"] == (
        "verified_with_noise_warning"
    )


async def test_noise_warning_original_with_reproduced_comparison_is_not_confirmed(
    stack: Fixtures, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rule 8a itself (D8). A real comparison cannot report `reproduced` for a noise-warning
    original (gate 4), so the comparison verdict is fixed at its boundary to `reproduced`.
    Everything else is real: the source is a real noise-warning seal."""
    clock = vc.install(monkeypatch, vc.NOISY, seed=SEED)
    run_id, experiment_id = await source(stack, clock, expect="verified_with_noise_warning")
    no_llm(monkeypatch)
    fix_comparison_status(monkeypatch, "reproduced")
    replay_run = await replay(stack, clock, experiment_id, vc.NOISY)
    await check_row(
        "noise_warning_original",
        replay_run,
        source_run=run_id,
        api=stack[0],
        app_engine=stack[1],
        owner=stack[2],
    )


# --- 7: a replay of a replay -----------------------------------------------------------------


async def test_replay_of_a_replay_never_propagates_verification(
    stack: Fixtures, monkeypatch: pytest.MonkeyPatch
) -> None:
    api, app_engine, owner, _, _ = stack  # noqa: F811
    clock = vc.install(monkeypatch, vc.CLEAN, seed=SEED)
    run_id, experiment_id = await source(stack, clock, expect="verified")
    no_llm(monkeypatch)
    first = await replay(stack, clock, experiment_id, vc.CLEAN)
    await check_row("reproduced", first, source_run=run_id, api=api, app_engine=app_engine,
                    owner=owner)  # fmt: skip
    (replayed_experiment,) = owner.execute(
        "SELECT id FROM experiments WHERE run_id = %s", (str(first),)
    ).fetchall()
    second = await replay(stack, clock, str(replayed_experiment[0]), vc.CLEAN)
    report = await check_row(
        "replay_of_replay", second, source_run=str(first), api=api, app_engine=app_engine,
        owner=owner,
    )  # fmt: skip
    assert report["replay_result"]["source"]["run_kind"] == "experiment_replay"


# --- 8: the replayed experiment is not the one the recommendation rests on ------------------


async def test_mismatched_recommendation_experiment_is_not_confirmed(
    stack: Fixtures, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = stack[2]
    clock = vc.install(monkeypatch, vc.CLEAN, seed=SEED, arms=(vc.REGRESSED, vc.CLEAN))
    run_id, _ = await source(
        stack,
        clock,
        expect="verified",
        oe=[candidates(UNUSED), candidates(INDEX), NOTHING_MORE],
    )
    rows = owner.execute(
        "SELECT id, round FROM experiments WHERE run_id = %s AND replicate = 0 ORDER BY round",
        (run_id,),
    ).fetchall()
    assert [r[1] for r in rows] == [0, 1], rows  # two rounds: the recommendation is round 2's
    no_llm(monkeypatch)
    clock.use(vc.CLEAN, seed=SEED + 1, arms=(vc.REGRESSED,))
    api, app_engine, _, _, provisioner = stack  # noqa: F811
    replay_run = await start_and_seal(
        api, app_engine, provisioner, str(rows[0][0]), seal=True, options=clock.options()
    )
    report = await check_row(
        "mismatched_experiment", replay_run, source_run=run_id, api=api, app_engine=app_engine,
        owner=owner,
    )  # fmt: skip
    assert report["replay_result"]["experiment_match"]["matches"] is False


# --- 9: missing or corrupted snapshot --------------------------------------------------------


@pytest.mark.parametrize("fault", ["missing", "corrupted"])
async def test_missing_or_corrupted_snapshot_fails_closed(
    fault: str, stack: Fixtures, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The snapshot is damaged after start and before sealing (owner privileges; the app role
    cannot). The classifier then has no snapshot and the replay seals inconclusive."""
    from querycure.replay.experiment_replay import execute_experiment_replay
    from querycure.replay.source_snapshot import ROLE_REPORT_JSON

    api, app_engine, owner, _, provisioner = stack  # noqa: F811
    clock = vc.install(monkeypatch, vc.CLEAN, seed=SEED)
    _, experiment_id = await source(stack, clock, expect="verified")
    no_llm(monkeypatch)
    replay_run = await start_and_seal(api, app_engine, provisioner, experiment_id, seal=False)
    sql = drop_link(ROLE_REPORT_JSON) if fault == "missing" else corrupt(ROLE_REPORT_JSON)
    owner.execute(sql.replace(":r", "%(r)s"), {"r": str(replay_run)})
    clock.use(vc.CLEAN, seed=SEED + 1)
    await execute_experiment_replay(
        app_engine, replay_run, sandbox=provisioner, options=clock.options(), reclaimed=False
    )
    report, _, outcome = stored_report(owner, str(replay_run))
    want = MATRIX["snapshot_missing"]
    event = await concluded(owner, str(replay_run))
    assert (outcome, event["replay_basis"]["code"]) == (want["outcome"], want["basis"])
    rr = report["replay_result"]
    assert (rr["result"], rr["title"]) == (want["result"], want["title"])
    assert rr["snapshot_error"], rr
    assert report["recommendation"]["status"] == "none"
    assert attempt(owner, replay_run)["status"] == want["comparison_status"]


# --- 10: a historical report-builder@1 replay ------------------------------------------------


async def test_historical_v1_replay_keeps_its_stored_contract(
    stack: Fixtures, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A replay created by the pre-snapshot start code (no marker, no links) and concluded by
    the activated build keeps its creation contract (§18.4): report-builder@1 / report-md@1
    with the legacy winner-based outcome, no basis, tagged legacy in the UI. It rebuilds
    byte-identically and is never reclassified."""
    api, app_engine, owner, _, _ = stack  # noqa: F811
    assert (registry.CURRENT_BUILDER, registry.CURRENT_RENDERER) == (
        "report-builder@2",
        "report-md@2",
    )
    clock = vc.install(monkeypatch, vc.CLEAN, seed=SEED)
    run_id, experiment_id = await source(stack, clock, expect="verified")
    no_llm(monkeypatch)
    with monkeypatch.context() as old_start:
        as_legacy_start(old_start)
        replay_run = await replay(stack, clock, experiment_id, vc.CLEAN)
    await check_row(
        "historical_v1", replay_run, source_run=run_id, api=api, app_engine=app_engine,
        owner=owner,
    )  # fmt: skip
