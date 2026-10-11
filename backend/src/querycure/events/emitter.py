"""Append to the run's event log inside the caller's transaction (DATABASE_DESIGN §4, §7).

`seq` comes from `UPDATE investigation_runs … RETURNING last_event_seq`: the row lock
serializes writers, so events commit in seq order and a rolled-back transaction leaves no gap.
`pg_notify` is transactional too, so listeners hear about an event only once it is visible.
"""

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.core.errors import InvalidStateError, RunFinalizedError
from querycure.db.repositories.runs import transition_run
from querycure.domain.runs import RunOutcome, RunStatus
from querycure.events.types import LIFECYCLE_TYPES, NOTIFY_CHANNEL, EventType

_NEXT_SEQ = text(
    "UPDATE investigation_runs SET last_event_seq = last_event_seq + 1 "
    "WHERE id = :run_id AND deleted_at IS NULL RETURNING last_event_seq, finalized_at"
)
_INSERT = text(
    "INSERT INTO investigation_events (run_id, seq, type, payload) "
    "VALUES (:run_id, :seq, :type, CAST(:payload AS JSONB))"
)
_NOTIFY = text("SELECT pg_notify(:channel, :run_id)")


async def emit(
    conn: AsyncConnection, run_id: uuid.UUID, type: EventType, payload: dict[str, Any]
) -> int:
    row = (await conn.execute(_NEXT_SEQ, {"run_id": run_id})).first()
    if row is None:
        raise InvalidStateError("Run not found.")
    seq, finalized_at = row
    if finalized_at is not None and type not in LIFECYCLE_TYPES:
        # Raising rolls back the seq increment with the rest of the transaction.
        raise RunFinalizedError("The run is finalized; its event log is sealed.")
    await conn.execute(
        _INSERT,
        {"run_id": run_id, "seq": seq, "type": type.value, "payload": json.dumps(payload)},
    )
    await conn.execute(_NOTIFY, {"channel": NOTIFY_CHANNEL, "run_id": str(run_id)})
    return int(seq)


async def change_status(
    conn: AsyncConnection,
    run_id: uuid.UUID,
    to: RunStatus,
    *,
    outcome: RunOutcome | None = None,
) -> RunStatus:
    """Transition and emit `run.status_changed` together, so SSE never shows a status the
    database does not have."""
    previous = await transition_run(conn, run_id, to, outcome=outcome)
    payload: dict[str, Any] = {"from": previous.value, "to": to.value}
    if outcome is not None:
        payload["outcome"] = outcome.value
    await emit(conn, run_id, EventType.RUN_STATUS_CHANGED, payload)
    return previous
