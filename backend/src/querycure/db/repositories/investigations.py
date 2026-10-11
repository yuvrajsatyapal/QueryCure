import datetime as dt
import json
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.core.errors import InvalidStateError


class RunInputs(BaseModel):
    """What the worker needs to start a run: references only, read at intake."""

    model_config = ConfigDict(frozen=True)

    run_id: uuid.UUID
    investigation_id: uuid.UUID
    user_id: uuid.UUID
    objective: str
    modes: list[str]
    connection_id: uuid.UUID | None
    workload_id: str | None
    artifacts: dict[str, str]  # role -> sha256, e.g. "input.query" -> digest


async def get_run_inputs(conn: AsyncConnection, run_id: uuid.UUID) -> RunInputs:
    row = (
        await conn.execute(
            text(
                "SELECT r.id AS run_id, i.id AS investigation_id, i.user_id, i.objective, i.modes, "
                "i.connection_id, i.workload_id FROM investigation_runs r "
                "JOIN investigations i ON i.id = r.investigation_id WHERE r.id = :id"
            ),
            {"id": run_id},
        )
    ).first()
    if row is None:
        raise InvalidStateError("Run not found.")
    roles = await conn.execute(
        text(
            "SELECT ra.role, a.sha256 FROM run_artifacts ra "
            "JOIN artifacts a ON a.id = ra.artifact_id "
            "WHERE ra.run_id = :id AND ra.role LIKE 'input.%' ORDER BY ra.role"
        ),
        {"id": run_id},
    )
    return RunInputs(
        **row._mapping,
        artifacts={r.role: r.sha256 for r in roles},
    )


async def insert_investigation(
    conn: AsyncConnection,
    *,
    user_id: uuid.UUID,
    title: str,
    objective: str,
    modes: list[str],
    connection_id: uuid.UUID | None,
    workload_id: str | None,
) -> uuid.UUID:
    return (  # type: ignore[no-any-return]
        await conn.execute(
            text(
                "INSERT INTO investigations (user_id, title, objective, modes, connection_id, "
                "workload_id) VALUES (:user_id, :title, :objective, :modes, :connection_id, "
                ":workload_id) RETURNING id"
            ),
            {
                "user_id": user_id,
                "title": title,
                "objective": objective,
                "modes": modes,
                "connection_id": connection_id,
                "workload_id": workload_id,
            },
        )
    ).scalar_one()


async def insert_run(
    conn: AsyncConnection,
    *,
    investigation_id: uuid.UUID,
    budget: dict[str, Any],
    idempotency_key: str | None,
    request_hash: str | None,
) -> uuid.UUID:
    run_id: uuid.UUID = (
        await conn.execute(
            text(
                "INSERT INTO investigation_runs (investigation_id, run_number, kind, status, "
                "budget, usage, idempotency_key, idempotency_request_hash) VALUES (:inv, "
                "(SELECT coalesce(max(run_number), 0) + 1 FROM investigation_runs "
                "WHERE investigation_id = :inv), 'initial', 'queued', CAST(:budget AS JSONB), "
                "'{}', :key, :hash) RETURNING id"
            ),
            {
                "inv": investigation_id,
                "budget": json.dumps(budget),
                "key": idempotency_key,
                "hash": request_hash,
            },
        )
    ).scalar_one()
    await conn.execute(
        text("UPDATE investigations SET latest_run_id = :run WHERE id = :inv"),
        {"run": run_id, "inv": investigation_id},
    )
    return run_id


async def set_query_artifact(
    conn: AsyncConnection, investigation_id: uuid.UUID, artifact_id: uuid.UUID
) -> None:
    await conn.execute(
        text("UPDATE investigations SET query_artifact_id = :a WHERE id = :id"),
        {"a": artifact_id, "id": investigation_id},
    )


async def find_by_idempotency_key(conn: AsyncConnection, key: str) -> Any | None:
    return (
        await conn.execute(
            text(
                "SELECT r.id AS run_id, r.investigation_id, i.user_id, "
                "r.idempotency_request_hash AS request_hash FROM investigation_runs r "
                "JOIN investigations i ON i.id = r.investigation_id "
                "WHERE r.idempotency_key = :key"
            ),
            {"key": key},
        )
    ).first()


async def count_active_runs(conn: AsyncConnection, user_id: uuid.UUID) -> int:
    count = (
        await conn.execute(
            text(
                "SELECT count(*) FROM investigation_runs r JOIN investigations i "
                "ON i.id = r.investigation_id WHERE i.user_id = :user_id "
                "AND i.deleted_at IS NULL "
                "AND r.status IN ('queued', 'running', 'awaiting_approval', 'cancelling')"
            ),
            {"user_id": user_id},
        )
    ).scalar_one()
    return int(count)


