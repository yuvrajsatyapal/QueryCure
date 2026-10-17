"""Benchmark Auditor (AGENT_SYSTEM §2, ADR-0009): deterministic checks, then an LLM narrative.

Runs after every experiment. Order:
1. deterministic checks over persisted records (`audit/checks.py`): a failed check moves a
   verified candidate to inconclusive;
2. one structured LLM call (`benchmark_auditor:<round>`) that may add cited concerns; a
   `downgrade` concern with a valid citation moves a verified candidate to inconclusive;
3. one `verification_results` row per candidate (append-only; the table refuses upgrades),
   candidate statuses for downgraded arms, and `verification.completed` events.

The narrative is optional: if the model fails, the audit is recorded as `deterministic_only`.
If the run's budget runs out or it is cancelled during the call, the deterministic audit is
still recorded before the stop propagates. Nothing here can verify or reject a candidate.
"""

from typing import Any

from langgraph.runtime import Runtime

from querycure.agents.agent_runner import AgentFailedError, run_agent
from querycure.agents.citations import CitationReport
from querycure.agents.claims import ActionRef, claim_context, index_columns
from querycure.agents.fencing import Fence
from querycure.agents.nodes.optimization_engineer import baseline_sql
from querycure.agents.nodes.run_experiment import experiment_id_for
from querycure.agents.outputs import AuditNarrative, judge_audit
from querycure.agents.prompts import benchmark_auditor as prompts
from querycure.agents.runtime import RunContext, guarded
from querycure.agents.state import InvestigationState
from querycure.audit.checks import AuditInputs, audit_experiment, pick_winner
from querycure.audit.loader import AuditUnavailable, load_audit_inputs
from querycure.core.errors import BudgetExhaustedError, RunCancelledError
from querycure.db.repositories.optimization import set_candidate_status
from querycure.db.repositories.verification import insert_verification, list_verifications
from querycure.domain.audit import (
    VERIFIED_VERDICTS,
    AuditAssessment,
    AuditConcern,
    CandidateAudit,
    audited,
)
from querycure.domain.investigation import NodeError
from querycure.events.emitter import emit
from querycure.events.types import EventType
from querycure.evidence.builders import context_summary
from querycure.evidence.sanitize import clean_text
from querycure.evidence.store import list_evidence

NODE = "benchmark_auditor"
_AUDITED_KINDS = ("benchmark_metric", "correctness_check")


def candidate_lines(inputs: AuditInputs, assessment: AuditAssessment) -> list[str]:
    arms = {c.arm: c for c in inputs.config.candidates}
    rules = {v.arm: v for v in inputs.result.verdicts}
    lines = []
    for audit in assessment.candidates:
        arm = arms[audit.arm]
        sql = " ; ".join(arm.ddl) if arm.ddl else (arm.query or "")
        reasons = ", ".join(r.code for r in rules[audit.arm].reasons) or "none"
        checks = "; ".join(f"{c.name}={c.status} ({c.detail})" for c in audit.checks)
        lines.append(
            f"- {audit.arm} {arm.kind}: {sql}\n  engine verdict: {audit.engine_verdict} "
            f"(rule reasons: {reasons}); after deterministic checks: {audit.verdict}\n"
            f"  checks: {checks}"
        )
    return lines


def audit_actions(inputs: AuditInputs, assessment: AuditAssessment) -> list[ActionRef]:
    """What each arm changes and whether it stands verified after the deterministic checks:
    the narrative may only recommend a change that does (ADR-0026)."""
    verdicts = {a.arm: a.verdict for a in assessment.candidates}
    return [
        ActionRef(
            arm=arm.arm,
            kind=arm.kind,
            columns=frozenset().union(*(index_columns(d) for d in arm.ddl)),
            verified=verdicts.get(arm.arm) in VERIFIED_VERDICTS,
        )
        for arm in inputs.config.candidates
    ]


def apply_concerns(
    assessment: AuditAssessment, concerns: list[AuditConcern]
) -> list[CandidateAudit]:
    """Downgrade concerns only ever move a verified arm to inconclusive."""
    out = []
    for audit in assessment.candidates:
        mine = [c for c in concerns if c.arm == audit.arm and c.severity == "downgrade"]
        verdict = audit.verdict
        reasons = list(audit.downgrade_reasons)
        if mine and verdict in VERIFIED_VERDICTS:
            verdict = audited(verdict, doubt=True)
            reasons += [f"auditor: {clean_text(c.text, 300)}" for c in mine]
        out.append(audit.model_copy(update={"verdict": verdict, "downgrade_reasons": reasons}))
    return out


def _round_verification(audits: list[CandidateAudit], winner: str | None) -> str:
    if winner is not None:
        return next(a.verdict for a in audits if a.arm == winner)
    if audits and all(a.verdict == "rejected" for a in audits):
        return "rejected"
    return "inconclusive"


async def _narrative(
    ctx: RunContext,
    state: InvestigationState,
    inputs: AuditInputs,
    assessment: AuditAssessment,
) -> AuditNarrative:
    sql = await baseline_sql(ctx, state) or inputs.config.baseline_query
    async with ctx.db().connect() as conn:
        everything = await list_evidence(conn, ctx.run_id)
    evidence = [e for e in everything if e.kind in _AUDITED_KINDS]
    arms = frozenset(c.arm for c in assessment.candidates)
    claims = claim_context(
        everything,
        query_sql=sql,
        actions=audit_actions(inputs, assessment),
        verdicts={a.arm: a.verdict for a in assessment.candidates},
    )

    def judge(output: AuditNarrative, kinds: Any) -> tuple[AuditNarrative, CitationReport]:
        return judge_audit(output, kinds, arms, claims)

    result = await run_agent(
        ctx,
        agent="benchmark_auditor",
        node=NODE,
        invocation_key=f"{NODE}:{assessment.round}",
        prompt_version=prompts.PROMPT_VERSION,
        messages=prompts.messages(
            sql=sql,
            candidates=candidate_lines(inputs, assessment),
            evidence=context_summary(evidence),
            fence=Fence(),
        ),
        output_type=AuditNarrative,
        judge=judge,
    )
    return result.output


