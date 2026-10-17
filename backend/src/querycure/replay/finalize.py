"""finalize_run (REPLAY_ENGINE §5, ADR-0015): seal a run in one metadata-DB transaction.

    lock run → [already finalized: return it] → emit run.concluded (last content event)
    → cutoff = last seq → events digest → report JSON + Markdown (versioned, pure)
    → investigation_reports → manifest artifact + replay_manifests
    → finalized_at / events_cutoff_seq → terminal status (lifecycle event) → report.ready

The caller owns the transaction: an exception anywhere leaves nothing visible and the run in
its previous status, and a re-run after a crash returns the existing seal. Hash chain is one
directional (events → report → manifest); nothing inside the run contains the manifest digest.
`finalized_at` is the database clock, read once; the builders read no clock.
"""

import json
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure import __version__
from querycure.core.errors import InvalidStateError
from querycure.domain.benchmark import ENGINE_VERSION
from querycure.domain.runs import TERMINAL_STATUSES, RunOutcome, RunStatus
from querycure.events.emitter import change_status, emit
from querycure.events.types import EventType
from querycure.replay.artifact_store import link, store_json, store_text
from querycure.replay.canonical import to_canonical
from querycure.replay.events_digest import PROFILE as EVENTS_PROFILE
from querycure.replay.events_digest import events_digest
from querycure.reports import registry
from querycure.reports.inputs import load_report_inputs

MANIFEST_SCHEMA_VERSION = 1
FINALIZER_NODE = "finalize_run"
Fault = Callable[[str], None]


@dataclass(frozen=True)
class Conclusion:
    final_status: RunStatus
    outcome: RunOutcome | None
    stop_reason: str | None
    synthesis_summary: str = ""
    materiality: dict[str, Any] | None = None
    no_action_evidence: list[str] = field(default_factory=list)
    error: dict[str, Any] | None = None
    # ADR-0026: sentences of the AI summary removed for contradicting final verdicts. Only
    # written when something was removed; report-builder@1 does not read it.
    narrative_check: dict[str, Any] | None = None


@dataclass(frozen=True)
class Finalized:
    run_id: uuid.UUID
    manifest_sha256: str
    report_json_sha256: str
    report_md_sha256: str
    final_status: str
    outcome: str | None
    already: bool


def _ref(sha: str | None) -> str | None:
    return None if sha is None else f"sha256:{sha}"


async def _existing(conn: AsyncConnection, run_id: uuid.UUID) -> Finalized:
    row = (
        await conn.execute(
            text(
                "SELECT m.manifest_sha256, r.report_json_sha256, r.report_md_sha256, "
                "r.final_status, r.outcome FROM replay_manifests m "
                "JOIN investigation_reports r ON r.run_id = m.run_id WHERE m.run_id = :id"
            ),
            {"id": run_id},
        )
    ).one()
    return Finalized(
        run_id=run_id,
        manifest_sha256=row.manifest_sha256,
        report_json_sha256=row.report_json_sha256,
        report_md_sha256=row.report_md_sha256,
        final_status=row.final_status,
        outcome=row.outcome,
        already=True,
    )


