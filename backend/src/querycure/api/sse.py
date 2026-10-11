"""SSE stream for one run: replay persisted events after `after_seq`, then follow live ones."""

import datetime as dt
import json
import uuid
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.db.repositories.events import EventRecord, list_events
from querycure.db.repositories.runs import get_run_status
from querycure.domain.runs import TERMINAL_STATUSES
from querycure.events.hub import EventHub
from querycure.events.types import EventType

BATCH_SIZE = 500


def format_event(event: EventRecord) -> str:
    ts = event.created_at.astimezone(dt.UTC)
    data = {
        "run_id": str(event.run_id),
        "seq": event.seq,
        "ts": ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z",
        "type": event.type,
        "payload": event.payload,
    }
    body = json.dumps(data, separators=(",", ":"))
    return f"id: {event.seq}\nevent: {event.type}\ndata: {body}\n\n"


def _is_terminal(event: EventRecord) -> bool:
    return event.type == EventType.RUN_STATUS_CHANGED and event.payload.get("to") in {
        s.value for s in TERMINAL_STATUSES
    }


async def event_stream(
    engine: AsyncEngine,
    hub: EventHub,
    run_id: uuid.UUID,
    *,
    after_seq: int,
    heartbeat_seconds: float,
) -> AsyncIterator[str]:
    # Subscribe before the first read so an event committed in between still wakes us.
    sub = hub.subscribe(run_id)
    try:
        last = after_seq
        yield "retry: 3000\n\n"
        while True:
            async with engine.connect() as conn:
                batch = await list_events(conn, run_id=run_id, after_seq=last, limit=BATCH_SIZE)
                if not batch:
                    status = await get_run_status(conn, run_id)
            for event in batch:
                yield format_event(event)
                last = event.seq
                if _is_terminal(event):
                    return
            if len(batch) == BATCH_SIZE:
                continue
            if not batch and (status is None or status in TERMINAL_STATUSES):
                # Reconnected after the terminal event was already delivered.
                return
            if not await sub.wait(heartbeat_seconds):
                yield ": heartbeat\n\n"
    finally:
        sub.close()
