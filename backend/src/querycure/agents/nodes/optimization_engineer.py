"""Optimization Engineer (AGENT_SYSTEM §2): hypotheses → sandbox-testable candidates.

One structured LLM call per round (invocation key `optimization_engineer:<round>`, so a crash
re-run reuses the stored output). Deterministic checks (`agents/candidates.py`) remove
anything outside the sandbox policy; more than half removed retries once with the problems.
Later rounds see earlier candidates with their verdict reason codes and may not repeat them.
"""

from collections.abc import Mapping
from typing import Any

from langgraph.runtime import Runtime

from querycure.agents.agent_runner import AgentFailedError, run_agent
from querycure.agents.candidates import judge_candidates, rejection_lines, to_candidates
from querycure.agents.citations import CitationReport
from querycure.agents.claims_v2 import claim_context
from querycure.agents.fencing import Fence
from querycure.agents.outputs import CandidateSet
from querycure.agents.prompts import optimization_engineer as prompts
from querycure.agents.runtime import RunContext, guarded
from querycure.agents.state import InvestigationState, hypotheses_of
from querycure.db.repositories.optimization import insert_candidates, list_candidates
from querycure.domain.investigation import NodeError
from querycure.events.emitter import emit
from querycure.events.types import EventType
from querycure.evidence.builders import context_summary
from querycure.evidence.sanitize import clean_text
from querycure.evidence.store import list_evidence
from querycure.replay.artifact_store import get_artifact

NODE = "optimization_engineer"


async def baseline_sql(ctx: RunContext, state: InvestigationState) -> str | None:
    sha = state.get("query_sql_sha256")
    if sha is None:
        return None
    async with ctx.db().connect() as conn:
        artifact = await get_artifact(conn, sha)
    return None if artifact is None else artifact.content.decode()


def candidate_summary(c: Any) -> dict[str, Any]:
    """`candidate.created` payload: the exact SQL, never a connection detail."""
    return {
        "key": c.key,
        "round": c.round,
        "kind": c.kind,
        "addresses_hypotheses": list(c.addresses_hypotheses),
        "ddl": list(c.ddl),
        "query_sql": c.query_sql,
        "sql_sha256": c.sql_sha256,
        "expected_benefit": c.expected_benefit,
        "status": c.status,
    }


@guarded(NODE, agent="optimization_engineer")
async def optimization_engineer(
    state: InvestigationState, runtime: Runtime[RunContext]
) -> dict[str, Any]:
    ctx = runtime.context
    round = state.get("optimization_round", 0)
    sql = await baseline_sql(ctx, state)
    hypotheses = hypotheses_of(state)
    if sql is None or not hypotheses:
        return {"candidate_keys": []}
    async with ctx.db().connect() as conn:
        earlier = await list_candidates(conn, ctx.run_id)
        evidence = await list_evidence(conn, ctx.run_id)
    seen = {c.sql_sha256 for c in earlier if c.round < round}
    keys = {h.key for h in hypotheses}
    cap = ctx.guard.budget.candidates_per_round
    claims = claim_context(evidence, query_sql=sql)

    def judge(
        output: CandidateSet, kinds: Mapping[str, str]
    ) -> tuple[CandidateSet, CitationReport]:
        return judge_candidates(
            output,
            baseline=sql,
            hypothesis_keys=keys,
            seen_digests=seen,
            max_candidates=cap,
            claims=claims,
        )

    try:
        result = await run_agent(
            ctx,
            agent="optimization_engineer",
            node=NODE,
            invocation_key=f"{NODE}:{round}",
            prompt_version=prompts.PROMPT_VERSION,
            messages=prompts.messages(
                objective=state.get("objective", ""),
                sql=sql,
                tables=[t["name"] for t in (state.get("query") or {}).get("tables", [])],
                hypotheses=hypotheses,
                context_summary=context_summary(evidence),
                earlier_rounds=rejection_lines([c for c in earlier if c.round < round], {}),
                max_candidates=cap,
                fence=Fence(),
            ),
            output_type=CandidateSet,
            judge=judge,
        )
    except AgentFailedError as exc:
        error = NodeError(node=NODE, code=exc.code, message=exc.message, recoverable=True)
        await ctx.events.emit(EventType.ERROR, error.model_dump())
        return {"candidate_keys": [], "errors": [error.model_dump()]}

    proposed = to_candidates(ctx.run_id, round, result.output)
    existing = {c.key for c in earlier}
    async with ctx.db().begin() as conn:
        stored = await insert_candidates(conn, ctx.run_id, proposed)
        for c in stored:
            if c.key not in existing:
                await emit(conn, ctx.run_id, EventType.CANDIDATE_CREATED, candidate_summary(c))
    summary = clean_text(result.output.summary, 600)
    text = (
        f"Round {round + 1}: proposed {len(stored)} candidate(s). {summary}".strip()
        if stored
        else f"Round {round + 1}: no candidate passed the sandbox policy. {summary}".strip()
    )
    await ctx.events.emit(EventType.AGENT_SUMMARY, {"agent": "optimization_engineer", "text": text})
    return {"candidate_keys": [c.key for c in stored]}