async def _manifest(
    conn: AsyncConnection,
    run_id: uuid.UUID,
    *,
    run: Any,
    finalized_at: str,
    conclusion: Conclusion,
    cutoff: int,
    digest: str,
    report: dict[str, Any],
    report_sha: str,
    md_sha: str,
) -> dict[str, Any]:
    roles = (
        await conn.execute(
            text(
                "SELECT ra.role, a.canonicalization, a.sha256 FROM run_artifacts ra "
                "JOIN artifacts a ON a.id = ra.artifact_id WHERE ra.run_id = :run "
                "ORDER BY ra.role, a.sha256"
            ),
            {"run": run_id},
        )
    ).all()
    by_role: dict[str, list[str]] = {}
    for r in roles:
        by_role.setdefault(r.role, []).append(f"sha256:{r.sha256}")
    experiments = (
        await conn.execute(
            text(
                "SELECT e.id, c.sha256 AS config, e.environment_digest, r.sha256 AS result, "
                "e.engine_version, e.row_profile FROM experiments e "
                "JOIN artifacts c ON c.id = e.config_artifact_id "
                "LEFT JOIN artifacts r ON r.id = e.result_artifact_id "
                "WHERE e.run_id = :run ORDER BY e.round, e.replicate, e.id"
            ),
            {"run": run_id},
        )
    ).all()
    revision = (
        await conn.execute(text("SELECT version_num FROM alembic_version"))
    ).scalar_one_or_none()
    first = {role: refs[0] for role, refs in by_role.items()}
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "run_id": str(run_id),
        "investigation_id": str(run.investigation_id),
        "run_kind": run.kind,
        "parent_run_id": str(run.parent_run_id) if run.parent_run_id else None,
        "finalized_at": finalized_at,
        "final_status": conclusion.final_status.value,
        "outcome": conclusion.outcome.value if conclusion.outcome else None,
        "app": {
            "version": __version__,
            "git_sha": os.environ.get("QC_GIT_SHA", "unrecorded"),
            "alembic_revision": revision,
            "benchmark_engine_version": ENGINE_VERSION,
        },
        "inputs": {
            "query": first.get("input.query"),
            "param_sets": first.get("input.param_sets"),
            "schema_snapshot": first.get("input.schema") or first.get("context.schema_snapshot"),
            "plans": sorted(by_role.get("input.plan", []) + by_role.get("context.plan", [])),
        },
        "llm": [
            {
                "agent": c["agent"],
                "provider": run.llm_provider,
                "model": c["model"],
                "served_by": c["served_by"],
                "prompt_version": c["prompt_version"],
                "status": c["status"],
                "calls": c["calls"],
            }
            for c in report["provenance"]["llm"]
        ],
        "events": {
            "cutoff_seq": cutoff,
            "count": cutoff,
            "digest": digest,
            "profile": EVENTS_PROFILE,
        },
        "report": {
            "json": _ref(report_sha),
            "markdown": _ref(md_sha),
            "report_schema_version": report["schema_version"],
            "builder_version": report["builder_version"],
            "md_renderer_version": registry.CURRENT_RENDERER,
        },
        "artifacts": [
            {"role": r.role, "profile": r.canonicalization, "digest": f"sha256:{r.sha256}"}
            for r in roles
        ],
        "experiments": [
            {
                "id": str(e.id),
                "config": _ref(e.config),
                "environment": e.environment_digest,
                "result": _ref(e.result),
                "engine_version": e.engine_version,
                "row_profile": e.row_profile,
            }
            for e in experiments
        ],
    }


