"""write_report (terminal, deterministic): outcome, interim report artifacts, final status.

Phase 2 has no candidates or benchmarks, so a run with hypotheses ends
`unverified_recommendations`: diagnoses with a suggested verification, nothing verified.
"""

import uuid
from typing import Any

from langgraph.runtime import Runtime
from sqlalchemy import text

from querycure.agents.runtime import REPORT_NODE, RunContext, guarded
from querycure.agents.state import InvestigationState
from querycure.db.repositories.findings import list_findings, list_hypotheses
from querycure.domain.runs import TERMINAL_STATUSES, RunOutcome, RunStatus
from querycure.events.emitter import change_status
from querycure.evidence.store import list_evidence
from querycure.replay.artifact_store import link, store_json, store_text
from querycure.reports.interim import build_report, render_markdown


def decide(
    *,
    current: RunStatus,
    stop_reason: str | None,
    has_hypotheses: bool,
    has_no_action_evidence: bool,
) -> tuple[RunStatus, RunOutcome | None]:
    if current is RunStatus.CANCELLING or stop_reason == "cancelled":
        return RunStatus.CANCELLED, None
    if stop_reason == "failed":
        return RunStatus.FAILED, None
    if stop_reason in ("budget_exhausted", "invalid_input"):
        return RunStatus.COMPLETED, RunOutcome.INCONCLUSIVE
    if has_hypotheses:
        return RunStatus.COMPLETED, RunOutcome.UNVERIFIED_RECOMMENDATIONS
    if has_no_action_evidence:
        return RunStatus.COMPLETED, RunOutcome.NO_ACTION_NEEDED
    return RunStatus.COMPLETED, RunOutcome.INCONCLUSIVE


async def _close(
    conn: Any, run_id: uuid.UUID, current: RunStatus, final: RunStatus, outcome: RunOutcome | None
) -> None:
    if final is RunStatus.CANCELLED and current is RunStatus.RUNNING:
        await change_status(conn, run_id, RunStatus.CANCELLING)
    await change_status(conn, run_id, final, outcome=outcome)


@guarded(REPORT_NODE, terminal=True)
async def write_report(state: InvestigationState, runtime: Runtime[RunContext]) -> dict[str, Any]:
    ctx = runtime.context
    async with ctx.db().begin() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT status, outcome, usage FROM investigation_runs "
                    "WHERE id = :id FOR UPDATE"
                ),
                {"id": ctx.run_id},
            )
        ).one()
        current = RunStatus(row.status)
        if current in TERMINAL_STATUSES:
            return {"outcome": row.outcome}  # re-run after a crash: already written
        hypotheses = await list_hypotheses(conn, ctx.run_id)
        final, outcome = decide(
            current=current,
            stop_reason=state.get("stop_reason"),
            has_hypotheses=bool(hypotheses),
            has_no_action_evidence=bool(state.get("no_action_evidence")),
        )
        report = build_report(
            run_id=str(ctx.run_id),
            objective=state.get("objective", ""),
            final_status=final.value,
            outcome=outcome.value if outcome else None,
            stop_reason=state.get("stop_reason"),
            findings=await list_findings(conn, ctx.run_id),
            hypotheses=hypotheses,
            evidence=await list_evidence(conn, ctx.run_id),
            errors=state.get("errors", []),
            usage=row.usage,
            synthesis_summary=state.get("synthesis_summary", ""),
        )
        as_json = await store_json(conn, kind="report_json", value=report)
        as_md = await store_text(conn, kind="report_md", text=render_markdown(report))
        for artifact, role in ((as_json, "output.report_json"), (as_md, "output.report_md")):
            await link(
                conn, run_id=ctx.run_id, artifact_id=artifact.id, role=role, produced_by=REPORT_NODE
            )
        await _close(conn, ctx.run_id, current, final, outcome)
    return {"outcome": outcome.value if outcome else None}
