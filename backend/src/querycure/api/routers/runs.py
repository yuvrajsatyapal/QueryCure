import base64
import binascii
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Header, Path, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.api.deps import (
    ConnDep,
    CurrentUser,
    EngineDep,
    HubDep,
    SettingsDep,
    StreamUser,
)
from querycure.api.schemas.investigations import (
    ArtifactRefOut,
    EvidenceDetail,
    FindingOut,
    FindingsResponse,
    RunDetail,
    RunPlan,
    RunPlanList,
    run_detail,
)
from querycure.api.schemas.runs import RunEvent, RunEventPage
from querycure.api.sse import event_stream
from querycure.core.errors import BadRequestError, NotFoundError
from querycure.db.repositories import investigations
from querycure.db.repositories.artifacts import artifacts_for_run
from querycure.db.repositories.events import list_events
from querycure.db.repositories.findings import list_findings, list_hypotheses
from querycure.db.repositories.runs import get_run_for_user
from querycure.domain.runs import TERMINAL_STATUSES, RunStatus
from querycure.domain.users import User
from querycure.events.emitter import change_status
from querycure.evidence.store import list_evidence
from querycure.plans.metrics import compute_metrics
from querycure.plans.parser import parse_plan
from querycure.replay.artifact_store import get_artifact
from querycure.replay.finalize import Conclusion, finalize_run

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


async def _owned_run(conn: AsyncConnection, user: User, run_id: uuid.UUID) -> Any:
    run = await investigations.get_run_row(conn, user_id=user.id, run_id=run_id)
    if run is None:
        raise NotFoundError("Run not found.")
    return run


@router.get("/runs/{run_id}")
async def get_run(run_id: uuid.UUID, conn: ConnDep, user: CurrentUser) -> RunDetail:
    return run_detail(await _owned_run(conn, user, run_id))


@router.post("/runs/{run_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_run(run_id: uuid.UUID, conn: ConnDep, user: CurrentUser) -> RunDetail:
    """Idempotent (API_DESIGN §4): queued/awaiting_approval stop at once; a running run moves
    to cancelling and the worker stops at its next safe point."""
    run = await _owned_run(conn, user, run_id)
    current = RunStatus(run.status)
    if current not in TERMINAL_STATUSES and current is not RunStatus.CANCELLING:
        await investigations.mark_cancel_requested(conn, run_id)
        if current is RunStatus.RUNNING:
            await change_status(conn, run_id, RunStatus.CANCELLING)
        else:  # nothing is executing: seal it now, with a partial report
            await finalize_run(
                conn,
                run_id,
                Conclusion(final_status=RunStatus.CANCELLED, outcome=None, stop_reason="cancelled"),
            )
    return run_detail(await _owned_run(conn, user, run_id))


@router.get("/runs/{run_id}/findings")
async def run_findings(run_id: uuid.UUID, conn: ConnDep, user: CurrentUser) -> FindingsResponse:
    await _owned_run(conn, user, run_id)
    return FindingsResponse(
        findings=[
            FindingOut(key=key, **f.model_dump()) for key, f in await list_findings(conn, run_id)
        ],
        hypotheses=await list_hypotheses(conn, run_id),
    )


@router.get("/runs/{run_id}/evidence/{evidence_id}")
async def run_evidence(
    run_id: uuid.UUID,
    evidence_id: Annotated[str, Path(pattern=r"^ev_[0-9a-f]{12}$")],
    conn: ConnDep,
    user: CurrentUser,
) -> EvidenceDetail:
    await _owned_run(conn, user, run_id)
    found = await list_evidence(conn, run_id, [evidence_id])
    if not found:
        raise NotFoundError("Evidence not found.")
    evidence = found[0]
    artifact = None
    if evidence.artifact_sha256 is not None:
        stored = await get_artifact(conn, evidence.artifact_sha256)
        if stored is not None:
            artifact = ArtifactRefOut(sha256=stored.sha256, kind=stored.kind)
    return EvidenceDetail(
        evidence=evidence,
        artifact=artifact,
        cited_by_findings=[
            key for key, f in await list_findings(conn, run_id) if evidence_id in f.evidence_ids
        ],
        cited_by_hypotheses=[
            h.key
            for h in await list_hypotheses(conn, run_id)
            if evidence_id in h.supporting_evidence + h.contradicting_evidence
        ],
    )


@router.get("/runs/{run_id}/plans")
async def run_plans(run_id: uuid.UUID, conn: ConnDep, user: CurrentUser) -> RunPlanList:
    await _owned_run(conn, user, run_id)
    items = []
    for row in await artifacts_for_run(conn, run_id, roles=("input.plan", "context.plan")):
        stored = await get_artifact(conn, row.sha256)
        if stored is None:
            continue
        tree = parse_plan(stored.content)
        items.append(
            RunPlan(
                sha256=row.sha256,
                kind=row.kind,
                role=row.role,
                plan=tree,
                metrics=compute_metrics(tree),
            )
        )
    return RunPlanList(items=items)