async def finalize_run(
    conn: AsyncConnection,
    run_id: uuid.UUID,
    conclusion: Conclusion,
    *,
    fault: Fault | None = None,
) -> Finalized:
    def step(name: str) -> None:
        if fault is not None:
            fault(name)

    run = (
        await conn.execute(
            text(
                "SELECT id, investigation_id, kind, parent_run_id, status, usage, finalized_at, "
                "llm_provider FROM investigation_runs WHERE id = :id FOR UPDATE"
            ),
            {"id": run_id},
        )
    ).one()
    if run.finalized_at is not None:
        return await _existing(conn, run_id)
    current = RunStatus(run.status)
    if current in TERMINAL_STATUSES:
        raise InvalidStateError("A terminal run that was never finalized cannot be sealed now.")
    if (conclusion.final_status is RunStatus.COMPLETED) != (conclusion.outcome is not None):
        raise ValueError("an outcome is required for, and only for, the completed status")

    await emit(
        conn,
        run_id,
        EventType.RUN_CONCLUDED,
        to_canonical(
            {
                "final_status": conclusion.final_status.value,
                "outcome": conclusion.outcome.value if conclusion.outcome else None,
                "stop_reason": conclusion.stop_reason,
                "synthesis_summary": conclusion.synthesis_summary,
                "materiality": conclusion.materiality,
                "no_action_evidence": sorted(conclusion.no_action_evidence),
                "usage": run.usage,
                "error": conclusion.error,
                **(
                    {"narrative_check": conclusion.narrative_check}
                    if conclusion.narrative_check
                    else {}
                ),
            }
        ),
    )
    step("concluded")
    cutoff = int(
        (
            await conn.execute(
                text("SELECT last_event_seq FROM investigation_runs WHERE id = :id"),
                {"id": run_id},
            )
        ).scalar_one()
    )
    digest = await events_digest(conn, run_id, cutoff)
    step("digest")

    finalized_at = to_canonical((await conn.execute(text("SELECT now()"))).scalar_one())
    inputs = await load_report_inputs(conn, run_id, cutoff)
    report = registry.build(
        registry.CURRENT_BUILDER,
        inputs,
        finalized_at=finalized_at,
        cutoff_seq=cutoff,
        events_digest=digest,
    )
    markdown = registry.RENDERERS[registry.CURRENT_RENDERER](report)
    as_json = await store_json(conn, kind="report_json", value=report)
    as_md = await store_text(conn, kind="report_md", text=markdown)
    for artifact, role in ((as_json, "output.report_json"), (as_md, "output.report_md")):
        await link(
            conn, run_id=run_id, artifact_id=artifact.id, role=role, produced_by=FINALIZER_NODE
        )
    await conn.execute(
        text(
            "INSERT INTO investigation_reports (run_id, report_json_artifact_id, "
            "report_md_artifact_id, report_json_sha256, report_md_sha256, final_status, "
            "outcome, report_schema_version, builder_version, md_renderer_version) VALUES "
            "(:run, :j, :m, :js, :ms, :status, :outcome, :schema, :builder, :renderer)"
        ),
        {
            "run": run_id,
            "j": as_json.id,
            "m": as_md.id,
            "js": as_json.sha256,
            "ms": as_md.sha256,
            "status": conclusion.final_status.value,
            "outcome": conclusion.outcome.value if conclusion.outcome else None,
            "schema": report["schema_version"],
            "builder": report["builder_version"],
            "renderer": registry.CURRENT_RENDERER,
        },
    )
    step("report")

    manifest = await _manifest(
        conn, run_id, run=run, finalized_at=finalized_at, conclusion=conclusion, cutoff=cutoff,
        digest=digest, report=report, report_sha=as_json.sha256, md_sha=as_md.sha256,
    )  # fmt: skip
    stored = await store_json(conn, kind="replay_manifest", value=manifest)
    await link(
        conn, run_id=run_id, artifact_id=stored.id, role="output.manifest",
        produced_by=FINALIZER_NODE,
    )  # fmt: skip
    await conn.execute(
        text(
            "INSERT INTO replay_manifests (run_id, manifest_artifact_id, manifest_sha256, "
            "manifest_schema_version, events_cutoff_seq, events_digest) "
            "VALUES (:run, :a, :sha, :v, :cutoff, :digest)"
        ),
        {
            "run": run_id,
            "a": stored.id,
            "sha": stored.sha256,
            "v": MANIFEST_SCHEMA_VERSION,
            "cutoff": cutoff,
            "digest": digest,
        },
    )
    step("manifest")

    await conn.execute(
        text(
            "UPDATE investigation_runs SET finalized_at = CAST(:at AS TIMESTAMPTZ), "
            "events_cutoff_seq = :cutoff, "
            "error = COALESCE(CAST(:error AS JSONB), error) WHERE id = :id"
        ),
        {
            "id": run_id,
            "at": finalized_at,
            "cutoff": cutoff,
            "error": None if conclusion.error is None else json.dumps(conclusion.error),
        },
    )
    if conclusion.final_status is RunStatus.CANCELLED and current is RunStatus.RUNNING:
        await change_status(conn, run_id, RunStatus.CANCELLING)
    await change_status(conn, run_id, conclusion.final_status, outcome=conclusion.outcome)
    await emit(
        conn,
        run_id,
        EventType.REPORT_READY,
        {
            "report_url": f"/api/v1/runs/{run_id}/report",
            "outcome": conclusion.outcome.value if conclusion.outcome else None,
            "manifest_sha256": f"sha256:{stored.sha256}",
        },
    )
    step("closed")
    return Finalized(
        run_id=run_id,
        manifest_sha256=stored.sha256,
        report_json_sha256=as_json.sha256,
        report_md_sha256=as_md.sha256,
        final_status=conclusion.final_status.value,
        outcome=conclusion.outcome.value if conclusion.outcome else None,
        already=False,
    )