_GET_INVESTIGATION = (
    "SELECT i.id, i.title, i.objective, i.modes, i.created_at, i.connection_id, "
    "i.workload_id, i.latest_run_id FROM investigations i "
    "WHERE i.id = :id AND i.user_id = :user_id AND (i.deleted_at IS NOT NULL) = :deleted"
)


async def get_investigation(
    conn: AsyncConnection, *, user_id: uuid.UUID, investigation_id: uuid.UUID, deleted: bool = False
) -> Any | None:
    """`deleted=True` finds a soft-deleted investigation (for restore)."""
    return (
        await conn.execute(
            text(_GET_INVESTIGATION),
            {"id": investigation_id, "user_id": user_id, "deleted": deleted},
        )
    ).first()


async def runs_of(conn: AsyncConnection, investigation_id: uuid.UUID) -> list[Any]:
    rows = await conn.execute(
        text(
            "SELECT r.id, r.investigation_id, r.run_number, r.kind, r.status, r.outcome, "
            "r.created_at, r.started_at, r.finished_at, r.budget, r.usage, r.llm_provider, "
            "r.llm_model, r.error, r.last_event_seq, r.cancel_requested_at "
            "FROM investigation_runs r "
            "WHERE r.investigation_id = :id AND r.deleted_at IS NULL ORDER BY r.run_number"
        ),
        {"id": investigation_id},
    )
    return list(rows)


async def get_run_row(conn: AsyncConnection, *, user_id: uuid.UUID, run_id: uuid.UUID) -> Any:
    return (
        await conn.execute(
            text(
                "SELECT r.id, r.investigation_id, r.run_number, r.kind, r.status, r.outcome, "
                "r.created_at, r.started_at, r.finished_at, r.budget, r.usage, r.llm_provider, "
                "r.llm_model, r.error, r.last_event_seq, r.cancel_requested_at "
                "FROM investigation_runs r JOIN investigations i ON i.id = r.investigation_id "
                "WHERE r.id = :run_id AND i.user_id = :user_id "
                "AND r.deleted_at IS NULL AND i.deleted_at IS NULL"
            ),
            {"run_id": run_id, "user_id": user_id},
        )
    ).first()


_LIST = text(
    "SELECT i.id, i.title, i.objective, i.modes, i.created_at, r.id AS run_id, "
    "r.investigation_id AS run_investigation_id, r.run_number, r.kind, r.status, r.outcome, "
    "r.created_at AS run_created_at, r.started_at, r.finished_at "
    "FROM investigations i LEFT JOIN investigation_runs r ON r.id = i.latest_run_id "
    "WHERE i.user_id = :user_id AND i.deleted_at IS NULL "
    "AND (CAST(:after_at AS TIMESTAMPTZ) IS NULL "
    "     OR (i.created_at, i.id) < (CAST(:after_at AS TIMESTAMPTZ), CAST(:after_id AS UUID))) "
    "AND (CAST(:status AS TEXT) IS NULL OR r.status = :status) "
    "AND (CAST(:outcome AS TEXT) IS NULL OR r.outcome = :outcome) "
    "AND (CAST(:q AS TEXT) IS NULL OR i.title ILIKE :q ESCAPE '\\') "
    "ORDER BY i.created_at DESC, i.id DESC LIMIT :limit"
)


async def list_investigations(
    conn: AsyncConnection,
    *,
    user_id: uuid.UUID,
    limit: int,
    after: tuple[dt.datetime, uuid.UUID] | None,
    status: str | None,
    outcome: str | None,
    q: str | None,
) -> list[Any]:
    pattern = None
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
    rows = await conn.execute(
        _LIST,
        {
            "user_id": user_id,
            "limit": limit,
            "after_at": after[0] if after else None,
            "after_id": after[1] if after else None,
            "status": status,
            "outcome": outcome,
            "q": pattern,
        },
    )
    return list(rows)


async def set_deleted(
    conn: AsyncConnection, *, user_id: uuid.UUID, investigation_id: uuid.UUID, deleted: bool
) -> bool:
    """Soft delete (deleted=True) or restore; False when nothing matched."""
    statement = (
        "UPDATE investigations SET deleted_at = now() "
        "WHERE id = :id AND user_id = :user_id AND deleted_at IS NULL"
        if deleted
        else "UPDATE investigations SET deleted_at = NULL "
        "WHERE id = :id AND user_id = :user_id AND deleted_at IS NOT NULL"
    )
    result = await conn.execute(text(statement), {"id": investigation_id, "user_id": user_id})
    return result.rowcount == 1


async def mark_cancel_requested(conn: AsyncConnection, run_id: uuid.UUID) -> None:
    await conn.execute(
        text(
            "UPDATE investigation_runs SET cancel_requested_at = coalesce(cancel_requested_at, "
            "now()) WHERE id = :id"
        ),
        {"id": run_id},
    )
