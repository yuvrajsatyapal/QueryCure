"""SSE stream for one run: replay persisted events after `after_seq`, then follow live ones."""

import datetime as dt
import json
import uuid
from collections.abc import AsyncIterator

import anyio
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.api.process_metrics import ProcessMetrics, SseOutcome
from querycure.core.logging import get_logger
from querycure.db.repositories.events import EventRecord, list_events
from querycure.db.repositories.runs import get_run_status
from querycure.domain.runs import TERMINAL_STATUSES, RunStatus
from querycure.events.hub import EventHub
from querycure.events.types import EventType

BATCH_SIZE = 500

log = get_logger("querycure.api.sse")


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


async def _read(
    engine: AsyncEngine, run_id: uuid.UUID, after_seq: int
) -> tuple[list[EventRecord], RunStatus | None]:
    """One short round trip, shielded from client disconnects (F1). A disconnect cancels the
    stream with a level-triggered anyio scope; landing inside the pool's pre-ping it left the
    ping query ACTIVE and SQLAlchemy raised a ProgrammingError instead of the cancellation. The
    read is bounded by the pool timeout and the server-side statement timeout, and the
    cancellation is delivered at the next await, after the connection is back in the pool."""
    with anyio.CancelScope(shield=True):
        async with engine.connect() as conn:
            batch = await list_events(conn, run_id=run_id, after_seq=after_seq, limit=BATCH_SIZE)
            status = None if batch else await get_run_status(conn, run_id)
    return batch, status


async def event_stream(
    engine: AsyncEngine,
    hub: EventHub,
    run_id: uuid.UUID,
    *,
    after_seq: int,
    heartbeat_seconds: float,
    metrics: ProcessMetrics | None = None,
) -> AsyncIterator[str]:
    metrics = metrics or ProcessMetrics()
    # Subscribe before the first read so an event committed in between still wakes us.
    sub = hub.subscribe(run_id)
    metrics.sse_opened()
    # Cancellation (the client went away) and aclose() leave the default in place.
    outcome: SseOutcome = "client_gone"
    last = after_seq
    try:
        yield "retry: 3000\n\n"
        while True:
            batch, status = await _read(engine, run_id, last)
            for event in batch:
                yield format_event(event)
                last = event.seq
                if _is_terminal(event):
                    outcome = "ended"
                    return
            if len(batch) == BATCH_SIZE:
                continue
            if not batch and (status is None or status in TERMINAL_STATUSES):
                # Reconnected after the terminal event was already delivered.
                outcome = "ended"
                return
            if not await sub.wait(heartbeat_seconds):
                yield ": heartbeat\n\n"
    except Exception:
        # The 200 and some events are already sent, so no error status can follow. End the
        # stream instead: the browser reconnects with Last-Event-ID and resumes where it was.
        outcome = "error"
        log.error("sse_stream_failed", run_id=str(run_id), last_seq=last, exc_info=True)
    finally:
        sub.close()
        metrics.sse_closed(outcome)
