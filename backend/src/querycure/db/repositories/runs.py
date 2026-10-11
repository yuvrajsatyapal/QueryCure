import uuid

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
