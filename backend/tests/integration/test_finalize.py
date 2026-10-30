"""finalize_run (T4.5, REPLAY_ENGINE §5, TESTING_STRATEGY §3 Finalization), as qc_app.

- fault injection after each step leaves no manifest, no report row and an unchanged status;
- a re-run after commit is a no-op returning the same seal;
- a gap in the event log aborts finalization;
- after the seal, content events and content writes are refused; lifecycle events are not;
- the stored report rebuilds byte-identically from the records;
- terminal paths outside the graph (dead-lettered job, API cancel) are finalized too.
"""

import uuid
from typing import Any

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.agents.run import fail_run
from querycure.core.errors import RunFinalizedError
from querycure.domain.investigation import Evidence
from querycure.domain.runs import RunOutcome, RunStatus
from querycure.events.emitter import emit
from querycure.events.types import EventType
from querycure.evidence.store import record_evidence
from querycure.replay.artifact_store import link, store_json
from querycure.replay.canonical import canonical_json, canonical_text, to_canonical
from querycure.replay.digest import digest
from querycure.replay.events_digest import EventLogGapError
from querycure.replay.finalize import Conclusion, finalize_run
from querycure.reports import registry
from querycure.reports.inputs import load_report_inputs
from querycure.reports.provenance import unlabeled_numbers
from tests.integration.run_helpers import add_evidence, new_run

pytestmark = pytest.mark.integration

DONE = Conclusion(
    final_status=RunStatus.COMPLETED,
    outcome=RunOutcome.UNVERIFIED_RECOMMENDATIONS,
    stop_reason=None,
    synthesis_summary="Summary.",
)
PAYLOAD = (
    '{"schema_version": 1, "workload_id": "w", "sandbox": "s", "baseline_query": "SELECT 1", '
    '"param_sets": [], "candidates": [{"candidate_id": "00000000-0000-4000-8000-000000000001", '
    '"key": "oc_000000000001", "kind": "create_index", "ddl": [], "query_sql": null, '
    '"sql_sha256": "x", "expected_benefit": "b", "risks": []}]}'
)
STEPS = ("concluded", "digest", "report", "manifest", "closed")


async def prepared(engine: AsyncEngine) -> uuid.UUID:
    run_id = await new_run(engine)
    await add_evidence(engine, run_id, ["plan_summary", "plan_node"])
    async with engine.begin() as conn:
        await emit(conn, run_id, EventType.NODE_STARTED, {"node": "intake", "attempt": 1})
    return run_id


def state(owner: psycopg.Connection, run_id: uuid.UUID) -> tuple[Any, ...]:
    row = owner.execute(
        "SELECT r.status, r.finalized_at IS NOT NULL, "
        "(SELECT count(*) FROM replay_manifests m WHERE m.run_id = r.id), "
        "(SELECT count(*) FROM investigation_reports p WHERE p.run_id = r.id), "
        "(SELECT count(*) FROM investigation_events e WHERE e.run_id = r.id) "
        "FROM investigation_runs r WHERE r.id = %s",
        (run_id,),
    ).fetchone()
    assert row is not None
    return tuple(row)


class Boom(RuntimeError):
    pass


@pytest.mark.parametrize("fail_at", STEPS)
async def test_fault_after_any_step_leaves_nothing_visible(
    app_engine: AsyncEngine, owner: psycopg.Connection, fail_at: str
) -> None:
    run_id = await prepared(app_engine)
    before = state(owner, run_id)

    def fault(step: str) -> None:
        if step == fail_at:
            raise Boom(step)

    with pytest.raises(Boom):
        async with app_engine.begin() as conn:
            await finalize_run(conn, run_id, DONE, fault=fault)

    assert state(owner, run_id) == before
    assert before[:4] == ("running", False, 0, 0)


