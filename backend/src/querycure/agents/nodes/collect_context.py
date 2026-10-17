"""collect_context (deterministic): plan, schema and statistics evidence for the analysts.

Uploaded plans/DDL become `imported` evidence. In Mode B the hardened gateway supplies a
plain EXPLAIN and a redacted schema snapshot (`measured`); a Mode C run on a demo workload
gets the same from a throwaway sandbox clone (`agents/services.sandbox_inspector`).
A live failure is recorded as `tool_error` evidence and the run continues on what it has
(ARCHITECTURE failure table).
"""

import uuid
from contextlib import AbstractAsyncContextManager
from typing import Any

from langgraph.runtime import Runtime

from querycure.agents.runtime import RunContext, guarded
from querycure.agents.services import Inspector, sandbox_inspector
from querycure.agents.state import InvestigationState
from querycure.core.errors import QueryCureError
from querycure.domain.investigation import Evidence
from querycure.domain.runs import ExecutionMode
from querycure.evidence.builders import (
    StatsOrigin,
    context_summary,
    declared_schema_evidence,
    plan_evidence,
    schema_evidence,
)
from querycure.evidence.ids import evidence_id
from querycure.evidence.store import list_evidence, record_evidence
from querycure.plans.metrics import compute_metrics
from querycure.plans.parser import parse_plan
from querycure.replay.artifact_store import get_artifact, link, store_json
from querycure.sql.ddl import DeclaredSchema
from querycure.sql.validator import TableRef

NODE = "collect_context"


def _tool_error(run_id: uuid.UUID, step: str, exc: QueryCureError) -> Evidence:
    return Evidence(
        id=evidence_id(run_id, "tool_error", None, f"#{step}"),
        kind="tool_error",
        artifact_sha256=None,
        locator=f"#{step}",
        summary=f"Live inspection step '{step}' failed ({exc.code}); continuing without it",
        data={"step": step, "code": exc.code},
        provenance="measured",
    )


def _opener(
    ctx: RunContext, state: InvestigationState
) -> tuple[AbstractAsyncContextManager[Inspector], StatsOrigin] | None:
    """Mode B: the user's connection. Mode C only: a throwaway clone of the demo workload,
    whose cumulative statistics counters were reset by cloning (E2E audit O3)."""
    modes = state.get("modes", [])
    if ExecutionMode.LIVE_INSPECTION.value in modes:
        if ctx.inspectors is None or state.get("connection_id") is None:
            return None
        return ctx.inspectors.open(uuid.UUID(str(state["connection_id"]))), "live"
    workload = state.get("workload_id")
    if ExecutionMode.SANDBOX_BENCHMARK.value in modes and workload:
        if ctx.context_inspector is not None:
            opened: AbstractAsyncContextManager[Inspector] = ctx.context_inspector(
                workload, ctx.run_id
            )
            return opened, "sandbox_clone"
        if ctx.sandbox is not None:
            clone = sandbox_inspector(ctx.sandbox, workload_id=workload, run_id=ctx.run_id)
            return clone, "sandbox_clone"
    return None


async def _live(ctx: RunContext, state: InvestigationState, sql: str) -> tuple[list[Evidence], Any]:
    engine = ctx.db()
    opened = _opener(ctx, state)
    if opened is None:
        return [], None
    opener, origin = opened
    query = state.get("query") or {}
    tables = [TableRef.model_validate(t) for t in query.get("tables", [])]
    items: list[Evidence] = []
    capabilities = None
    try:
        async with opener as gateway:
            capabilities = (await gateway.capabilities()).model_dump(mode="json")
            try:
                explained = await gateway.explain(sql)
                async with engine.begin() as conn:
                    plan_art = await store_json(conn, kind="plan", value=explained.plan_document)
                    await link(
                        conn,
                        run_id=ctx.run_id,
                        artifact_id=plan_art.id,
                        role="context.plan",
                        produced_by=NODE,
                    )
                tree = parse_plan(explained.plan_document)
                items += plan_evidence(
                    ctx.run_id, plan_art.sha256, tree, compute_metrics(tree), provenance="measured"
                )
            except QueryCureError as exc:
                items.append(_tool_error(ctx.run_id, "explain", exc))
            if tables:
                try:
                    snapshot = await gateway.schema_snapshot(tables)
                    async with engine.begin() as conn:
                        snap_art = await store_json(
                            conn, kind="schema_snapshot", value=snapshot.model_dump(mode="json")
                        )
                        await link(
                            conn,
                            run_id=ctx.run_id,
                            artifact_id=snap_art.id,
                            role="context.schema_snapshot",
                            produced_by=NODE,
                        )
                    items += schema_evidence(ctx.run_id, snap_art.sha256, snapshot, origin=origin)
                except QueryCureError as exc:
                    items.append(_tool_error(ctx.run_id, "schema_snapshot", exc))
    except QueryCureError as exc:
        items.append(_tool_error(ctx.run_id, "connect", exc))
    return items, capabilities


@guarded(NODE)
async def collect_context(
    state: InvestigationState, runtime: Runtime[RunContext]
) -> dict[str, Any]:
    ctx = runtime.context
    engine = ctx.db()
    items: list[Evidence] = []
    sql: str | None = None
    async with engine.connect() as conn:
        if plan_sha := state.get("plan_sha256"):
            art = await get_artifact(conn, plan_sha)
            if art is not None:
                tree = parse_plan(art.content)
                items += plan_evidence(
                    ctx.run_id, plan_sha, tree, compute_metrics(tree), provenance="imported"
                )
        if schema_sha := state.get("schema_sha256"):
            art = await get_artifact(conn, schema_sha)
            if art is not None:
                declared = DeclaredSchema.model_validate_json(art.content)
                items += declared_schema_evidence(ctx.run_id, schema_sha, declared)
        if query_sha := state.get("query_sql_sha256"):
            art = await get_artifact(conn, query_sha)
            sql = art.content.decode() if art is not None else None

    capabilities = None
    if sql is not None:
        live_items, capabilities = await _live(ctx, state, sql)
        items += live_items

    ids = await record_evidence(engine, ctx.run_id, items)
    async with engine.connect() as conn:
        everything = await list_evidence(conn, ctx.run_id)
    return {
        "evidence_ids": ids,
        "capabilities": capabilities,
        "context_summary": context_summary(everything),
    }
