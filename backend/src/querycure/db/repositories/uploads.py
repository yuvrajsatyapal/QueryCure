"""Who uploaded which artifact (migration 0014). Artifacts are ownerless and deduplicated;
this record is what lets an uploader, and only an uploader, reference a digest in a run."""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def record_upload(
    conn: AsyncConnection, *, user_id: uuid.UUID, artifact_id: uuid.UUID, kind: str
) -> None:
    await conn.execute(
        text(
            "INSERT INTO user_uploads (user_id, artifact_id, kind) VALUES (:u, :a, :k) "
            "ON CONFLICT (user_id, artifact_id) DO NOTHING"
        ),
        {"u": user_id, "a": artifact_id, "k": kind},
    )


async def uploaded_by(conn: AsyncConnection, *, user_id: uuid.UUID, artifact_id: uuid.UUID) -> bool:
    row = await conn.execute(
        text(
            "SELECT 1 FROM user_uploads WHERE user_id = :u AND artifact_id = :a "
            "AND deleted_at IS NULL"
        ),
        {"u": user_id, "a": artifact_id},
    )
    return row.first() is not None
