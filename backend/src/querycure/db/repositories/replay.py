"""replay_attempts (REPLAY_ENGINE §8): one row per replay request, user-scoped."""

import base64
import datetime as dt
import json
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_COLUMNS = (
    "a.id, a.user_id, a.kind, a.source_run_id, a.source_experiment_id, a.replay_run_id, "
    "a.replay_experiment_id, a.approval_request_id, a.status, a.failure_code, a.warnings, "
    "a.result, a.started_at, a.finished_at, a.created_at"
)
EXPERIMENT_TERMINAL = frozenset(
    {"not_replayable", "reproduced", "reproduced_with_drift", "not_reproduced", "inconclusive",
     "failed", "cancelled"}
)  # fmt: skip


class AttemptRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    user_id: uuid.UUID
    kind: str
    source_run_id: uuid.UUID
    source_experiment_id: uuid.UUID | None
    replay_run_id: uuid.UUID | None
    replay_experiment_id: uuid.UUID | None
    approval_request_id: uuid.UUID | None
    status: str
    failure_code: str | None
    warnings: list[str]
    result: dict[str, Any]
    started_at: dt.datetime
    finished_at: dt.datetime | None
    created_at: dt.datetime


def _row(r: Any) -> AttemptRow:
    return AttemptRow.model_validate(dict(r._mapping))


async def insert_attempt(
    conn: AsyncConnection,
    *,
    user_id: uuid.UUID,
    kind: str,
    source_run_id: uuid.UUID,
    status: str,
    failure_code: str | None = None,
    warnings: list[str] | None = None,
    result: dict[str, Any] | None = None,
    source_experiment_id: uuid.UUID | None = None,
    replay_run_id: uuid.UUID | None = None,
    approval_request_id: uuid.UUID | None = None,
    finished: bool = False,
) -> AttemptRow:
    row = (
        await conn.execute(
            text(
                "INSERT INTO replay_attempts AS a (user_id, kind, source_run_id, "  # noqa: S608
                "source_experiment_id, replay_run_id, approval_request_id, status, failure_code, "
                "warnings, result, finished_at) VALUES (:user, :kind, :src, :src_exp, :replay, "
                ":approval, :status, :code, :warnings, CAST(:result AS JSONB), "
                "CASE WHEN :finished THEN now() END) "
                f"RETURNING {_COLUMNS}"
            ),
            {
                "user": user_id,
                "kind": kind,
                "src": source_run_id,
                "src_exp": source_experiment_id,
                "replay": replay_run_id,
                "approval": approval_request_id,
                "status": status,
                "code": failure_code,
                "warnings": warnings or [],
                "result": json.dumps(result or {}),
                "finished": finished,
            },
        )
    ).one()
    return _row(row)


async def update_attempt(
    conn: AsyncConnection,
    attempt_id: uuid.UUID,
    *,
    status: str,
    from_statuses: tuple[str, ...] | None = None,
    failure_code: str | None = None,
    result: dict[str, Any] | None = None,
    replay_experiment_id: uuid.UUID | None = None,
    finished: bool = False,
) -> AttemptRow | None:
    """Conditional on the current status, so racing updates (cancel vs completion) resolve
    to exactly one winner. None when the attempt was no longer in `from_statuses`."""
    row = (
        await conn.execute(
            text(
                "UPDATE replay_attempts a SET status = :status, "  # noqa: S608
                "failure_code = COALESCE(:code, a.failure_code), "
                "result = COALESCE(CAST(:result AS JSONB), a.result), "
                "replay_experiment_id = COALESCE(:exp, a.replay_experiment_id), "
                "finished_at = CASE WHEN :finished THEN now() ELSE a.finished_at END "
                "WHERE a.id = :id AND (CAST(:froms AS TEXT[]) IS NULL "
                "OR a.status = ANY(CAST(:froms AS TEXT[]))) "
                f"RETURNING {_COLUMNS}"
            ),
            {
                "id": attempt_id,
                "status": status,
                "code": failure_code,
                "result": None if result is None else json.dumps(result),
                "exp": replay_experiment_id,
                "finished": finished,
                "froms": None if from_statuses is None else list(from_statuses),
            },
        )
    ).first()
    return None if row is None else _row(row)


async def get_attempt(
    conn: AsyncConnection, attempt_id: uuid.UUID, *, user_id: uuid.UUID | None = None
) -> AttemptRow | None:
    row = (
        await conn.execute(
            text(
                f"SELECT {_COLUMNS} FROM replay_attempts a WHERE a.id = :id "  # noqa: S608
                "AND a.deleted_at IS NULL AND (CAST(:user AS UUID) IS NULL OR a.user_id = :user)"
            ),
            {"id": attempt_id, "user": user_id},
        )
    ).first()
    return None if row is None else _row(row)


async def attempt_for_replay_run(conn: AsyncConnection, run_id: uuid.UUID) -> AttemptRow | None:
    row = (
        await conn.execute(
            text(f"SELECT {_COLUMNS} FROM replay_attempts a WHERE a.replay_run_id = :id"),  # noqa: S608
            {"id": run_id},
        )
    ).first()
    return None if row is None else _row(row)


def encode_cursor(row: AttemptRow) -> str:
    raw = f"{row.created_at.isoformat()}|{row.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[dt.datetime, uuid.UUID]:
    created, _, ident = base64.urlsafe_b64decode(cursor.encode()).decode().partition("|")
    return dt.datetime.fromisoformat(created), uuid.UUID(ident)


async def list_attempts(
    conn: AsyncConnection,
    *,
    user_id: uuid.UUID,
    source_run_id: uuid.UUID,
    limit: int,
    after: tuple[dt.datetime, uuid.UUID] | None = None,
) -> list[AttemptRow]:
    rows = await conn.execute(
        text(
            f"SELECT {_COLUMNS} FROM replay_attempts a WHERE a.source_run_id = :run "  # noqa: S608
            "AND a.user_id = :user AND a.deleted_at IS NULL "
            "AND (CAST(:at AS TIMESTAMPTZ) IS NULL OR (a.created_at, a.id) < "
            "(CAST(:at AS TIMESTAMPTZ), CAST(:aid AS UUID))) "
            "ORDER BY a.created_at DESC, a.id DESC LIMIT :limit"
        ),
        {
            "run": source_run_id,
            "user": user_id,
            "at": None if after is None else after[0],
            "aid": None if after is None else after[1],
            "limit": limit,
        },
    )
    return [_row(r) for r in rows]
