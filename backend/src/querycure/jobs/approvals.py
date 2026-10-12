"""Approval decisions and expiry (AGENT_SYSTEM §8). Shared by the API and the worker sweep.

A decision (or expiry) is one transaction: the approval row leaves `pending` exactly once,
the time the run spent waiting is added to `waiting_seconds` (so it never counts against the
wall-clock budget), the run moves `awaiting_approval → queued` with its event, and a
`run_resume` job is queued. The worker then resumes the interrupted graph, whose
approval_gate reads the decision from the row.
"""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from querycure.core.logging import get_logger
from querycure.db.repositories.optimization import (
    ApprovalRow,
    decide_approval,
    expire_due_approvals,
    get_approval_for_round,
)
from querycure.domain.optimization import ApprovalDecision, ApprovalStatus
from querycure.domain.runs import RunStatus
from querycure.events.emitter import change_status, emit
from querycure.events.types import EventType
from querycure.jobs import queue

log = get_logger(__name__)


def decision_event(row: ApprovalRow) -> dict[str, object]:
    return {
        "approval_id": str(row.id),
        "round": row.round,
        "status": row.status,
        "decided_by": row.decided_by,
        "approved_candidate_ids": [
            str(i) for i in (row.decision.approved_candidate_ids if row.decision else [])
        ],
    }


async def _resume(conn: AsyncConnection, row: ApprovalRow) -> None:
    status = (
        await conn.execute(
            text("SELECT status FROM investigation_runs WHERE id = :id FOR UPDATE"),
            {"id": row.run_id},
        )
    ).scalar_one()
    await emit(conn, row.run_id, EventType.APPROVAL_DECIDED, decision_event(row))
    if RunStatus(status) is not RunStatus.AWAITING_APPROVAL:
        return  # e.g. cancelled meanwhile: nothing to resume
    await conn.execute(
        text(
            "UPDATE investigation_runs SET waiting_seconds = waiting_seconds + "
            "greatest(extract(epoch FROM now() - :since), 0) WHERE id = :id"
        ),
        {"id": row.run_id, "since": row.created_at},
    )
    await change_status(conn, row.run_id, RunStatus.QUEUED)
    await queue.enqueue(
        conn,
        kind="run_resume",
        run_id=row.run_id,
        payload={"approval_id": str(row.id)},
        dedupe_key=f"run_resume:{row.run_id}:{row.id}",
    )


async def record_decision(
    conn: AsyncConnection,
    row: ApprovalRow,
    *,
    status: ApprovalStatus,
    decided_by: str,
    decision: ApprovalDecision,
) -> ApprovalRow | None:
    """None when the approval was no longer pending (a concurrent decision or expiry won)."""
    if not await decide_approval(
        conn, approval_id=row.id, status=status, decided_by=decided_by, decision=decision
    ):
        return None
    decided = await get_approval_for_round(conn, row.run_id, row.round)
    if decided is None:  # pragma: no cover
        return None
    await _resume(conn, decided)
    return decided


async def expire_approvals(engine: AsyncEngine) -> list[uuid.UUID]:
    """Pending approvals past their deadline expire; their runs resume and end inconclusive."""
    async with engine.begin() as conn:
        expired = await expire_due_approvals(conn)
        for approval_id, run_id in expired:
            rows = await conn.execute(
                text("SELECT round FROM approval_requests WHERE id = :id"), {"id": approval_id}
            )
            row = await get_approval_for_round(conn, run_id, rows.scalar_one())
            if row is not None:
                await _resume(conn, row)
    if expired:
        log.info("approvals_expired", count=len(expired))
    return [a for a, _ in expired]
