import base64
import binascii
import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query
from fastapi.responses import StreamingResponse

from querycure.api.deps import (
    ConnDep,
    CurrentUser,
    EngineDep,
    HubDep,
    SettingsDep,
    StreamUser,
)
from querycure.api.schemas.runs import RunEvent, RunEventPage
from querycure.api.sse import event_stream
from querycure.core.errors import BadRequestError, NotFoundError
from querycure.db.repositories.events import list_events
from querycure.db.repositories.runs import get_run_for_user

router = APIRouter(tags=["runs"])

MAX_HISTORY_LIMIT = 500


def _encode_cursor(seq: int) -> str:
    return base64.urlsafe_b64encode(f"seq:{seq}".encode()).decode()


def _decode_cursor(cursor: str) -> int:
    try:
        prefix, _, value = base64.urlsafe_b64decode(cursor.encode()).decode().partition(":")
        seq = int(value)
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise BadRequestError("Invalid cursor.") from exc
    if prefix != "seq" or seq < 0:
        raise BadRequestError("Invalid cursor.")
    return seq


@router.get(
    "/runs/{run_id}/events",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def stream_run_events(
    run_id: uuid.UUID,
    user: StreamUser,
    engine: EngineDep,
    hub: HubDep,
    settings: SettingsDep,
    after_seq: Annotated[int | None, Query(ge=0)] = None,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    async with engine.begin() as conn:
        if await get_run_for_user(conn, user_id=user.id, run_id=run_id) is None:
            raise NotFoundError("Run not found.")
    start = after_seq or 0
    if last_event_id is not None:
        # The browser's reconnect header wins over the query string (API_DESIGN §3).
        if not last_event_id.isdigit():
            raise BadRequestError("Last-Event-ID must be an event sequence number.")
        start = int(last_event_id)
    return StreamingResponse(
        event_stream(
            engine,
            hub,
            run_id,
            after_seq=start,
            heartbeat_seconds=settings.sse_heartbeat_seconds,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/runs/{run_id}/events/history", response_model=RunEventPage)
async def run_event_history(
    run_id: uuid.UUID,
    user: CurrentUser,
    conn: ConnDep,
    limit: Annotated[int, Query(ge=1, le=MAX_HISTORY_LIMIT)] = 100,
    cursor: str | None = None,
) -> RunEventPage:
    if await get_run_for_user(conn, user_id=user.id, run_id=run_id) is None:
        raise NotFoundError("Run not found.")
    after = _decode_cursor(cursor) if cursor else 0
    events = await list_events(conn, run_id=run_id, after_seq=after, limit=limit + 1)
    page = events[:limit]
    return RunEventPage(
        items=[RunEvent(ts=e.created_at, **e.model_dump(exclude={"created_at"})) for e in page],
        next_cursor=_encode_cursor(page[-1].seq) if len(events) > limit else None,
    )
