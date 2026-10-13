"""write_report (terminal, deterministic): outcome, then `finalize_run` (report, manifest, seal).

Outcomes (AGENT_SYSTEM §12): a verified tournament winner → `verified_recommendation`; an
expired approval, or candidates benchmarked without a verified winner → `inconclusive`;
hypotheses that were never benchmarked (no Mode C, declined approval, no valid candidate) →
`unverified_recommendations`. When the deterministic materiality check finds nothing worth
optimizing, the run ends `no_action_needed` even if hypotheses exist.

Since Phase 4 the report is `report-builder@1` / `report-md@1` written by `finalize_run` in the
same transaction as the terminal status. The interim builders stay in `reports/interim.py`
(frozen) for the records of earlier runs.
"""

from typing import Any

from langgraph.runtime import Runtime
from sqlalchemy import text

from querycure.agents.runtime import REPORT_NODE, RunContext, guarded
from querycure.agents.state import InvestigationState
from querycure.db.repositories.findings import list_hypotheses
from querycure.domain.runs import TERMINAL_STATUSES, RunOutcome, RunStatus
from querycure.evidence.store import list_evidence
from querycure.replay.finalize import Conclusion, finalize_run
from querycure.reports.optimization import optimization_section


def decide(
    *,
    current: RunStatus,
    stop_reason: str | None,
    has_hypotheses: bool,
    has_no_action_evidence: bool,
    not_material: bool = False,
    winner: str | None = None,
    approval_status: str | None = None,
    benchmarked: bool = False,
) -> tuple[RunStatus, RunOutcome | None]:
    if current is RunStatus.CANCELLING or stop_reason == "cancelled":
        return RunStatus.CANCELLED, None
    if stop_reason == "failed":
        return RunStatus.FAILED, None
    if winner is not None:
        return RunStatus.COMPLETED, RunOutcome.VERIFIED_RECOMMENDATION
    if stop_reason in ("budget_exhausted", "invalid_input"):
        return RunStatus.COMPLETED, RunOutcome.INCONCLUSIVE
    if approval_status == "expired" or benchmarked:
        return RunStatus.COMPLETED, RunOutcome.INCONCLUSIVE
    if not_material and has_no_action_evidence:
        return RunStatus.COMPLETED, RunOutcome.NO_ACTION_NEEDED
    if has_hypotheses:
        return RunStatus.COMPLETED, RunOutcome.UNVERIFIED_RECOMMENDATIONS
    if has_no_action_evidence:
        return RunStatus.COMPLETED, RunOutcome.NO_ACTION_NEEDED
    return RunStatus.COMPLETED, RunOutcome.INCONCLUSIVE


@guarded(REPORT_NODE, terminal=True)
async def write_report(state: InvestigationState, runtime: Runtime[RunContext]) -> dict[str, Any]:
    """Decide the outcome from records and state, then seal the run (finalize_run)."""
    ctx = runtime.context
    async with ctx.db().begin() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT status, outcome, finalized_at FROM investigation_runs "
                    "WHERE id = :id FOR UPDATE"
                ),
                {"id": ctx.run_id},
            )
        ).one()
        current = RunStatus(row.status)
        if row.finalized_at is not None or current in TERMINAL_STATUSES:
            return {"outcome": row.outcome}  # re-run after a crash: already sealed
        hypotheses = await list_hypotheses(conn, ctx.run_id)
        materiality = state.get("materiality") or {}
        evidence = await list_evidence(conn, ctx.run_id)
        optimization = await optimization_section(conn, ctx.run_id, evidence)
        final, outcome = decide(
            current=current,
            stop_reason=state.get("stop_reason"),
            has_hypotheses=bool(hypotheses),
            has_no_action_evidence=bool(state.get("no_action_evidence")),
            not_material=materiality.get("verdict") == "not_material",
            winner=state.get("winner"),
            approval_status=state.get("approval_status"),
            benchmarked=bool(optimization and optimization["benchmarked"]),
        )
        await finalize_run(
            conn,
            ctx.run_id,
            Conclusion(
                final_status=final,
                outcome=outcome,
                stop_reason=state.get("stop_reason"),
                synthesis_summary=state.get("synthesis_summary", ""),
                materiality=materiality or None,
                no_action_evidence=list(state.get("no_action_evidence") or []),
            ),
        )
    return {"outcome": outcome.value if outcome else None}
