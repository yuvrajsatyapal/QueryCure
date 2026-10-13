"""verification_results (append-only; one row per experiment and candidate, ADR-0009)."""

import json
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.evidence.store import ensure_writable

_COLUMNS = (
    "id, run_id, experiment_id, candidate_id, candidate_key, round, engine_verdict, verdict, "
    "reasons, stats, checks, auditor_status, auditor_notes, auditor_concerns, "
    "auditor_prompt_version, auditor_downgraded, created_at"
)


class VerificationRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    run_id: uuid.UUID
    experiment_id: uuid.UUID
    candidate_id: uuid.UUID
    candidate_key: str
    round: int
    engine_verdict: str
    verdict: str
    reasons: list[dict[str, Any]]
    stats: list[dict[str, Any]]
    checks: list[dict[str, Any]]
    auditor_status: str
    auditor_notes: str | None
    auditor_concerns: list[dict[str, Any]]
    auditor_prompt_version: str | None
    auditor_downgraded: bool


async def insert_verification(
    conn: AsyncConnection, run_id: uuid.UUID, row: dict[str, Any]
) -> None:
    """Idempotent: a re-run after a crash finds the row and inserts nothing."""
    await ensure_writable(conn, run_id)
    await conn.execute(
        text(
            "INSERT INTO verification_results (run_id, experiment_id, candidate_id, "
            "candidate_key, round, engine_verdict, verdict, reasons, stats, checks, "
            "auditor_status, auditor_notes, auditor_concerns, auditor_prompt_version, "
            "auditor_downgraded) VALUES (:run_id, :experiment_id, :candidate_id, "
            ":candidate_key, :round, :engine_verdict, :verdict, CAST(:reasons AS JSONB), "
            "CAST(:stats AS JSONB), CAST(:checks AS JSONB), :auditor_status, :auditor_notes, "
            "CAST(:auditor_concerns AS JSONB), :auditor_prompt_version, :auditor_downgraded) "
            "ON CONFLICT (experiment_id, candidate_id) DO NOTHING"
        ),
        {
            **row,
            "run_id": run_id,
            "reasons": json.dumps(row["reasons"]),
            "stats": json.dumps(row["stats"]),
            "checks": json.dumps(row["checks"]),
            "auditor_concerns": json.dumps(row["auditor_concerns"]),
        },
    )


async def list_verifications(
    conn: AsyncConnection, run_id: uuid.UUID, *, experiment_id: uuid.UUID | None = None
) -> list[VerificationRow]:
    rows = await conn.execute(
        text(
            f"SELECT {_COLUMNS} FROM verification_results WHERE run_id = :run "  # noqa: S608
            "AND (CAST(:exp AS UUID) IS NULL OR experiment_id = CAST(:exp AS UUID)) "
            "AND deleted_at IS NULL ORDER BY round, experiment_id, candidate_key"
        ),
        {"run": run_id, "exp": experiment_id},
    )
    return [VerificationRow.model_validate(dict(r._mapping)) for r in rows]
