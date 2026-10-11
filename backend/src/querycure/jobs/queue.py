"""PostgreSQL job queue: FOR UPDATE SKIP LOCKED claims with leases (DATABASE_DESIGN §4 jobs).

Every state change after the claim is conditional on `locked_by = worker_id AND status =
'running'`, so a worker whose lease expired and was reclaimed can no longer touch the job.
All times come from the database clock.
"""

import json
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

JobKind = Literal["run_start", "run_resume", "experiment_replay", "retention_sweep"]

BACKOFF_BASE_SECONDS = 2
BACKOFF_MAX_SECONDS = 300
DEFAULT_MAX_ATTEMPTS = 3


class Job(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    kind: JobKind
    run_id: uuid.UUID | None
    payload: dict[str, Any]
    attempts: int
    max_attempts: int
    reclaimed: bool  # claimed from an expired lease (the previous worker crashed or stalled)


class ReapedJob(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    kind: JobKind
    run_id: uuid.UUID | None


async def enqueue(
    conn: AsyncConnection,
    *,
    kind: JobKind,
    payload: dict[str, Any],
    run_id: uuid.UUID | None = None,
    dedupe_key: str | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> uuid.UUID | None:
    """Returns the new job ID, or None when an active job with the same dedupe key exists."""
    return (
        await conn.execute(
            text(
                "INSERT INTO jobs (kind, run_id, payload, dedupe_key, max_attempts) "
                "VALUES (:kind, :run_id, CAST(:payload AS JSONB), :dedupe_key, :max_attempts) "
                "ON CONFLICT (dedupe_key) "
                "WHERE dedupe_key IS NOT NULL AND status IN ('pending', 'running') DO NOTHING "
                "RETURNING id"
            ),
            {
                "kind": kind,
                "run_id": run_id,
                "payload": json.dumps(payload),
                "dedupe_key": dedupe_key,
                "max_attempts": max_attempts,
            },
        )
    ).scalar_one_or_none()


_CLAIM = text(
    "WITH candidate AS ("
    "  SELECT id, status AS previous FROM jobs"
    "  WHERE (status = 'pending' AND run_after <= now())"
    "     OR (status = 'running' AND locked_until < now() AND attempts < max_attempts)"
    "  ORDER BY run_after"
    "  FOR UPDATE SKIP LOCKED"
    "  LIMIT 1) "
    "UPDATE jobs j SET status = 'running', locked_by = :worker, "
    "locked_until = now() + make_interval(secs => :lease), attempts = j.attempts + 1 "
    "FROM candidate c WHERE j.id = c.id "
    "RETURNING j.id, j.kind, j.run_id, j.payload, j.attempts, j.max_attempts, "
    "c.previous = 'running' AS reclaimed"
)


async def claim(conn: AsyncConnection, *, worker_id: str, lease_seconds: int) -> Job | None:
    row = (await conn.execute(_CLAIM, {"worker": worker_id, "lease": lease_seconds})).first()
    return None if row is None else Job.model_validate(row, from_attributes=True)


async def reap_exhausted(conn: AsyncConnection) -> list[ReapedJob]:
    """Dead-letter crashed jobs that have no attempts left; callers fail their runs."""
    rows = await conn.execute(
        text(
            "UPDATE jobs SET status = 'dead', locked_by = NULL, locked_until = NULL, "
            'last_error = \'{"code": "LEASE_EXPIRED_NO_ATTEMPTS_LEFT"}\' '
            "WHERE id IN (SELECT id FROM jobs WHERE status = 'running' AND locked_until < now() "
            "AND attempts >= max_attempts FOR UPDATE SKIP LOCKED) "
            "RETURNING id, kind, run_id"
        )
    )
    return [ReapedJob.model_validate(r, from_attributes=True) for r in rows]


async def heartbeat(
    conn: AsyncConnection, *, job_id: uuid.UUID, worker_id: str, lease_seconds: int
) -> bool:
    """False means the lease was lost: the worker must stop working on the job."""
    result = await conn.execute(
        text(
            "UPDATE jobs SET locked_until = now() + make_interval(secs => :lease) "
            "WHERE id = :id AND locked_by = :worker AND status = 'running'"
        ),
        {"id": job_id, "worker": worker_id, "lease": lease_seconds},
    )
    return result.rowcount == 1


async def complete(conn: AsyncConnection, *, job_id: uuid.UUID, worker_id: str) -> bool:
    result = await conn.execute(
        text(
            "UPDATE jobs SET status = 'done', locked_by = NULL, locked_until = NULL "
            "WHERE id = :id AND locked_by = :worker AND status = 'running'"
        ),
        {"id": job_id, "worker": worker_id},
    )
    return result.rowcount == 1


async def fail(
    conn: AsyncConnection,
    *,
    job_id: uuid.UUID,
    worker_id: str,
    error: dict[str, Any],
    retryable: bool = True,
) -> Literal["pending", "dead"] | None:
    """Retry with exponential backoff while attempts remain; otherwise dead-letter.

    Returns the new status, or None if this worker no longer holds the job.
    """
    status = (
        await conn.execute(
            text(
                "UPDATE jobs SET "
                "status = CASE WHEN :retryable AND attempts < max_attempts "
                "THEN 'pending' ELSE 'dead' END, "
                "run_after = now() + make_interval(secs => least(:max_backoff, "
                "power(:base, attempts)::int)), "
                "locked_by = NULL, locked_until = NULL, last_error = CAST(:error AS JSONB) "
                "WHERE id = :id AND locked_by = :worker AND status = 'running' "
                "RETURNING status"
            ),
            {
                "id": job_id,
                "worker": worker_id,
                "retryable": retryable,
                "error": json.dumps(error),
                "base": BACKOFF_BASE_SECONDS,
                "max_backoff": BACKOFF_MAX_SECONDS,
            },
        )
    ).scalar_one_or_none()
    return status