@guarded(NODE, agent="benchmark_auditor")
async def benchmark_auditor(
    state: InvestigationState, runtime: Runtime[RunContext]
) -> dict[str, Any]:
    ctx = runtime.context
    if state.get("verification") not in (
        "verified",
        "verified_with_noise_warning",
        "rejected",
        "inconclusive",
    ):
        return {}  # failed or not run: nothing to audit
    experiment_id = experiment_id_for(ctx.run_id, state.get("optimization_round", 0))
    async with ctx.db().connect() as conn:
        try:
            inputs, _ = await load_audit_inputs(conn, ctx.run_id, experiment_id)
        except AuditUnavailable:
            return {}
        stored = await list_verifications(conn, ctx.run_id, experiment_id=experiment_id)
    assessment = audit_experiment(inputs)
    if stored:  # re-run after a crash: the recorded audit stands
        verdicts = {r.candidate_key: r.verdict for r in stored}
        audits = [
            a.model_copy(update={"verdict": verdicts[a.arm]})
            for a in assessment.candidates
            if a.arm in verdicts
        ]
        winner = pick_winner(inputs.result, inputs.replication, verdicts)
        return {"winner": winner, "verification": _round_verification(audits, winner)}

    narrative: AuditNarrative | None = None
    note: str | None = None
    stop: BaseException | None = None
    try:
        narrative = await _narrative(ctx, state, inputs, assessment)
    except AgentFailedError as exc:
        note = f"The auditor narrative is unavailable ({exc.code}); deterministic checks only."
        error = NodeError(node=NODE, code=exc.code, message=exc.message[:500], recoverable=True)
        await ctx.events.emit(EventType.ERROR, error.model_dump())
    except (BudgetExhaustedError, RunCancelledError) as exc:
        note = "The auditor narrative was skipped: the run stopped; deterministic checks only."
        stop = exc

    concerns = [
        AuditConcern(
            arm=c.arm,
            severity=c.severity,
            text=clean_text(c.text, 600),
            evidence_ids=c.evidence_ids,
        )
        for c in (narrative.concerns if narrative else [])
        if c.evidence_ids
    ]
    audits = apply_concerns(assessment, concerns)
    verdicts = {a.arm: a.verdict for a in audits}
    winner = pick_winner(inputs.result, inputs.replication, verdicts)
    summary = clean_text(narrative.summary, 800) if narrative else (note or "")
    stats: dict[str, list[dict[str, Any]]] = {}
    for s in inputs.result.stats:
        stats.setdefault(s.arm, []).append(s.model_dump(mode="json"))
    rules = {v.arm: v for v in inputs.result.verdicts}
    async with ctx.db().begin() as conn:
        for audit in audits:
            if audit.candidate_id is None:
                continue
            downgraded = audit.verdict != audit.engine_verdict
            reasons = [r.model_dump() for r in rules[audit.arm].reasons]
            if downgraded:
                reasons += [
                    {"code": "audit_downgrade", "detail": d[:300]} for d in audit.downgrade_reasons
                ]
            await insert_verification(
                conn,
                ctx.run_id,
                {
                    "experiment_id": experiment_id,
                    "candidate_id": audit.candidate_id,
                    "candidate_key": audit.arm,
                    "round": assessment.round,
                    "engine_verdict": audit.engine_verdict,
                    "verdict": audit.verdict,
                    "reasons": reasons,
                    "stats": stats.get(audit.arm, []),
                    "checks": [c.model_dump() for c in audit.checks],
                    "auditor_status": "completed" if narrative else "deterministic_only",
                    "auditor_notes": summary or None,
                    "auditor_concerns": [c.model_dump() for c in concerns if c.arm == audit.arm],
                    "auditor_prompt_version": prompts.PROMPT_VERSION if narrative else None,
                    "auditor_downgraded": downgraded,
                },
            )
            if downgraded:
                await set_candidate_status(
                    conn, ctx.run_id, [audit.candidate_id], "inconclusive", reasons=reasons
                )
            await emit(
                conn,
                ctx.run_id,
                EventType.VERIFICATION_COMPLETED,
                {
                    "experiment_id": str(experiment_id),
                    "candidate_key": audit.arm,
                    "verdict": audit.verdict,
                    "gate": None,
                    "reasons": reasons,
                    "audit": {
                        "engine_verdict": audit.engine_verdict,
                        "downgraded": downgraded,
                        "failed_checks": [c.name for c in audit.checks if c.status == "fail"],
                        "warned_checks": [c.name for c in audit.checks if c.status == "warn"],
                    },
                },
            )
    downgraded_arms = [a.arm for a in audits if a.verdict != a.engine_verdict]
    text = (
        "Audit: "
        + (
            f"downgraded {', '.join(downgraded_arms)} to inconclusive. "
            if downgraded_arms
            else "no verdict changed. "
        )
        + summary
    )
    await ctx.events.emit(
        EventType.AGENT_SUMMARY, {"agent": "benchmark_auditor", "text": text[:600].strip()}
    )
    if stop is not None:
        raise stop
    return {"winner": winner, "verification": _round_verification(audits, winner)}
