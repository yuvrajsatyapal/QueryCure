import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncEngine

from querydoctor.api.deps import ConnDep, CurrentUser, SettingsDep, get_engine
from querydoctor.api.schemas.connections import (
    ConnectionList,
    ConnectionSummary,
    ConnectionTestResponse,
    CreateConnectionRequest,
    ExplainRequest,
    ExplainResponse,
    QueryInfo,
)
from querydoctor.connectors.inspection_gateway import InspectionGateway
from querydoctor.connectors.models import SchemaSnapshot, TargetConnection
from querydoctor.connectors.ssrf_guard import TargetPolicy, resolve_target
from querydoctor.core.config import Profile, Settings
from querydoctor.core.crypto import SecretBox, secret_aad
from querydoctor.core.errors import (
    ApprovalRequiredError,
    ConfigurationError,
    FeatureDisabledError,
    NotFoundError,
    QueryDoctorError,
    RoleTooPrivilegedError,
    TargetBlockedError,
    ValidationFailedError,
)
from querydoctor.db.repositories import connections as repo
from querydoctor.db.repositories.connections import ConnectionRecord
from querydoctor.domain.users import User
from querydoctor.plans.metrics import compute_metrics
from querydoctor.plans.parser import parse_plan
from querydoctor.sql.validator import SqlPolicy, TableRef

MAX_SNAPSHOT_TABLES = 50
_TABLE = "database_connections"


def require_live_inspection(settings: SettingsDep) -> None:
    # Mode B is off on the public demo by default (ADR-0003, SECURITY.md §5.3).
    if settings.profile is not Profile.LOCAL and not settings.feature_live_inspection_public:
        raise FeatureDisabledError("Live database inspection is disabled on this deployment.")


router = APIRouter(
    prefix="/connections", tags=["connections"], dependencies=[Depends(require_live_inspection)]
)


def _secret_box(settings: Settings) -> SecretBox:
    if settings.master_key is None:
        raise ConfigurationError("QD_MASTER_KEY is not configured; credentials cannot be stored.")
    return SecretBox.from_base64(
        settings.master_key.get_secret_value(), version=settings.master_key_version
    )


def _aad(record_id: uuid.UUID, user: User) -> bytes:
    return secret_aad(table=_TABLE, row_id=str(record_id), user_id=str(user.id))


async def _owned(conn: ConnDep, user: User, connection_id: uuid.UUID) -> ConnectionRecord:
    record = await repo.get_connection(conn, user_id=user.id, connection_id=connection_id)
    if record is None:
        raise NotFoundError("Connection not found.")
    return record


