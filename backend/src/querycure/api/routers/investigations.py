"""Investigations (API_DESIGN §2). Creating one queues a run and its job in one transaction;
the worker does the work. The API never imports the agents package."""

import base64
import binascii
import datetime as dt
import hashlib
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.api.deps import ConnDep, CurrentUser, EngineDep, SettingsDep
from querycure.api.schemas.investigations import (
    CreateInvestigationRequest,
    CreateInvestigationResponse,
    InvestigationDetail,
    InvestigationPage,
    InvestigationSummary,
    RunSummary,
    run_detail,
)
from querycure.core.config import Profile, Settings
from querycure.core.errors import (
    ApprovalRequiredError,
    BadRequestError,
    ConcurrencyLimitError,
    FeatureDisabledError,
    IdempotencyConflictError,
    InvalidStateError,
    NotFoundError,
    ValidationFailedError,
)
from querycure.db.repositories import investigations as repo
from querycure.db.repositories.connections import get_connection
from querycure.domain.budgets import CONCURRENT_RUNS_PER_USER, default_budget
from querycure.domain.runs import ACTIVE_STATUSES, ExecutionMode
from querycure.domain.users import User
from querycure.events.emitter import emit
from querycure.events.types import EventType
from querycure.jobs import queue
from querycure.replay import artifact_store as store
from querycure.replay.canonical import canonical_json
from querycure.sql.validator import validate_select
from querycure.workloads.registry import WORKLOADS, WorkloadRef

router = APIRouter(prefix="/investigations", tags=["investigations"])

MAX_PAGE = 100
_PLAN_KINDS = ("plan", "plan_analyze")


def _invalid(field: str, message: str) -> ValidationFailedError:
    return ValidationFailedError(message, details=[{"field": field, "message": message}])


async def _check(
    conn: AsyncConnection, body: CreateInvestigationRequest, user: User, settings: Settings
) -> None:
    modes = set(body.modes)
    if len(modes) != len(body.modes):
        raise _invalid("modes", "modes must not repeat")
    if ExecutionMode.SANDBOX_BENCHMARK.value in modes:
        _check_sandbox(body, settings)
    elif body.pre_authorize_demo_sandbox:
        raise _invalid("pre_authorize_demo_sandbox", "only applies to sandbox benchmarking")
    if body.llm is not None and body.llm.credential_id is not None:
        raise FeatureDisabledError("Bring-your-own-key credentials arrive in Phase 5.")
    if body.query is None and body.plan_artifact_sha256 is None:
        raise _invalid("query", "provide a query, an uploaded plan, or both")
    if body.query is not None:
        validate_select(body.query)  # SQL_NOT_ALLOWED / SQL_PARSE_ERROR as the envelope
    if ExecutionMode.LIVE_INSPECTION.value in modes:
        if settings.profile is not Profile.LOCAL and not settings.feature_live_inspection_public:
            raise FeatureDisabledError("Live database inspection is disabled on this deployment.")
        if body.connection_id is None:
            raise _invalid("connection_id", "live inspection needs a connection")
        if body.query is None:
            raise _invalid("query", "live inspection needs the query text")
        record = await get_connection(conn, user_id=user.id, connection_id=body.connection_id)
        if record is None:
            raise NotFoundError("Connection not found.")
        if record.environment == "production":
            raise ApprovalRequiredError(
                "EXPLAIN on a production connection needs approval (arrives in Phase 3).",
                details=[{"field": "connection_id", "message": "environment is production"}],
            )
    if body.workload_id is not None:
        try:
            WorkloadRef.parse(body.workload_id)
        except ValueError as exc:
            raise _invalid("workload_id", str(exc)) from None
    for field, sha, kinds in (
        ("plan_artifact_sha256", body.plan_artifact_sha256, _PLAN_KINDS),
        ("schema_artifact_sha256", body.schema_artifact_sha256, ("schema_snapshot",)),
    ):
        if sha is None:
            continue
        artifact = await store.get_artifact(conn, sha)
        if artifact is None or artifact.kind not in kinds:
            raise _invalid(field, "no uploaded artifact of the right kind has this digest")


MAX_BENCH_PARAM_SETS = 5