async def test_finalization_seals_once_and_is_idempotent(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    run_id = await prepared(app_engine)

    async with app_engine.begin() as conn:
        first = await finalize_run(conn, run_id, DONE)
    async with app_engine.begin() as conn:
        again = await finalize_run(conn, run_id, DONE)

    assert not first.already
    assert again.already
    assert (again.manifest_sha256, again.report_json_sha256) == (
        first.manifest_sha256,
        first.report_json_sha256,
    )
    status, sealed, manifests, reports, events = state(owner, run_id)
    assert (status, sealed, manifests, reports) == ("completed", True, 1, 1)
    types = [
        r[0]
        for r in owner.execute(
            "SELECT type FROM investigation_events WHERE run_id = %s ORDER BY seq", (run_id,)
        )
    ]
    cutoff = owner.execute(
        "SELECT events_cutoff_seq FROM investigation_runs WHERE id = %s", (run_id,)
    ).fetchone()
    assert cutoff is not None
    # Content events up to and including run.concluded are sealed; lifecycle events follow.
    assert types[cutoff[0] - 1] == "run.concluded"
    assert types[cutoff[0] :] == ["run.status_changed", "report.ready"]
    assert events == len(types)


async def test_manifest_is_consistent_and_excludes_itself(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    run_id = await prepared(app_engine)
    async with app_engine.begin() as conn:
        done = await finalize_run(conn, run_id, DONE)

    row = owner.execute(
        "SELECT a.content, a.sha256, m.events_digest, m.events_cutoff_seq FROM replay_manifests m "
        "JOIN artifacts a ON a.id = m.manifest_artifact_id WHERE m.run_id = %s",
        (run_id,),
    ).fetchone()
    assert row is not None
    content, sha, events_digest, cutoff = row
    assert digest("qc-json-v1", bytes(content)) == sha == done.manifest_sha256
    import json

    manifest = json.loads(bytes(content))
    assert manifest["events"] == {
        "cutoff_seq": cutoff,
        "count": cutoff,
        "digest": events_digest,
        "profile": "qc-events-v1",
    }
    assert manifest["report"]["json"] == f"sha256:{done.report_json_sha256}"
    assert manifest["report"]["builder_version"] == "report-builder@2"
    assert manifest["report"]["md_renderer_version"] == "report-md@2"
    assert manifest["report"]["report_schema_version"] == 2
    assert all(a["role"] != "output.manifest" for a in manifest["artifacts"])
    assert manifest["artifacts"] == sorted(
        manifest["artifacts"], key=lambda a: (a["role"], a["digest"])
    )
    assert manifest["app"]["benchmark_engine_version"] == "bench@2"
    assert manifest["app"]["alembic_revision"] is not None
    # Nothing stored inside the run contains the manifest digest (no circular hashing).
    report = owner.execute(
        "SELECT convert_from(a.content, 'UTF8') FROM run_artifacts ra JOIN artifacts a "
        "ON a.id = ra.artifact_id WHERE ra.run_id = %s AND ra.role LIKE 'output.report%%'",
        (run_id,),
    ).fetchall()
    assert report
    assert all(done.manifest_sha256 not in r[0] for r in report)


async def test_event_gap_aborts_finalization(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    run_id = await prepared(app_engine)
    owner.execute("DELETE FROM investigation_events WHERE run_id = %s AND seq = 1", (run_id,))

    with pytest.raises(EventLogGapError):
        async with app_engine.begin() as conn:
            await finalize_run(conn, run_id, DONE)

    assert state(owner, run_id)[:4] == ("running", False, 0, 0)


async def test_sealed_run_refuses_content_but_allows_lifecycle(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    run_id = await prepared(app_engine)
    async with app_engine.begin() as conn:
        await finalize_run(conn, run_id, DONE)

    with pytest.raises(RunFinalizedError):
        async with app_engine.begin() as conn:
            await emit(conn, run_id, EventType.AGENT_SUMMARY, {"agent": "x", "text": "late"})
    with pytest.raises(RunFinalizedError):
        await record_evidence(
            app_engine,
            run_id,
            [
                Evidence(
                    id="ev_" + "0" * 12,
                    kind="user_input",
                    artifact_sha256=None,
                    locator="/late",
                    summary="late",
                    data={},
                    provenance="imported",
                )
            ],
        )
    async with app_engine.begin() as conn:
        art = await store_json(conn, kind="agent_output", value={"late": True})
    async with app_engine.begin() as conn:
        with pytest.raises(RunFinalizedError):
            await link(conn, run_id=run_id, artifact_id=art.id, role="output.agent")
    async with app_engine.begin() as conn:  # lifecycle events stay allowed (outside the seal)
        await emit(conn, run_id, EventType.REPORT_READY, {"report_url": "x"})


async def test_stored_report_rebuilds_byte_identically(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    run_id = await prepared(app_engine)
    async with app_engine.begin() as conn:
        done = await finalize_run(conn, run_id, DONE)

    async with app_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT finalized_at, events_cutoff_seq FROM investigation_runs WHERE id = :id"
                ),
                {"id": run_id},
            )
        ).one()
        digest_row = (
            await conn.execute(
                text("SELECT events_digest FROM replay_manifests WHERE run_id = :id"),
                {"id": run_id},
            )
        ).one()
        inputs = await load_report_inputs(conn, run_id, row.events_cutoff_seq)
    rebuilt = registry.build(
        registry.CURRENT_BUILDER,
        inputs,
        finalized_at=to_canonical(row.finalized_at),
        cutoff_seq=row.events_cutoff_seq,
        events_digest=digest_row.events_digest,
    )
    assert digest("qc-json-v1", canonical_json(to_canonical(rebuilt))) == done.report_json_sha256
    md = registry.RENDERERS[registry.CURRENT_RENDERER](rebuilt)
    assert digest("qc-text-v1", canonical_text(md)) == done.report_md_sha256
    assert unlabeled_numbers(md) == []


async def test_dead_lettered_run_is_finalized_with_a_partial_report(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    run_id = await prepared(app_engine)

    await fail_run(app_engine, run_id, {"code": "JOB_DEAD_LETTERED"})

    status, sealed, manifests, reports, _ = state(owner, run_id)
    assert (status, sealed, manifests, reports) == ("failed", True, 1, 1)
    row = owner.execute(
        "SELECT final_status, outcome FROM investigation_reports WHERE run_id = %s", (run_id,)
    ).fetchone()
    assert row == ("failed", None)
    error = owner.execute(
        "SELECT error FROM investigation_runs WHERE id = %s", (run_id,)
    ).fetchone()
    assert error is not None
    assert error[0] == {"code": "JOB_DEAD_LETTERED"}


async def test_approval_sweep_never_touches_a_sealed_run(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    from querycure.jobs.approvals import expire_approvals

    run_id = await prepared(app_engine)
    owner.execute(
        "INSERT INTO approval_requests (run_id, user_id, round, kind, payload, expires_at) "
        "VALUES (%s, uuid_generate_v4(), 0, 'sandbox_execution', %s, now() - interval '1 h')",
        (run_id, PAYLOAD),
    )
    async with app_engine.begin() as conn:
        await finalize_run(
            conn,
            run_id,
            Conclusion(final_status=RunStatus.CANCELLED, outcome=None, stop_reason="cancelled"),
        )

    assert await expire_approvals(app_engine) == []
    status = owner.execute(
        "SELECT status FROM approval_requests WHERE run_id = %s", (run_id,)
    ).fetchone()
    assert status == ("pending",)


async def test_replay_basis_is_written_only_when_set(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    """ADR-0026 pattern: an optional `run.concluded` key, absent unless the caller sets it, so
    every existing run's payload bytes are unchanged (REPLAY_OUTCOME_AUDIT §12.1)."""
    plain, marked = await prepared(app_engine), await prepared(app_engine)
    basis = {"code": "source_not_verified", "source_outcome": None,
             "comparison_status": None, "comparison_mode": None}  # fmt: skip
    async with app_engine.begin() as conn:
        await finalize_run(conn, plain, DONE)
        await finalize_run(
            conn,
            marked,
            Conclusion(
                final_status=RunStatus.COMPLETED,
                outcome=RunOutcome.UNVERIFIED_RECOMMENDATIONS,
                stop_reason=None,
                replay_basis=basis,
            ),
        )

    def concluded(run_id: uuid.UUID) -> dict[str, Any]:
        row = owner.execute(
            "SELECT payload FROM investigation_events WHERE run_id = %s AND type = 'run.concluded'",
            (run_id,),
        ).fetchone()
        assert row is not None
        return dict(row[0])

    assert "replay_basis" not in concluded(plain)
    assert concluded(marked)["replay_basis"] == basis


def sealed_versions(owner: psycopg.Connection, run_id: uuid.UUID) -> tuple[Any, ...]:
    """(row builder, row renderer, row schema, manifest builder, manifest renderer,
    manifest schema, report JSON builder, report JSON schema)."""
    row = owner.execute(
        "SELECT ir.builder_version, ir.md_renderer_version, ir.report_schema_version, "
        "convert_from(ma.content, 'UTF8'), convert_from(j.content, 'UTF8') "
        "FROM investigation_reports ir JOIN artifacts j ON j.id = ir.report_json_artifact_id "
        "JOIN replay_manifests m ON m.run_id = ir.run_id "
        "JOIN artifacts ma ON ma.id = m.manifest_artifact_id WHERE ir.run_id = %s",
        (run_id,),
    ).fetchone()
    assert row is not None
    import json

    manifest, report = json.loads(row[3])["report"], json.loads(row[4])
    return (
        row[0], row[1], row[2], manifest["builder_version"], manifest["md_renderer_version"],
        manifest["report_schema_version"], report["builder_version"], report["schema_version"],
    )  # fmt: skip


async def test_new_reports_seal_with_the_current_v2_contract(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    """ADR-0032 activation: with no explicit choice, a new report is report-builder@2 /
    report-md@2 / schema 2 everywhere it is recorded."""
    run_id = await prepared(app_engine)
    async with app_engine.begin() as conn:
        await finalize_run(conn, run_id, DONE)

    assert sealed_versions(owner, run_id) == (
        "report-builder@2", "report-md@2", 2, "report-builder@2", "report-md@2", 2,
        "report-builder@2", 2,
    )  # fmt: skip


async def test_explicit_legacy_versions_seal_v1_byte_identically_while_v2_is_current(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    """The legacy contract chosen explicitly: builder, renderer and schema are recorded as v1
    in the reports row, the manifest and the report, and the stored bytes rebuild with v1."""
    run_id = await prepared(app_engine)
    async with app_engine.begin() as conn:
        done = await finalize_run(conn, run_id, DONE, versions=registry.LEGACY_REPORT_VERSIONS)

    assert sealed_versions(owner, run_id) == (
        "report-builder@1", "report-md@1", 1, "report-builder@1", "report-md@1", 1,
        "report-builder@1", 1,
    )  # fmt: skip
    async with app_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT r.finalized_at, r.events_cutoff_seq, m.events_digest FROM "
                    "investigation_runs r JOIN replay_manifests m ON m.run_id = r.id "
                    "WHERE r.id = :id"
                ),
                {"id": run_id},
            )
        ).one()
        inputs = await load_report_inputs(conn, run_id, row.events_cutoff_seq)
    rebuilt = registry.build(
        "report-builder@1",
        inputs,
        finalized_at=to_canonical(row.finalized_at),
        cutoff_seq=row.events_cutoff_seq,
        events_digest=row.events_digest,
    )
    assert digest("qc-json-v1", canonical_json(to_canonical(rebuilt))) == done.report_json_sha256
    md = registry.RENDERERS["report-md@1"](rebuilt)
    assert digest("qc-text-v1", canonical_text(md)) == done.report_md_sha256


@pytest.mark.parametrize(
    "versions",
    [
        registry.ReportVersions("report-builder@9", "report-md@2", 2),
        registry.ReportVersions("report-builder@2", "report-md@1", 2),
        registry.ReportVersions("report-builder@1", "report-md@1", 2),
    ],
)
async def test_unsupported_report_versions_are_refused_before_anything_is_written(
    app_engine: AsyncEngine, owner: psycopg.Connection, versions: registry.ReportVersions
) -> None:
    run_id = await prepared(app_engine)
    before = state(owner, run_id)

    with pytest.raises(registry.UnsupportedReportVersionError):
        async with app_engine.begin() as conn:
            await finalize_run(conn, run_id, DONE, versions=versions)

    assert state(owner, run_id) == before


async def test_a_builder_that_emits_another_contract_is_refused(
    app_engine: AsyncEngine, owner: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The recorded versions come from one checked contract; a builder whose output names
    another builder or schema fails the seal instead of recording a mismatch."""
    run_id = await prepared(app_engine)
    before = state(owner, run_id)
    v1 = registry.BUILDERS["report-builder@1"]
    monkeypatch.setitem(registry.BUILDERS, "report-builder@2", v1)

    with pytest.raises(registry.UnsupportedReportVersionError, match="emitted"):
        async with app_engine.begin() as conn:
            await finalize_run(conn, run_id, DONE)

    assert state(owner, run_id) == before
