# ruff: noqa: F811  (pytest fixtures imported from test_unaudited_winner are used as parameters)
"""Audit-completeness invariant on the failed-run path, on the metadata database only.

`fail_run` seals a run outside the graph (a dead-lettered job, a reaped lease). If the run had
already persisted an engine-`verified` candidate and the Benchmark Auditor then crashed on every
attempt, nothing downgraded the candidate, and the sealed failed-run report presented it as the
recommendation. `fail_run` must enforce audit completeness inside the transaction that seals.

REAL: graph orchestration and checkpoint resume across attempts, the `run_experiment` node and
its candidate transitions, the real auditor and `audit_experiment` where it runs,
`dead_job_handler`, `fail_run`, `finalize_run`, report building and sealing, every DB constraint.

REPLACED, and only these: benchmark execution (the committed recording, see
`test_unaudited_winner.py`, whose fixtures and synthetic `measured` wrapper this reuses), the
sandbox context reads, the LLM (scripted, no network), and the crashing node (a stand-in that
raises, to model "the auditor repeatedly fails" / "write_report crashes").
"""

import json
import uuid
from collections.abc import Sequence
from typing import Any

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from querycure.agents.run import RunServices, execute_run, fail_run
from querycure.agents.runtime import LlmClients
from querycure.audit.completeness import UnauditedCandidate, audit_incomplete_error
from querycure.benchmark.measurement_fixtures import (
    FixtureContext,
    FixtureMeasure,
    MeasurementFixture,
)
from querycure.evals.runner import _seed
from querycure.jobs import queue
from querycure.jobs.handlers import dead_job_handler
from querycure.replay.finalize import Conclusion, Finalized
from querycure.replay.finalize import finalize_run as real_finalize_run
from tests.fake_llm import RoleClient, Step
from tests.integration.test_context_nodes import SETTINGS
from tests.integration.test_eval_runner import case
from tests.integration.test_finalize import STEPS
from tests.integration.test_optimization_graph import NOTHING_MORE, candidates, scripts
from tests.integration.test_unaudited_winner import (  # noqa: F401  (fixtures)
    ANALYZE_DRAFT,
    ANALYZE_KEY,
    CASE_ID,
    INDEX_DRAFT,
    INDEX_KEY,
    NEUTRAL,
    RUN_ID,
    SyntheticMeasuredReplay,
    audit_errors,
    audits_by_key,
    candidate_id,
    candidate_states,
    db,
    engine,
    engine_reason_codes,
    failed_checks,
    fresh_db,
    recording,
    sealing,
)

pytestmark = pytest.mark.integration

ATTEMPTS = 3  # what a dead-lettered job has used up


def build_services(
    engine: AsyncEngine,
    url: str,
    recording: MeasurementFixture,
    *,
    synthetic_measured: bool,
    auditor: Sequence[Step],
) -> RunServices:
    assert recording.context is not None
    roles: dict[str, Sequence[Step]] = dict(
        scripts([candidates(INDEX_DRAFT, ANALYZE_DRAFT), NOTHING_MORE])
    )
    if auditor:
        roles["benchmark_auditor"] = auditor
    llm = RoleClient(roles)
    return RunServices(
        engine=engine,
        settings=SETTINGS,
        checkpoint_url=url,
        clients=lambda _inputs: LlmClients(primary=llm),
        checkpoint_role="qc_app",
        sandbox=None,
        measure=SyntheticMeasuredReplay(recording)
        if synthetic_measured
        else FixtureMeasure(recording),
        context_inspector=FixtureContext(recording.context),
    )


def crash(monkeypatch: pytest.MonkeyPatch, node: str) -> None:
    """The node raises on every attempt. LangGraph propagates it out of `execute_run`, which is
    what the worker sees: it retries, then dead-letters the job."""

    async def crashed(*_args: object) -> dict[str, Any]:
        raise RuntimeError(f"{node} is down")

    monkeypatch.setattr(f"querycure.agents.graph.{node}", crashed)


async def crashed_run(
    engine: AsyncEngine,
    url: str,
    recording: MeasurementFixture,
    *,
    synthetic_measured: bool = False,
    auditor: Sequence[Step] = (),
) -> RunServices:
    """Seed the recorded run, then fail every attempt after the node that crashes."""
    run_id = await _seed(url, case(CASE_ID), SETTINGS)
    assert run_id == RUN_ID, "the eval harness no longer derives this run id: re-derive the keys"
    services = build_services(
        engine, url, recording, synthetic_measured=synthetic_measured, auditor=auditor
    )
    for attempt in range(1, ATTEMPTS + 1):
        with pytest.raises(RuntimeError):
            await execute_run(services, RUN_ID, attempt=attempt, reclaimed=False)
    return services


async def dead_letter(services: RunServices) -> None:
    reaped = queue.ReapedJob(id=uuid.uuid4(), kind="run_start", run_id=RUN_ID)
    await dead_job_handler(services)(reaped)


