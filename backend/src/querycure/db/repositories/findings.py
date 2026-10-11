"""Findings and hypotheses: idempotent by deterministic key, refused once the run is sealed."""

import uuid
from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.domain.investigation import Finding, Hypothesis
from querycure.evidence.store import ensure_writable


async def insert_findings(
    conn: AsyncConnection, run_id: uuid.UUID, findings: Sequence[tuple[str, Finding]]
) -> list[str]:
    """(key, finding) pairs; returns the keys that were new."""
    if not findings:
        return []
    await ensure_writable(conn, run_id)
    new: list[str] = []
    for key, f in findings:
        inserted = (
            await conn.execute(
                text(
                    "INSERT INTO findings (run_id, key, agent, title, detail, severity, "
                    "evidence_ids) VALUES (:run_id, :key, :agent, :title, :detail, :severity, "
                    ":evidence_ids) ON CONFLICT (run_id, key) DO NOTHING RETURNING key"
                ),
                {"run_id": run_id, "key": key, **f.model_dump()},
            )
        ).scalar_one_or_none()
        if inserted is not None:
            new.append(inserted)
    return new


async def insert_hypotheses(
    conn: AsyncConnection, run_id: uuid.UUID, round: int, hypotheses: Sequence[Hypothesis]
) -> list[str]:
    if not hypotheses:
        return []
    await ensure_writable(conn, run_id)
    new: list[str] = []
    for h in hypotheses:
        inserted = (
            await conn.execute(
                text(
                    "INSERT INTO hypotheses (run_id, key, round, rank, statement, category, "
                    "supporting_evidence, contradicting_evidence, confidence, uncertainty_notes, "
                    "verification_method, proposed_by) VALUES (:run_id, :key, :round, :rank, "
                    ":statement, :category, :supporting_evidence, :contradicting_evidence, "
                    ":confidence, :uncertainty_notes, :verification_method, :proposed_by) "
                    "ON CONFLICT (run_id, key) DO NOTHING RETURNING key"
                ),
                {"run_id": run_id, "round": round, **h.model_dump()},
            )
        ).scalar_one_or_none()
        if inserted is not None:
            new.append(inserted)
    return new


async def list_findings(conn: AsyncConnection, run_id: uuid.UUID) -> list[tuple[str, Finding]]:
    rows = await conn.execute(
        text(
            "SELECT key, agent, title, detail, severity, evidence_ids FROM findings "
            "WHERE run_id = :run_id AND deleted_at IS NULL ORDER BY created_at, key"
        ),
        {"run_id": run_id},
    )
    return [
        (r.key, Finding.model_validate({k: v for k, v in r._mapping.items() if k != "key"}))
        for r in rows
    ]


async def list_hypotheses(conn: AsyncConnection, run_id: uuid.UUID) -> list[Hypothesis]:
    rows = await conn.execute(
        text(
            "SELECT key, rank, statement, category, supporting_evidence, contradicting_evidence, "
            "confidence, uncertainty_notes, verification_method, proposed_by FROM hypotheses "
            "WHERE run_id = :run_id AND deleted_at IS NULL ORDER BY round, rank"
        ),
        {"run_id": run_id},
    )
    return [Hypothesis.model_validate(r, from_attributes=True) for r in rows]
