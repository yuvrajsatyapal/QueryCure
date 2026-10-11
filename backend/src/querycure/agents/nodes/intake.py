"""intake (deterministic): load the run's inputs, validate them, record query facts."""

from typing import Any

from langgraph.runtime import Runtime

from querycure.agents.runtime import RunContext, guarded
from querycure.agents.state import InvestigationState
from querycure.core.errors import SqlNotAllowedError, SqlParseError
from querycure.db.repositories.investigations import RunInputs, get_run_inputs
from querycure.domain.investigation import NodeError
from querycure.domain.runs import ExecutionMode
from querycure.events.types import EventType
from querycure.evidence.builders import query_evidence
from querycure.evidence.store import record_evidence
from querycure.replay.artifact_store import get_artifact
from querycure.sql.validator import ValidatedQuery, validate_select

NODE = "intake"


def _problems(inputs: RunInputs, has_query: bool) -> list[str]:
    problems: list[str] = []
    has_plan = "input.plan" in inputs.artifacts
    live = ExecutionMode.LIVE_INSPECTION.value in inputs.modes
    if not has_query and not has_plan:
        problems.append("Provide a query, an uploaded plan, or both.")
    if live and inputs.connection_id is None:
        problems.append("Live inspection needs a connection.")
    if live and not has_query:
        problems.append("Live inspection needs the query text.")
    return problems


def query_state(sha256: str, validated: ValidatedQuery) -> dict[str, Any]:
    meta = validated.metadata
    return {
        "sha256": sha256,
        "fingerprint": validated.fingerprint.digest,
        "statement_type": validated.statement_type,
        "tables": [t.model_dump() for t in meta.tables],
        "columns": [c.model_dump() for c in meta.columns],
        "order_by": meta.order_by,
        "limit": meta.limit,
        "parameter_count": meta.parameter_count,
    }


@guarded(NODE)
async def intake(state: InvestigationState, runtime: Runtime[RunContext]) -> dict[str, Any]:
    ctx = runtime.context
    engine = ctx.db()
    async with engine.connect() as conn:
        inputs = await get_run_inputs(conn, ctx.run_id)
        query_sha = inputs.artifacts.get("input.query")
        query_artifact = await get_artifact(conn, query_sha) if query_sha else None

    update: dict[str, Any] = {
        "investigation_id": str(inputs.investigation_id),
        "run_id": str(inputs.run_id),
        "objective": inputs.objective,
        "modes": inputs.modes,
        "connection_id": str(inputs.connection_id) if inputs.connection_id else None,
        "workload_id": inputs.workload_id,
        "query_sql_sha256": query_sha,
        "plan_sha256": inputs.artifacts.get("input.plan"),
        "schema_sha256": inputs.artifacts.get("input.schema"),
        "query": None,
    }
    problems = _problems(inputs, query_artifact is not None)
    validated: ValidatedQuery | None = None
    if query_artifact is not None:
        try:
            validated = validate_select(query_artifact.content.decode())
        except (SqlNotAllowedError, SqlParseError) as exc:
            reasons = "; ".join(str(d.get("message", "")) for d in exc.details if d.get("message"))
            problems.append(f"{exc.message} ({reasons})" if reasons else exc.message)

    if problems:
        errors = [
            NodeError(node=NODE, code="INVALID_INPUT", message=p, recoverable=False).model_dump()
            for p in problems
        ]
        for error in errors:
            await ctx.events.emit(EventType.ERROR, error)
        return {**update, "stop_reason": "invalid_input", "errors": errors}

    if validated is None or query_sha is None:
        return {**update, "evidence_ids": []}
    ids = await record_evidence(
        engine, ctx.run_id, query_evidence(ctx.run_id, query_sha, validated)
    )
    return {**update, "query": query_state(query_sha, validated), "evidence_ids": ids}