def _check_sandbox(body: CreateInvestigationRequest, settings: Settings) -> None:
    """Mode C (Phase 3): demo workloads only; the user-provisioned sandbox (D4) is deferred."""
    if not settings.feature_sandbox:
        raise FeatureDisabledError("Sandbox benchmarking is disabled on this deployment.")
    if body.workload_id is None:
        raise _invalid("workload_id", "sandbox benchmarking needs a demo workload")
    if body.query is None:
        raise _invalid("query", "sandbox benchmarking needs the query text")
    if len(body.param_sets) > MAX_BENCH_PARAM_SETS:
        raise _invalid(
            "param_sets", f"at most {MAX_BENCH_PARAM_SETS} param sets can be benchmarked"
        )
    expected = validate_select(body.query).metadata.parameter_count
    for p in body.param_sets:
        if len(p.values) != expected:
            raise _invalid("param_sets", f"param set {p.name} needs {expected} value(s)")
    if expected and not body.param_sets:
        ref = WorkloadRef.parse(body.workload_id)
        examples = {q.sql.strip() for q in WORKLOADS[ref.name].example_queries}
        if body.query.strip() not in examples:
            raise _invalid("param_sets", "a parameterized query needs at least one param set")


def _request_hash(body: CreateInvestigationRequest) -> str:
    return hashlib.sha256(canonical_json(body.model_dump(mode="json"))).hexdigest()


async def _detail(
    conn: AsyncConnection, user: User, investigation_id: uuid.UUID
) -> InvestigationDetail:
    inv = await repo.get_investigation(conn, user_id=user.id, investigation_id=investigation_id)
    if inv is None:
        raise NotFoundError("Investigation not found.")
    runs = [
        RunSummary.model_validate(r, from_attributes=True) for r in await repo.runs_of(conn, inv.id)
    ]
    latest = next((r for r in runs if r.id == inv.latest_run_id), None)
    return InvestigationDetail(
        id=inv.id,
        title=inv.title,
        objective=inv.objective,
        modes=inv.modes,
        created_at=inv.created_at,
        latest_run=latest,
        connection_id=inv.connection_id,
        workload_id=inv.workload_id,
        runs=runs,
    )


async def _response(
    conn: AsyncConnection, user: User, run_id: uuid.UUID
) -> CreateInvestigationResponse:
    run = await repo.get_run_row(conn, user_id=user.id, run_id=run_id)
    if run is None:
        raise NotFoundError("Run not found.")
    return CreateInvestigationResponse(
        investigation=await _detail(conn, user, run.investigation_id), run=run_detail(run)
    )


async def _replay(
    conn: AsyncConnection, user: User, key: str, request_hash: str
) -> CreateInvestigationResponse | None:
    existing = await repo.find_by_idempotency_key(conn, key)
    if existing is None:
        return None
    if existing.user_id != user.id or existing.request_hash != request_hash:
        raise IdempotencyConflictError(
            "This Idempotency-Key was already used for a different request."
        )
    return await _response(conn, user, existing.run_id)