def sealed_report(db: psycopg.Connection) -> dict[str, Any]:
    row = db.execute(
        "SELECT convert_from(a.content, 'UTF8') FROM run_artifacts ra "
        "JOIN artifacts a ON a.id = ra.artifact_id "
        "WHERE ra.run_id = %s AND ra.role = 'output.report_json'",
        (RUN_ID,),
    ).fetchone()
    assert row is not None, "no sealed report"
    report: dict[str, Any] = json.loads(row[0])
    return report


def run_error(db: psycopg.Connection) -> Any:
    row = db.execute("SELECT error FROM investigation_runs WHERE id = %s", (RUN_ID,)).fetchone()
    assert row is not None
    return row[0]


def snapshot(db: psycopg.Connection) -> dict[str, Any]:
    """Everything the gate and the seal write."""
    counts = db.execute(
        "SELECT type, count(*) FROM investigation_events WHERE run_id = %s GROUP BY type",
        (RUN_ID,),
    ).fetchall()
    return {
        "candidates": candidate_states(db, RUN_ID),
        "events": dict(counts),
        "sealing": sealing(db, RUN_ID),
        "error": run_error(db),
    }


def unaudited_index(db: psycopg.Connection) -> UnauditedCandidate:
    return UnauditedCandidate(
        id=candidate_id(db, RUN_ID, INDEX_KEY), key=INDEX_KEY, round=0, status="verified"
    )


# --- the bug: an unaudited verified candidate in a sealed failed-run report -------------------


