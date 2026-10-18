"""Supervisor: plan which analysts run, then synthesize their findings into hypotheses.

The LLM proposes; deterministic rules dispose. Analysts outside the AGENT_SYSTEM §2
eligibility rules are dropped from a plan, a failed supervisor call falls back to running
every eligible analyst, and `proposed_by` is computed from shared citations. After synthesis
the deterministic materiality check (evidence/materiality.py) caps hypotheses about a query
that is not worth optimizing; the model can neither see nor override it.
"""

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from langgraph.runtime import Runtime
from langgraph.types import Send
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.agents.agent_runner import AgentFailedError, run_agent
from querycure.agents.citations import CitationReport
from querycure.agents.claims_v2 import claim_context
from querycure.agents.fencing import Fence
from querycure.agents.outputs import HypothesisSet, judge_hypotheses
from querycure.agents.prompts import supervisor as prompts
from querycure.agents.runtime import REPORT_NODE, RunContext, guarded
from querycure.agents.state import InvestigationState, findings_of, plan_of
from querycure.db.repositories.findings import insert_hypotheses
from querycure.domain.investigation import (
    AgentName,
    Evidence,
    Finding,
    Hypothesis,
    InvestigationPlan,
    NodeError,
)
from querycure.domain.runs import ExecutionMode
from querycure.events.emitter import emit
from querycure.events.types import EventType
from querycure.evidence.builders import context_summary
from querycure.evidence.ids import keyed_id
from querycure.evidence.materiality import Materiality, assess_materiality, gate_hypotheses
from querycure.evidence.sanitize import clean_text
from querycure.evidence.store import list_evidence
from querycure.replay.artifact_store import get_artifact
from querycure.sql.fingerprint import match_key

PLAN_NODE = "supervisor_plan"
SYNTHESIS_NODE = "synthesize_hypotheses"
_CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}


def eligible_agents(state: InvestigationState) -> list[str]:
    """AGENT_SYSTEM §2 "Runs when", evaluated on state only."""
    query = state.get("query") or {}
    eligible: list[str] = []
    if query or state.get("plan_sha256"):
        eligible.append("query_analyzer")
    if query.get("tables"):
        eligible.append("index_strategist")
    caps = state.get("capabilities") or {}
    live = ExecutionMode.LIVE_INSPECTION.value in state.get("modes", [])
    if live and (caps.get("has_pg_stat_statements") or caps.get("can_read_all_stats")):
        eligible.append("workload_investigator")
    return eligible


def _no_citations(
    output: InvestigationPlan, kinds: Mapping[str, str]
) -> tuple[InvestigationPlan, CitationReport]:
    # Plans route work; they make no claims, so there is nothing to cite-check.
    return output, CitationReport(total=0, removed=0, stripped_ids=0, problems=[])


@guarded(PLAN_NODE, agent="supervisor")
async def supervisor_plan(
    state: InvestigationState, runtime: Runtime[RunContext]
) -> dict[str, Any]:
    ctx = runtime.context
    eligible = eligible_agents(state)
    if not eligible:
        error = NodeError(
            node=PLAN_NODE,
            code="NO_ANALYSTS",
            message="No analyst can run on the available inputs.",
            recoverable=False,
        )
        await ctx.events.emit(EventType.ERROR, error.model_dump())
        return {"plan": None, "errors": [error.model_dump()]}

    errors: list[dict[str, Any]] = []
    try:
        result = await run_agent(
            ctx,
            agent="supervisor",
            node=PLAN_NODE,
            invocation_key=PLAN_NODE,
            prompt_version=prompts.PLAN_PROMPT_VERSION,
            messages=prompts.plan_messages(
                objective=state.get("objective", ""),
                eligible=eligible,
                context_summary=state.get("context_summary", ""),
                fence=Fence(),
            ),
            output_type=InvestigationPlan,
            judge=_no_citations,
        )
        proposed = result.output
        chosen = [a for a in proposed.agents if a in eligible] or eligible
        plan = InvestigationPlan(
            agents=chosen,  # type: ignore[arg-type]
            focus=[clean_text(f, 200) for f in proposed.focus],
            rationale=clean_text(proposed.rationale, 1000),
        )
    except AgentFailedError as exc:
        plan = InvestigationPlan(
            agents=eligible,  # type: ignore[arg-type]
            focus=[],
            rationale=(
                "Default plan: the supervisor was unavailable, so every eligible analyst runs."
            ),
        )
        error = NodeError(node=PLAN_NODE, code=exc.code, message=exc.message, recoverable=True)
        await ctx.events.emit(EventType.ERROR, error.model_dump())
        errors.append(error.model_dump())

    await ctx.events.emit(
        EventType.AGENT_SUMMARY,
        {"agent": "supervisor", "text": "Plan: run " + ", ".join(plan.agents) + "."},
    )
    return {"plan": plan.model_dump(), "errors": errors}


def route_after_plan(state: InvestigationState) -> list[Send] | str:
    """Fan out one Send per planned analyst; stop or an empty plan goes to the report."""
    plan = plan_of(state)
    if state.get("stop_reason") is not None or plan is None:
        return REPORT_NODE
    return [Send(agent, state) for agent in plan.agents]