def _target(record: ConnectionRecord, user: User, settings: Settings) -> TargetConnection:
    sealed = record.sealed_password()
    if sealed is None:
        raise NotFoundError("Connection not found.")
    password = _secret_box(settings).decrypt(sealed, aad=_aad(record.id, user))
    return TargetConnection(
        host=record.host,
        port=record.port,
        dbname=record.dbname,
        username=record.username,
        password=password,
        sslmode=record.sslmode,  # type: ignore[arg-type]
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_connection(
    body: CreateConnectionRequest, conn: ConnDep, user: CurrentUser, settings: SettingsDep
) -> ConnectionSummary:
    policy = TargetPolicy.from_settings(settings)
    if body.sslmode == "disable" and not policy.allow_private:
        raise TargetBlockedError(
            "TLS is required for this deployment.",
            details=[{"field": "sslmode", "message": "disable is only allowed locally"}],
        )
    # Fail fast on blocked targets; the gateway re-resolves and re-checks on every use.
    await resolve_target(body.host, body.port, policy=policy)
    box = _secret_box(settings)
    record_id = uuid.uuid4()
    sealed = box.encrypt(body.password.get_secret_value(), aad=_aad(record_id, user))
    record = await repo.insert_connection(
        conn,
        id=record_id,
        user_id=user.id,
        fields=body.model_dump(exclude={"password"}),
        sealed=sealed,
    )
    return ConnectionSummary.from_record(record)


@router.get("")
async def list_connections(conn: ConnDep, user: CurrentUser) -> ConnectionList:
    records = await repo.list_connections(conn, user_id=user.id)
    return ConnectionList(items=[ConnectionSummary.from_record(r) for r in records])


@router.post("/{connection_id}/test")
async def test_connection(
    connection_id: uuid.UUID,
    engine: Annotated[AsyncEngine, Depends(get_engine)],
    user: CurrentUser,
    settings: SettingsDep,
) -> ConnectionTestResponse:
    async with engine.begin() as conn:
        record = await _owned(conn, user, connection_id)
    target = _target(record, user, settings)
    try:
        async with InspectionGateway.open(
            target, policy=TargetPolicy.from_settings(settings)
        ) as gw:
            caps = await gw.capabilities()
    except QueryDoctorError as exc:
        # Recorded in its own transaction so the outcome survives the error response.
        outcome = "refused" if isinstance(exc, RoleTooPrivilegedError) else "failed"
        async with engine.begin() as conn:
            await repo.record_test(
                conn, user_id=user.id, connection_id=record.id, status=outcome, capabilities=None
            )
        raise
    async with engine.begin() as conn:
        await repo.record_test(
            conn,
            user_id=user.id,
            connection_id=record.id,
            status="ok",
            capabilities=caps.model_dump(mode="json"),
        )
    return ConnectionTestResponse(status="ok", capabilities=caps, warnings=caps.warnings)


@router.post("/{connection_id}/explain")
async def explain(
    connection_id: uuid.UUID,
    body: ExplainRequest,
    conn: ConnDep,
    user: CurrentUser,
    settings: SettingsDep,
) -> ExplainResponse:
    record = await _owned(conn, user, connection_id)
    if record.environment == "production":
        raise ApprovalRequiredError(
            "EXPLAIN on a production connection needs an approval inside an investigation.",
            details=[{"field": "connection_id", "message": "environment is production"}],
        )
    target = _target(record, user, settings)
    async with InspectionGateway.open(target, policy=TargetPolicy.from_settings(settings)) as gw:
        result = await gw.explain(
            body.query, sql_policy=SqlPolicy(allow_user_functions=body.allow_user_functions)
        )
    tree = parse_plan(result.plan_document)
    return ExplainResponse(
        plan=tree,
        metrics=compute_metrics(tree),
        generic_plan=result.generic_plan,
        query=QueryInfo(
            statement_type=result.validated.statement_type,
            fingerprint=result.validated.fingerprint,
            metadata=result.validated.metadata,
        ),
    )


def _table_refs(raw: str) -> list[TableRef]:
    refs: list[TableRef] = []
    for item in (part.strip() for part in raw.split(",")):
        if not item:
            continue
        schema, _, name = item.rpartition(".")
        if not name or schema.count(".") or not all(p.strip() for p in item.split(".")):
            raise ValidationFailedError(
                "Tables must be given as name or schema.name.",
                details=[{"field": "tables", "message": item[:100]}],
            )
        refs.append(TableRef(schema_name=schema or None, name=name))
    if not refs or len(refs) > MAX_SNAPSHOT_TABLES:
        raise ValidationFailedError(
            f"Provide between 1 and {MAX_SNAPSHOT_TABLES} tables.",
            details=[{"field": "tables", "message": f"got {len(refs)}"}],
        )
    return refs


@router.get("/{connection_id}/schema")
async def schema_snapshot(
    connection_id: uuid.UUID,
    tables: Annotated[str, Query(max_length=4000)],
    conn: ConnDep,
    user: CurrentUser,
    settings: SettingsDep,
) -> SchemaSnapshot:
    record = await _owned(conn, user, connection_id)
    refs = _table_refs(tables)
    target = _target(record, user, settings)
    async with InspectionGateway.open(target, policy=TargetPolicy.from_settings(settings)) as gw:
        return await gw.schema_snapshot(refs)


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(connection_id: uuid.UUID, conn: ConnDep, user: CurrentUser) -> Response:
    if not await repo.soft_delete(conn, user_id=user.id, connection_id=connection_id):
        raise NotFoundError("Connection not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
