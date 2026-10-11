"""Artifact reads scoped to the owner: an artifact is visible only through a run they own
(DATABASE_DESIGN §5)."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def artifacts_for_run(
    conn: AsyncConnection, run_id: uuid.UUID, *, roles: Sequence[str]
) -> list[Any]:
    rows = await conn.execute(
        text(
            "SELECT a.sha256, a.kind, ra.role FROM run_artifacts ra "
            "JOIN artifacts a ON a.id = ra.artifact_id "
            "WHERE ra.run_id = :run_id AND ra.role = ANY(:roles) ORDER BY ra.role, a.sha256"
        ),
        {"run_id": run_id, "roles": list(roles)},
    )
    return list(rows)


async def owned_by(conn: AsyncConnection, *, user_id: uuid.UUID, sha256: str) -> bool:
    return bool(
        (
            await conn.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM artifacts a "
                    "JOIN run_artifacts ra ON ra.artifact_id = a.id "
                    "JOIN investigation_runs r ON r.id = ra.run_id "
                    "JOIN investigations i ON i.id = r.investigation_id "
                    "WHERE a.sha256 = :sha AND i.user_id = :user_id AND i.deleted_at IS NULL)"
                ),
                {"sha": sha256, "user_id": user_id},
            )
        ).scalar_one()
    )