def _proposed_by(supporting: list[str], findings: list[Finding]) -> list[AgentName]:
    cited = set(supporting)
    agents = sorted({f.agent for f in findings if cited & set(f.evidence_ids)})
    return agents or ["supervisor"]


def rank_hypotheses(
    run_id: uuid.UUID, round: int, output: HypothesisSet, findings: list[Finding]
) -> list[Hypothesis]:
    """Stable order by confidence, then the model's own order. Keys depend on position only,
    so a reused output yields the same keys on a re-run."""
    ordered = sorted(
        enumerate(output.hypotheses), key=lambda p: (_CONFIDENCE_ORDER[p[1].confidence], p[0])
    )
    return [
        Hypothesis(
            key=keyed_id("hy", run_id, round, rank),
            rank=rank,
            statement=clean_text(draft.statement, 1000),
            category=draft.category,
            supporting_evidence=draft.supporting_evidence,
            contradicting_evidence=draft.contradicting_evidence,
            confidence=draft.confidence,
            uncertainty_notes=clean_text(draft.uncertainty_notes, 1000),
            verification_method=draft.verification_method,
            proposed_by=_proposed_by(draft.supporting_evidence, findings),
        )
        for rank, (_, draft) in enumerate(ordered, start=1)
    ]


@guarded(SYNTHESIS_NODE, agent="supervisor")
async def synthesize_hypotheses(
    state: InvestigationState, runtime: Runtime[RunContext]
) -> dict[str, Any]:
    ctx = runtime.context
    engine = ctx.db()
    findings = findings_of(state)
    async with engine.connect() as conn:
        evidence = await list_evidence(conn, ctx.run_id)
        query_key = await _query_key(conn, state, evidence)
    materiality = assess_materiality(evidence, query_key=query_key)
    if not findings:
        return {
            "hypotheses": [],
            "synthesis_summary": "",
            "no_action_evidence": _no_action(materiality),
            "materiality": materiality.model_dump(),
        }

    async with engine.connect() as conn:
        sha = state.get("query_sql_sha256")
        artifact = await get_artifact(conn, sha) if sha else None
    claims = claim_context(
        evidence, query_sql=artifact.content.decode() if artifact is not None else None
    )

    def judge(
        output: HypothesisSet, kinds: Mapping[str, str]
    ) -> tuple[HypothesisSet, CitationReport]:
        return judge_hypotheses(output, kinds, claims)

    try:
        result = await run_agent(
            ctx,
            agent="supervisor",
            node=SYNTHESIS_NODE,
            invocation_key=f"{SYNTHESIS_NODE}:0",
            prompt_version=prompts.SYNTHESIS_PROMPT_VERSION,
            messages=prompts.synthesis_messages(
                objective=state.get("objective", ""),
                findings=findings,
                context_summary=context_summary(evidence),
                fence=Fence(),
            ),
            output_type=HypothesisSet,
            judge=judge,
        )
    except AgentFailedError as exc:
        error = NodeError(node=SYNTHESIS_NODE, code=exc.code, message=exc.message, recoverable=True)
        await ctx.events.emit(EventType.ERROR, error.model_dump())
        return {
            "hypotheses": [],
            "errors": [error.model_dump()],
            "no_action_evidence": _no_action(materiality),
            "materiality": materiality.model_dump(),
        }

    hypotheses = gate_hypotheses(
        rank_hypotheses(ctx.run_id, 0, result.output, findings), materiality
    )
    async with engine.begin() as conn:
        new = set(await insert_hypotheses(conn, ctx.run_id, 0, hypotheses))
        for h in hypotheses:
            if h.key in new:
                await emit(conn, ctx.run_id, EventType.HYPOTHESIS_CREATED, h.model_dump())
    summary = clean_text(result.output.summary, 600)
    if summary:
        await ctx.events.emit(EventType.AGENT_SUMMARY, {"agent": "supervisor", "text": summary})
    if materiality.verdict == "not_material":
        await ctx.events.emit(
            EventType.AGENT_SUMMARY,
            {
                "agent": "supervisor",
                "text": "Not worth optimizing: " + " ".join(materiality.reasons),
            },
        )
    no_action = result.output.no_action_evidence if not hypotheses else []
    return {
        "hypotheses": [h.model_dump() for h in hypotheses],
        "synthesis_summary": summary,
        "no_action_evidence": list(dict.fromkeys([*no_action, *_no_action(materiality)])),
        "materiality": materiality.model_dump(),
    }


def _no_action(materiality: Materiality) -> list[str]:
    return materiality.evidence_ids if materiality.verdict == "not_material" else []


async def _query_key(
    conn: AsyncConnection, state: InvestigationState, evidence: Sequence[Evidence]
) -> str | None:
    """Only needed to match `pg_stat_statements` rows, which only live runs collect."""
    sha = state.get("query_sql_sha256")
    if sha is None or not any(e.kind == "workload_stat" for e in evidence):
        return None
    artifact = await get_artifact(conn, sha)
    return None if artifact is None else match_key(artifact.content.decode())