async def test_a_failed_run_report_does_not_recommend_a_candidate_whose_audit_never_ran(
    engine: AsyncEngine,
    fresh_db: str,
    db: psycopg.Connection,
    recording: MeasurementFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crash(monkeypatch, "benchmark_auditor")
    services = await crashed_run(engine, fresh_db, recording)

    await dead_letter(services)

    recommendation = sealed_report(db)["recommendation"]
    assert recommendation["status"] == "unverified"
    assert recommendation["candidate_key"] is None
    assert recommendation["ddl"] == []
    assert recommendation["primary_measurement"] is None


async def test_a_dead_lettered_run_downgrades_an_unaudited_verified_candidate_and_seals(
    engine: AsyncEngine,
    fresh_db: str,
    db: psycopg.Connection,
    recording: MeasurementFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crash(monkeypatch, "benchmark_auditor")
    services = await crashed_run(engine, fresh_db, recording)
    assert candidate_states(db, RUN_ID)[INDEX_KEY] == ("verified", [])  # the engine verdict
    assert audits_by_key(db, RUN_ID) == {}  # and no audit: the precondition of the bug

    await dead_letter(services)

    unaudited = unaudited_index(db)
    assert candidate_states(db, RUN_ID) == {
        INDEX_KEY: ("inconclusive", ["audit_not_completed"]),
        ANALYZE_KEY: ("inconclusive", engine_reason_codes(recording, ANALYZE_KEY)),
    }
    assert audits_by_key(db, RUN_ID) == {}  # no verification row claims checks that never ran
    assert audit_errors(db, RUN_ID) == [audit_incomplete_error([unaudited], "failed").model_dump()]
    assert sealing(db, RUN_ID) == {
        "run": ("failed", None, True),
        "reports": [("failed", None)],
        "manifests": 1,
        "report_ready": 1,
        "stop_reason": "failed",
    }
    assert run_error(db) == {"code": "JOB_DEAD_LETTERED"}
    report = sealed_report(db)
    assert report["final_status"] == "failed"
    assert audit_incomplete_error([unaudited], "failed").model_dump() in report["errors"]


# --- what must not change ---------------------------------------------------------------------


async def test_an_audited_verified_candidate_stays_verified_in_a_failed_run(
    engine: AsyncEngine,
    fresh_db: str,
    db: psycopg.Connection,
    recording: MeasurementFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crash(monkeypatch, "write_report")  # after the audit completed
    services = await crashed_run(
        engine, fresh_db, recording, synthetic_measured=True, auditor=[NEUTRAL, NEUTRAL]
    )

    await dead_letter(services)

    audits = audits_by_key(db, RUN_ID)
    assert (audits[INDEX_KEY]["engine_verdict"], audits[INDEX_KEY]["verdict"]) == (
        "verified",
        "verified",
    )
    assert failed_checks(audits[INDEX_KEY]) == []
    assert candidate_states(db, RUN_ID) == {
        INDEX_KEY: ("verified", []),
        ANALYZE_KEY: ("inconclusive", engine_reason_codes(recording, ANALYZE_KEY)),
    }
    assert audit_errors(db, RUN_ID) == []
    sealed = sealing(db, RUN_ID)
    assert sealed["run"] == ("failed", None, True)
    assert sealed["reports"] == [("failed", None)]
    recommendation = sealed_report(db)["recommendation"]
    assert (recommendation["status"], recommendation["candidate_key"]) == ("verified", INDEX_KEY)


async def test_a_downgrade_made_by_the_auditor_is_left_exactly_as_it_was(
    engine: AsyncEngine,
    fresh_db: str,
    db: psycopg.Connection,
    recording: MeasurementFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crash(monkeypatch, "write_report")
    services = await crashed_run(engine, fresh_db, recording, auditor=[NEUTRAL, NEUTRAL])
    # Prerecorded samples: the real provenance check fails and the auditor downgrades the index.
    assert candidate_states(db, RUN_ID)[INDEX_KEY] == ("inconclusive", ["audit_downgrade"])
    before_reasons = db.execute(
        "SELECT verdict_reasons FROM optimization_candidates WHERE run_id = %s AND key = %s",
        (RUN_ID, INDEX_KEY),
    ).fetchone()

    await dead_letter(services)

    audits = audits_by_key(db, RUN_ID)
    assert failed_checks(audits[INDEX_KEY]) == ["provenance"]
    assert candidate_states(db, RUN_ID)[INDEX_KEY] == ("inconclusive", ["audit_downgrade"])
    assert (
        db.execute(
            "SELECT verdict_reasons FROM optimization_candidates WHERE run_id = %s AND key = %s",
            (RUN_ID, INDEX_KEY),
        ).fetchone()
        == before_reasons
    )
    assert audit_errors(db, RUN_ID) == []
    assert sealing(db, RUN_ID)["run"] == ("failed", None, True)
    assert sealed_report(db)["recommendation"]["status"] == "unverified"


# --- transaction safety -----------------------------------------------------------------------


@pytest.mark.parametrize("step", STEPS)
async def test_a_fault_while_sealing_rolls_back_the_downgrade_and_its_event(
    engine: AsyncEngine,
    fresh_db: str,
    db: psycopg.Connection,
    recording: MeasurementFixture,
    monkeypatch: pytest.MonkeyPatch,
    step: str,
) -> None:
    crash(monkeypatch, "benchmark_auditor")
    services = await crashed_run(engine, fresh_db, recording)
    inside: dict[str, Any] = {}

    async def faulty(
        conn: AsyncConnection, run_id: uuid.UUID, conclusion: Conclusion, **_kw: Any
    ) -> Finalized:
        # What this transaction holds at the moment sealing starts.
        inside["candidates"] = dict(
            (
                await conn.execute(
                    text("SELECT key, status FROM optimization_candidates WHERE run_id = :r"),
                    {"r": run_id},
                )
            ).all()
        )
        inside["gate_events"] = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM investigation_events WHERE run_id = :r "
                    "AND type = 'error' AND payload->>'code' = 'AUDIT_NOT_COMPLETED'"
                ),
                {"r": run_id},
            )
        ).scalar_one()

        def fault(name: str) -> None:
            if name == step:
                raise RuntimeError(f"injected fault after {name}")

        return await real_finalize_run(conn, run_id, conclusion, fault=fault)

    monkeypatch.setattr("querycure.agents.run.finalize_run", faulty)

    await dead_letter(services)

    # The downgrade and the event were written in the same transaction as the seal ...
    assert inside == {
        "candidates": {INDEX_KEY: "inconclusive", ANALYZE_KEY: "inconclusive"},
        "gate_events": 1,
    }
    # ... so the fault took them back with everything else. The fallback marks the run failed
    # without a report (existing behaviour) and does not enforce the gate.
    assert candidate_states(db, RUN_ID)[INDEX_KEY] == ("verified", [])
    assert audit_errors(db, RUN_ID) == []
    assert db.execute(
        "SELECT status, finalized_at IS NOT NULL FROM investigation_runs WHERE id = %s",
        (RUN_ID,),
    ).fetchone() == ("failed", False)
    assert db.execute(
        "SELECT (SELECT count(*) FROM investigation_reports WHERE run_id = %s), "
        "(SELECT count(*) FROM replay_manifests WHERE run_id = %s)",
        (RUN_ID, RUN_ID),
    ).fetchone() == (0, 0)
    assert run_error(db) == {"code": "JOB_DEAD_LETTERED"}


async def test_repeated_calls_on_a_sealed_run_change_nothing(
    engine: AsyncEngine,
    fresh_db: str,
    db: psycopg.Connection,
    recording: MeasurementFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crash(monkeypatch, "benchmark_auditor")
    services = await crashed_run(engine, fresh_db, recording)
    await dead_letter(services)
    sealed = snapshot(db)
    assert len(audit_errors(db, RUN_ID)) == 1  # downgraded once
    assert sealed["sealing"]["run"] == ("failed", None, True)

    await fail_run(engine, RUN_ID, {"code": "JOB_DEAD_LETTERED"})
    await fail_run(engine, RUN_ID, {"code": "SOMETHING_ELSE"})
    await dead_letter(services)

    assert snapshot(db) == sealed
    assert candidate_states(db, RUN_ID)[INDEX_KEY] == ("inconclusive", ["audit_not_completed"])
