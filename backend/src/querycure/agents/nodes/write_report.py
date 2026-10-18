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

from collections.abc import Mapping, Sequence
from typing import Any

from langgraph.runtime import Runtime
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.agents.claims_v2 import CHECKER_VERSION, action_refs, claim_context, filter_text
from querycure.agents.runtime import REPORT_NODE, RunContext, guarded
from querycure.agents.state import InvestigationState
from querycure.core.logging import get_logger
from querycure.db.repositories.agents import call_outcomes
from querycure.db.repositories.findings import list_hypotheses
from querycure.db.repositories.optimization import list_candidates
from querycure.domain.investigation import Evidence, NodeError
from querycure.domain.runs import TERMINAL_STATUSES, RunOutcome, RunStatus
from querycure.events.emitter import emit
from querycure.events.types import EventType
from querycure.evidence.store import list_evidence
from querycure.replay.artifact_store import get_artifact
from querycure.replay.finalize import Conclusion, finalize_run
from querycure.reports.optimization import optimization_section

log = get_logger(__name__)


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
        summary, narrative_check = await _reconcile_summary(
            conn, ctx, state, evidence, str(state.get("synthesis_summary") or "")
        )
        error = model_failure(await call_outcomes(conn, ctx.run_id)) if outcome else None
        if error is not None:
            await emit(
                conn,
                ctx.run_id,
                EventType.ERROR,
                NodeError(
                    node=REPORT_NODE, code=error["code"], message=error["message"],
                    recoverable=False,
                ).model_dump(),
            )  # fmt: skip
        await finalize_run(
            conn,
            ctx.run_id,
            Conclusion(
                final_status=final,
                outcome=outcome,
                stop_reason=state.get("stop_reason"),
                synthesis_summary=summary,
                materiality=materiality or None,
                no_action_evidence=list(state.get("no_action_evidence") or []),
                error=error,
                narrative_check=narrative_check,
            ),
        )
    return {"outcome": outcome.value if outcome else None}


_CODE_LABELS = {
    "LLM_INVALID_OUTPUT": "invalid structured output",
    "LLM_TIMEOUT": "timeout",
    "LLM_RATE_LIMITED": "rate limited",
    "LLM_CONNECTION_ERROR": "connection failure",
    "LLM_PROVIDER_ERROR": "provider error",
    "LLM_MODEL_UNAVAILABLE": "model unavailable",
    "LLM_AUTH_FAILED": "key rejected",
    "LLM_REQUEST_REJECTED": "request rejected",
    "LLM_FREE_QUOTA_EXHAUSTED": "free allowance used up",
    "LLM_PAID_USAGE_BLOCKED": "paid usage blocked",
    "LLM_CIRCUIT_OPEN": "skipped after repeated failures",
    "UNCITED_CLAIMS": "uncited claims",
}


def model_failure(outcomes: Mapping[str, int]) -> dict[str, Any] | None:
    """Run-level reason when the run used the model but no call produced usable output
    (E2E audit O7): otherwise a provider outage reads as a plain `inconclusive`."""
    if not outcomes or outcomes.get("succeeded", 0) or outcomes.get("tool_call", 0):
        return None
    counts = sorted(outcomes.items(), key=lambda kv: (-kv[1], kv[0]))
    described = ", ".join(f"{n} {_CODE_LABELS.get(code, code.lower())}" for code, n in counts)
    total = sum(outcomes.values())
    return {
        "code": "MODEL_UNAVAILABLE",
        "message": (
            f"No model call produced usable output ({total} attempt(s): {described}), so "
            "nothing was diagnosed. Try again later or configure another free model."
        ),
        "details": [{"code": code, "count": n} for code, n in counts],
    }


async def _reconcile_summary(
    conn: AsyncConnection,
    ctx: RunContext,
    state: InvestigationState,
    evidence: Sequence[Evidence],
    summary: str,
) -> tuple[str, dict[str, Any] | None]:
    """The synthesis summary is written before any benchmark. Once candidates have verdicts,
    a sentence that recommends a change the benchmark did not verify, or states a figure the
    measurements do not show, is removed (ADR-0026). Nothing is added or reworded."""
    if not summary or not any(e.kind == "benchmark_metric" for e in evidence):
        return summary, None
    candidates = await list_candidates(conn, ctx.run_id)
    sha = state.get("query_sql_sha256")
    artifact = await get_artifact(conn, sha) if sha else None
    claims = claim_context(
        evidence,
        query_sql=artifact.content.decode() if artifact is not None else None,
        actions=action_refs(candidates),
        verdicts={c.key: c.status for c in candidates},
    )
    out = filter_text(summary, claims)
    if not out.removed:
        return summary, None
    log.warning("summary_claims_removed", run_id=str(ctx.run_id), removed=len(out.removed))
    return out.text, {
        "removed_sentences": out.removed,
        "problems": out.problems,
        "checker": CHECKER_VERSION,
    }
