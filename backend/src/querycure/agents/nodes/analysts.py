"""The three tool-using analysts (AGENT_SYSTEM §2), built from one factory.

Each runs in parallel after the supervisor's fan-out, writes only its own findings, and
continues the run on failure (the supervisor synthesizes from whatever analysts produced).
"""

import contextlib
import uuid
from collections.abc import AsyncIterator, Mapping
from types import ModuleType
from typing import Any

from langgraph.runtime import Runtime

from querycure.agents.agent_runner import AgentFailedError, run_tool_agent
from querycure.agents.fencing import Fence
from querycure.agents.prompts import (
    index_strategist,
    query_analyzer,
    workload_investigator,
)
from querycure.agents.prompts.analyst import analyst_messages
from querycure.agents.runtime import NodeFn, RunContext, guarded
from querycure.agents.services import Inspector
from querycure.agents.state import InvestigationState, plan_of
from querycure.agents.tools import evidence_tools as et
from querycure.agents.tools import workload_tools as wt
from querycure.agents.tools.base import Tool, ToolContext, describe_tools
from querycure.core.errors import QueryCureError
from querycure.db.repositories.findings import insert_findings
from querycure.domain.investigation import AgentName, Finding, NodeError
from querycure.domain.runs import ExecutionMode
from querycure.events.emitter import emit
from querycure.events.types import EventType
from querycure.evidence.builders import context_summary
from querycure.evidence.ids import keyed_id
from querycure.evidence.sanitize import clean_text
from querycure.evidence.store import list_evidence
from querycure.replay.artifact_store import get_artifact


def _tools(*tools: Tool) -> dict[str, Tool]:
    return {t.name: t for t in tools}


ALLOWLISTS: dict[AgentName, dict[str, Tool]] = {
    "query_analyzer": _tools(
        et.GET_PLAN_NODE, et.GET_TABLE_STATS, et.GET_COLUMN_STATS, et.GET_SCHEMA_OBJECT
    ),
    "index_strategist": _tools(et.LIST_INDEXES, et.GET_COLUMN_STATS, et.ESTIMATE_INDEX_SIZE),
    "workload_investigator": _tools(
        wt.GET_STATEMENT_STATS,
        wt.GET_ACTIVITY_SNAPSHOT,
        wt.GET_LOCK_SNAPSHOT,
        wt.GET_TABLE_IO_STATS,
    ),
}
PROMPTS: dict[AgentName, ModuleType] = {
    "query_analyzer": query_analyzer,
    "index_strategist": index_strategist,
    "workload_investigator": workload_investigator,
}


@contextlib.asynccontextmanager
async def _maybe_inspector(
    ctx: RunContext, state: InvestigationState
) -> AsyncIterator[Inspector | None]:
    """The gateway in Mode B; None offline or when it cannot be opened (tools then say so)."""
    connection_id = state.get("connection_id")
    live = ExecutionMode.LIVE_INSPECTION.value in state.get("modes", [])
    if not live or connection_id is None or ctx.inspectors is None:
        yield None
        return
    try:
        opened = ctx.inspectors.open(uuid.UUID(str(connection_id)))
        inspector = await opened.__aenter__()
    except QueryCureError:
        yield None
        return
    try:
        yield inspector
    finally:
        await opened.__aexit__(None, None, None)


def make_analyst(agent: AgentName, *, tools: Mapping[str, Tool] | None = None) -> NodeFn:
    allowlist = dict(tools if tools is not None else ALLOWLISTS[agent])
    prompt = PROMPTS[agent]

    @guarded(agent, agent=agent)
    async def analyst(state: InvestigationState, runtime: Runtime[RunContext]) -> dict[str, Any]:
        ctx = runtime.context
        engine = ctx.db()
        async with engine.connect() as conn:
            evidence = await list_evidence(conn, ctx.run_id)
            sql = None
            if sha := state.get("query_sql_sha256"):
                art = await get_artifact(conn, sha)
                sql = art.content.decode() if art is not None else None
        plan = plan_of(state)
        messages = analyst_messages(
            role=prompt.ROLE,
            task=prompt.TASK,
            objective=state.get("objective", ""),
            focus=plan.focus if plan is not None else [],
            sql=sql,
            context_summary=context_summary(evidence),
            tools=describe_tools(allowlist),
            max_tools=ctx.guard.budget.tool_calls_per_agent,
            fence=Fence(),
        )
        try:
            async with _maybe_inspector(ctx, state) as inspector:
                result = await run_tool_agent(
                    ToolContext(run=ctx, state=state, inspector=inspector),
                    agent=agent,
                    node=agent,
                    invocation_key=f"{agent}:0",
                    prompt_version=prompt.PROMPT_VERSION,
                    messages=messages,
                    tools=allowlist,
                )
        except AgentFailedError as exc:
            error = NodeError(node=agent, code=exc.code, message=exc.message, recoverable=True)
            await ctx.events.emit(EventType.ERROR, {**error.model_dump(), "details": exc.details})
            return {"errors": [error.model_dump()]}

        findings = [
            (
                keyed_id("fd", ctx.run_id, agent, i),
                Finding(
                    agent=agent,
                    title=clean_text(d.title, 200),
                    detail=clean_text(d.detail, 2000),
                    severity=d.severity,
                    evidence_ids=d.evidence_ids,
                ),
            )
            for i, d in enumerate(result.output.findings)
        ]
        async with engine.begin() as conn:
            new = set(await insert_findings(conn, ctx.run_id, findings))
            for key, finding in findings:
                if key in new:
                    await emit(
                        conn,
                        ctx.run_id,
                        EventType.FINDING_CREATED,
                        {"key": key, **finding.model_dump()},
                    )
        summary = clean_text(result.output.summary, 600)
        if summary:
            await ctx.events.emit(EventType.AGENT_SUMMARY, {"agent": agent, "text": summary})
        return {"findings": [f.model_dump() for _, f in findings]}

    return analyst


query_analyzer_node = make_analyst("query_analyzer")
index_strategist_node = make_analyst("index_strategist")
workload_investigator_node = make_analyst("workload_investigator")
