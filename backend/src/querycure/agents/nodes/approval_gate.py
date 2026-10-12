"""approval_gate (AGENT_SYSTEM §8): no sandbox DDL without a human decision.

Creates one `approval_requests` row per round carrying the exact SQL of every candidate and
its digest, moves the run to `awaiting_approval` in the same transaction as the
`approval.requested` event, and interrupts the graph. The decision endpoint (or the expiry
sweep) records the decision and queues a resume job; on resume this node re-runs from the
top, finds the decided row, and applies it to the candidates. The benchmark engine re-checks
the same row and digests before it executes anything (defense in depth).

Demo workloads may be pre-authorized when the investigation is created: the row is then
written already approved (`decided_by = pre_authorized`), so the audit trail is identical.
"""

import json
import uuid
from typing import Any

from langgraph.runtime import Runtime
from langgraph.types import interrupt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.agents.nodes.optimization_engineer import baseline_sql
from querycure.agents.runtime import RunContext, guarded
from querycure.agents.state import InvestigationState
from querycure.db.repositories.optimization import (
    ApprovalRow,
    create_approval,
    get_approval_for_round,
    list_candidates,
    set_candidate_status,
)
from querycure.domain.optimization import ApprovalCandidate, ApprovalPayload
from querycure.domain.runs import RunStatus
from querycure.events.emitter import change_status, emit
from querycure.events.types import EventType
from querycure.replay.artifact_store import get_artifact
from querycure.workloads.registry import WORKLOADS, WorkloadRef

NODE = "approval_gate"
SANDBOX_LABEL = "QueryCure sandbox (disposable clone of the demo workload, no network egress)"


async def param_sets_for(
    conn: AsyncConnection, run_id: uuid.UUID, sql: str, workload_id: str
) -> list[dict[str, Any]]:
    """The run's param sets, else the workload's own sets for this exact example query."""
    row = (
        await conn.execute(
            text(
                "SELECT a.sha256 FROM run_artifacts ra JOIN artifacts a ON a.id = ra.artifact_id "
                "WHERE ra.run_id = :id AND ra.role = 'input.param_sets'"
            ),
            {"id": run_id},
        )
    ).first()
    if row is not None:
        artifact = await get_artifact(conn, row.sha256)
        if artifact is not None:
            sets = json.loads(artifact.content)
            if isinstance(sets, list) and sets:
                return [
                    {
                        "name": s["name"],
                        "values": s["values"],
                        "edge_case": s.get("edge_case", False),
                    }
                    for s in sets
                ]
    spec = WORKLOADS[WorkloadRef.parse(workload_id).name]
    for example in spec.example_queries:
        if example.sql.strip() == sql.strip():
            return [p.model_dump() for p in example.param_sets]
    return [{"name": "default", "values": [], "edge_case": False}]


def approval_summary(row: ApprovalRow) -> dict[str, Any]:
    return {
        "approval_id": str(row.id),
        "round": row.round,
        "status": row.status,
        "decided_by": row.decided_by,
        "expires_at": row.expires_at.isoformat(),
        "candidates": [
            {"key": c.key, "kind": c.kind, "ddl": c.ddl, "query_sql": c.query_sql}
            for c in row.payload.candidates
        ],
    }


async def _owner_and_preauth(conn: AsyncConnection, run_id: uuid.UUID) -> tuple[uuid.UUID, bool]:
    row = (
        await conn.execute(
            text(
                "SELECT i.user_id, i.pre_authorize_sandbox FROM investigation_runs r "
                "JOIN investigations i ON i.id = r.investigation_id WHERE r.id = :id"
            ),
            {"id": run_id},
        )
    ).one()
    return row.user_id, bool(row.pre_authorize_sandbox)


@guarded(NODE)
async def approval_gate(state: InvestigationState, runtime: Runtime[RunContext]) -> dict[str, Any]:
    ctx = runtime.context
    round = state.get("optimization_round", 0)
    keys = set(state.get("candidate_keys") or [])
    workload_id = state.get("workload_id")
    sql = await baseline_sql(ctx, state)
    if not keys or workload_id is None or sql is None:
        return {"approval_id": None, "approval_status": None}

    async with ctx.db().begin() as conn:
        approval = await get_approval_for_round(conn, ctx.run_id, round)
        if approval is None:
            candidates = [c for c in await list_candidates(conn, ctx.run_id, round=round)]
            candidates = [c for c in candidates if c.key in keys and c.id is not None]
            user_id, pre_authorized = await _owner_and_preauth(conn, ctx.run_id)
            payload = ApprovalPayload(
                workload_id=workload_id,
                sandbox=SANDBOX_LABEL,
                baseline_query=sql,
                param_sets=await param_sets_for(conn, ctx.run_id, sql, workload_id),
                candidates=[
                    ApprovalCandidate(
                        candidate_id=c.id,  # type: ignore[arg-type]
                        key=c.key,
                        kind=c.kind,
                        ddl=list(c.ddl),
                        query_sql=c.query_sql,
                        sql_sha256=c.sql_sha256,
                        expected_benefit=c.expected_benefit,
                        risks=list(c.risks),
                    )
                    for c in candidates
                ],
            )
            approval = await create_approval(
                conn,
                run_id=ctx.run_id,
                user_id=user_id,
                round=round,
                payload=payload,
                pre_authorized=pre_authorized,
            )
            await emit(conn, ctx.run_id, EventType.APPROVAL_REQUESTED, approval_summary(approval))
            if approval.status != "pending":
                await emit(conn, ctx.run_id, EventType.APPROVAL_DECIDED, approval_summary(approval))
        if approval.status == "pending":
            status = (
                await conn.execute(
                    text("SELECT status FROM investigation_runs WHERE id = :id FOR UPDATE"),
                    {"id": ctx.run_id},
                )
            ).scalar_one()
            if RunStatus(status) is RunStatus.RUNNING:
                await change_status(conn, ctx.run_id, RunStatus.AWAITING_APPROVAL)

    if approval.status == "pending":
        # Pauses the graph here; the checkpoint survives worker restarts. On resume the node
        # runs again from the top and reads the decided row below.
        interrupt({"approval_id": str(approval.id)})

    async with ctx.db().begin() as conn:
        decided = await get_approval_for_round(conn, ctx.run_id, round)
        if decided is None:  # pragma: no cover - written above in this node
            raise RuntimeError("approval row disappeared")
        approved = set(decided.decision.approved_candidate_ids if decided.decision else [])
        ids = [c.candidate_id for c in decided.payload.candidates]
        if decided.status == "expired":
            await set_candidate_status(
                conn, ctx.run_id, ids, "expired",
                reasons=[{"code": "approval_expired", "detail": "no decision within 24 h"}],
            )  # fmt: skip
        else:
            await set_candidate_status(
                conn, ctx.run_id, [i for i in ids if i in approved], "approved"
            )
            await set_candidate_status(
                conn, ctx.run_id, [i for i in ids if i not in approved], "declined",
                reasons=[{"code": "approval_declined", "detail": "not approved for the sandbox"}],
            )  # fmt: skip
    return {"approval_id": str(decided.id), "approval_status": decided.status}