async def _create(
    conn: AsyncConnection,
    body: CreateInvestigationRequest,
    user: User,
    settings: Settings,
    key: str | None,
    request_hash: str | None,
) -> uuid.UUID:
    limit = CONCURRENT_RUNS_PER_USER[settings.profile]
    if await repo.count_active_runs(conn, user.id) >= limit:
        raise ConcurrencyLimitError(f"At most {limit} investigations can run at once.")
    investigation_id = await repo.insert_investigation(
        conn,
        user_id=user.id,
        title=body.title,
        objective=body.objective,
        modes=list(body.modes),
        connection_id=body.connection_id,
        workload_id=body.workload_id,
        pre_authorize_sandbox=body.pre_authorize_demo_sandbox,
    )
    run_id = await repo.insert_run(
        conn,
        investigation_id=investigation_id,
        budget=default_budget(settings.profile).model_dump(),
        idempotency_key=key,
        request_hash=request_hash,
    )
    inputs: list[tuple[str, Any]] = []
    if body.query is not None:
        query_art = await store.store_raw_sql(conn, body.query)
        await repo.set_query_artifact(conn, investigation_id, query_art.id)
        inputs.append(("input.query", query_art))
    if body.param_sets:
        params = [p.model_dump(mode="json") for p in body.param_sets]
        inputs.append(
            ("input.param_sets", await store.store_json(conn, kind="param_sets", value=params))
        )
    for role, sha in (
        ("input.plan", body.plan_artifact_sha256),
        ("input.schema", body.schema_artifact_sha256),
    ):
        if sha is not None:
            inputs.append((role, await store.get_artifact(conn, sha)))
    for role, artifact in inputs:
        await store.link(conn, run_id=run_id, artifact_id=artifact.id, role=role, produced_by="api")
    await emit(conn, run_id, EventType.RUN_STATUS_CHANGED, {"from": None, "to": "queued"})
    await queue.enqueue(
        conn, kind="run_start", run_id=run_id, payload={}, dedupe_key=f"run_start:{run_id}"
    )
    return run_id


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_investigation(
    body: CreateInvestigationRequest,
    engine: EngineDep,
    user: CurrentUser,
    settings: SettingsDep,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> CreateInvestigationResponse:
    key = request_hash = None
    if idempotency_key is not None:
        try:
            key = str(uuid.UUID(idempotency_key))
        except ValueError:
            raise BadRequestError("Idempotency-Key must be a UUID.") from None
        request_hash = _request_hash(body)
        async with engine.begin() as conn:
            replayed = await _replay(conn, user, key, request_hash)
        if replayed is not None:
            return replayed
    try:
        async with engine.begin() as conn:
            await _check(conn, body, user, settings)
            run_id = await _create(conn, body, user, settings, key, request_hash)
            return await _response(conn, user, run_id)
    except IntegrityError:
        # A concurrent request with the same key won the unique index: answer like it did.
        if key is None or request_hash is None:
            raise
        async with engine.begin() as conn:
            replayed = await _replay(conn, user, key, request_hash)
        if replayed is None:
            raise
        return replayed


def _encode_cursor(created_at: dt.datetime, inv_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(f"{created_at.isoformat()}|{inv_id}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[dt.datetime, uuid.UUID]:
    try:
        at, _, raw_id = base64.urlsafe_b64decode(cursor.encode()).decode().partition("|")
        return dt.datetime.fromisoformat(at), uuid.UUID(raw_id)
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise BadRequestError("Invalid cursor.") from exc


@router.get("")
async def list_investigations(
    conn: ConnDep,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 20,
    cursor: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    outcome: str | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> InvestigationPage:
    rows = await repo.list_investigations(
        conn,
        user_id=user.id,
        limit=limit + 1,
        after=_decode_cursor(cursor) if cursor else None,
        status=status_filter,
        outcome=outcome,
        q=q,
    )
    items = [
        InvestigationSummary(
            id=r.id,
            title=r.title,
            objective=r.objective,
            modes=r.modes,
            created_at=r.created_at,
            latest_run=None
            if r.run_id is None
            else RunSummary(
                id=r.run_id,
                investigation_id=r.run_investigation_id,
                run_number=r.run_number,
                kind=r.kind,
                status=r.status,
                outcome=r.outcome,
                created_at=r.run_created_at,
                started_at=r.started_at,
                finished_at=r.finished_at,
            ),
        )
        for r in rows[:limit]
    ]
    more = len(rows) > limit
    return InvestigationPage(
        items=items,
        next_cursor=_encode_cursor(items[-1].created_at, items[-1].id) if more else None,
    )


@router.get("/{investigation_id}")
async def get_investigation(
    investigation_id: uuid.UUID, conn: ConnDep, user: CurrentUser
) -> InvestigationDetail:
    return await _detail(conn, user, investigation_id)


@router.delete("/{investigation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_investigation(
    investigation_id: uuid.UUID, conn: ConnDep, user: CurrentUser
) -> Response:
    detail = await _detail(conn, user, investigation_id)
    if any(r.status in {s.value for s in ACTIVE_STATUSES} for r in detail.runs):
        raise InvalidStateError("Cancel the active run before deleting this investigation.")
    await repo.set_deleted(conn, user_id=user.id, investigation_id=investigation_id, deleted=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{investigation_id}/restore")
async def restore_investigation(
    investigation_id: uuid.UUID, conn: ConnDep, user: CurrentUser
) -> InvestigationDetail:
    restored = await repo.set_deleted(
        conn, user_id=user.id, investigation_id=investigation_id, deleted=False
    )
    if not restored:
        raise NotFoundError("Investigation not found.")
    return await _detail(conn, user, investigation_id)
