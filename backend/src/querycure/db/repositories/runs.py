import datetime as dt
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.core.errors import InvalidStateError
from querycure.domain.runs import TERMINAL_STATUSES, RunOutcome, RunStatus, sources_for

# One statement: the row lock makes concurrent callers re-check the status after waiting,
# so exactly one of several racing transitions wins (DATABASE_DESIGN §7).
_TRANSITION = text(
    "UPDATE investigation_runs r SET status = :to, "
    "outcome = :outcome, "
    "started_at = CASE WHEN :to = 'running' THEN coalesce(r.started_at, now()) "
    "ELSE r.started_at END, "
    "finished_at = CASE WHEN :terminal THEN now() ELSE r.finished_at END "
    "FROM (SELECT id, status AS previous FROM investigation_runs WHERE id = :id FOR UPDATE) p "
    "WHERE r.id = p.id AND p.previous = ANY(:sources) "
    "RETURNING p.previous"
)


async def transition_run(
    conn: AsyncConnection,
    run_id: uuid.UUID,
    to: RunStatus,
    *,
    outcome: RunOutcome | None = None,
) -> RunStatus:
    """Move a run along the AGENT_SYSTEM §9 state machine; returns the status it left."""
    if (to is RunStatus.COMPLETED) != (outcome is not None):
        raise ValueError("an outcome is required for, and only for, the completed status")
    previous = (
        await conn.execute(
            _TRANSITION,
            {
                "id": run_id,
                "to": to.value,
                "outcome": outcome.value if outcome is not None else None,
                "terminal": to in TERMINAL_STATUSES,
                "sources": sorted(s.value for s in sources_for(to)),
            },
        )
    ).scalar_one_or_none()
    if previous is None:
        raise InvalidStateError(f"Run cannot move to {to.value} from its current status.")
    return RunStatus(previous)


class RunRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    investigation_id: uuid.UUID
    run_number: int
    kind: str
    status: RunStatus
    outcome: RunOutcome | None
    budget: dict[str, Any]
    usage: dict[str, Any]
    llm_provider: str | None
    llm_model: str | None
    error: dict[str, Any] | None
    last_event_seq: int
    cancel_requested_at: dt.datetime | None
    started_at: dt.datetime | None
    finished_at: dt.datetime | None
    created_at: dt.datetime


_SELECT_RUN = (
    "SELECT r.id, r.investigation_id, r.run_number, r.kind, r.status, r.outcome, r.budget, "
    "r.usage, r.llm_provider, r.llm_model, r.error, r.last_event_seq, r.cancel_requested_at, "
    "r.started_at, r.finished_at, r.created_at FROM investigation_runs r "
    "JOIN investigations i ON i.id = r.investigation_id "
)


async def get_run_for_user(
    conn: AsyncConnection, *, user_id: uuid.UUID, run_id: uuid.UUID
) -> RunRecord | None:
    """None for missing, deleted, or another user's run: the API answers 404 for all three."""
    row = (
        await conn.execute(
            text(
                _SELECT_RUN + "WHERE r.id = :run_id AND i.user_id = :user_id "
                "AND r.deleted_at IS NULL AND i.deleted_at IS NULL"
            ),
            {"run_id": run_id, "user_id": user_id},
        )
    ).first()
    return None if row is None else RunRecord.model_validate(row, from_attributes=True)


async def get_run_status(conn: AsyncConnection, run_id: uuid.UUID) -> RunStatus | None:
    status = (
        await conn.execute(
            text("SELECT status FROM investigation_runs WHERE id = :id"), {"id": run_id}
        )
    ).scalar_one_or_none()
    return None if status is None else RunStatus(status)
