"""Evidence persistence: idempotent by deterministic ID, sealed once the run is finalized."""

import json
import uuid
from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from querycure.core.errors import InvalidStateError, RunFinalizedError
from querycure.domain.investigation import Evidence
from querycure.events.emitter import emit
from querycure.events.types import EventType

_LOCK_RUN = text("SELECT finalized_at FROM investigation_runs WHERE id = :id FOR SHARE")
_INSERT = text(
    "INSERT INTO evidence (id, run_id, kind, artifact_id, locator, summary, data, provenance) "
    "SELECT x.id, :run_id, x.kind, a.id, x.locator, x.summary, x.data, x.provenance "
    "FROM jsonb_to_recordset(CAST(:rows AS JSONB)) AS x("
    "  id text, kind text, artifact_sha256 text, locator text, summary text, data jsonb, "
    "  provenance text) "
    "LEFT JOIN artifacts a ON a.sha256 = x.artifact_sha256 "
    "ON CONFLICT (run_id, id) DO NOTHING RETURNING id, kind"
)
_SELECT = (
    "SELECT e.id, e.kind, a.sha256 AS artifact_sha256, e.locator, e.summary, e.data, "
    "e.provenance FROM evidence e LEFT JOIN artifacts a ON a.id = e.artifact_id "
    "WHERE e.run_id = :run_id AND e.deleted_at IS NULL "
)


async def ensure_writable(conn: AsyncConnection, run_id: uuid.UUID) -> None:
    """Content writes check finalization in their own transaction (REPLAY_ENGINE §5).

    FOR SHARE waits for an in-flight finalize_run (FOR UPDATE) instead of racing it."""
    row = (await conn.execute(_LOCK_RUN, {"id": run_id})).first()
    if row is None:
        raise InvalidStateError("Run not found.")
    if row.finalized_at is not None:
        raise RunFinalizedError("The run is finalized; no more evidence can be added.")


async def insert_evidence(
    conn: AsyncConnection, run_id: uuid.UUID, items: Sequence[Evidence]
) -> list[Evidence]:
    """Returns the items that were new. Re-inserting the same evidence is a no-op."""
    if not items:
        return []
    await ensure_writable(conn, run_id)
    rows = [e.model_dump(mode="json") for e in {e.id: e for e in items}.values()]
    inserted = {
        r.id for r in await conn.execute(_INSERT, {"run_id": run_id, "rows": json.dumps(rows)})
    }
    return [e for e in items if e.id in inserted]


async def record_evidence(
    engine: AsyncEngine, run_id: uuid.UUID, items: Sequence[Evidence]
) -> list[str]:
    """Insert and announce new evidence in one transaction; returns every item's ID."""
    async with engine.begin() as conn:
        new = await insert_evidence(conn, run_id, items)
        if new:
            await emit(
                conn,
                run_id,
                EventType.EVIDENCE_CREATED,
                {"evidence_ids": [e.id for e in new], "kinds": sorted({e.kind for e in new})},
            )
    return list(dict.fromkeys(e.id for e in items))


async def list_evidence(
    conn: AsyncConnection, run_id: uuid.UUID, ids: Sequence[str] | None = None
) -> list[Evidence]:
    if ids is None:
        rows = await conn.execute(text(_SELECT + "ORDER BY e.created_at, e.id"), {"run_id": run_id})
    else:
        rows = await conn.execute(
            text(_SELECT + "AND e.id = ANY(:ids) ORDER BY e.id"),
            {"run_id": run_id, "ids": list(ids)},
        )
    return [Evidence.model_validate(r, from_attributes=True) for r in rows]


async def existing_ids(conn: AsyncConnection, run_id: uuid.UUID, ids: Sequence[str]) -> set[str]:
    rows = await conn.execute(
        text("SELECT id FROM evidence WHERE run_id = :run_id AND id = ANY(:ids)"),
        {"run_id": run_id, "ids": list(ids)},
    )
    return {r.id for r in rows}
