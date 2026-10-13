"""Content-addressed artifact store (ADR-0010/0015; DATABASE_DESIGN `artifacts`).

Works with the restricted qc_app role: INSERT … ON CONFLICT DO NOTHING plus re-select, never
UPDATE and never row locks (locking clauses need UPDATE privilege).
"""

import json
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.core.errors import ArtifactConflictError, PayloadTooLargeError, QueryCureError
from querycure.replay.canonical import canonical_json, canonical_raw, canonical_text, to_canonical
from querycure.replay.digest import digest

MAX_ARTIFACT_BYTES = 5 * 1024 * 1024
Profile = Literal["qc-json-v1", "qc-text-v1", "qc-raw-v1"]
MediaType = Literal["application/json", "text/sql", "text/markdown"]


class ArtifactIntegrityError(QueryCureError):
    code = "ARTIFACT_INTEGRITY_ERROR"


class StoredArtifact(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    sha256: str
    kind: str
    media_type: MediaType
    canonicalization: Profile
    content: bytes


async def _put(
    conn: AsyncConnection, *, kind: str, media_type: MediaType, profile: Profile, content: bytes
) -> StoredArtifact:
    if len(content) > MAX_ARTIFACT_BYTES:
        raise PayloadTooLargeError("Artifact is larger than 5 MB.")
    sha = digest(profile, content)
    params = {
        "sha256": sha,
        "kind": kind,
        "media_type": media_type,
        "content": content,
        "profile": profile,
    }
    await conn.execute(
        text(
            "INSERT INTO artifacts (sha256, kind, media_type, content, canonicalization) "
            "VALUES (:sha256, :kind, :media_type, :content, :profile) "
            "ON CONFLICT (sha256) DO NOTHING"
        ),
        params,
    )
    row = (
        await conn.execute(
            text(
                "SELECT id, sha256, kind, media_type, canonicalization, content "
                "FROM artifacts WHERE sha256 = :sha256"
            ),
            params,
        )
    ).one()
    stored = StoredArtifact.model_validate(row, from_attributes=True)
    # The digest includes the profile, so this only happens through a bug or a hand-edited row.
    if stored.canonicalization != profile or stored.content != content:
        raise ArtifactConflictError(
            "An artifact with this digest already exists with other content."
        )
    return stored


async def store_json(conn: AsyncConnection, *, kind: str, value: Any) -> StoredArtifact:
    content = canonical_json(to_canonical(value))
    return await _put(
        conn, kind=kind, media_type="application/json", profile="qc-json-v1", content=content
    )


async def store_text(conn: AsyncConnection, *, kind: str, text: str) -> StoredArtifact:
    content = canonical_text(text)
    return await _put(
        conn, kind=kind, media_type="text/markdown", profile="qc-text-v1", content=content
    )


async def store_raw_sql(conn: AsyncConnection, sql: str) -> StoredArtifact:
    content = canonical_raw(sql.encode("utf-8"))
    return await _put(
        conn, kind="query", media_type="text/sql", profile="qc-raw-v1", content=content
    )


async def get_artifact(conn: AsyncConnection, sha256: str) -> StoredArtifact | None:
    """Fetch by digest and re-verify it; a mismatch means the stored bytes changed."""
    row = (
        await conn.execute(
            text(
                "SELECT id, sha256, kind, media_type, canonicalization, content "
                "FROM artifacts WHERE sha256 = :sha256 AND deleted_at IS NULL"
            ),
            {"sha256": sha256},
        )
    ).one_or_none()
    if row is None:
        return None
    artifact = StoredArtifact.model_validate(row, from_attributes=True)
    if digest(artifact.canonicalization, artifact.content) != artifact.sha256:
        raise ArtifactIntegrityError("Stored artifact does not match its digest.")
    return artifact


async def link(
    conn: AsyncConnection,
    *,
    run_id: uuid.UUID,
    artifact_id: uuid.UUID,
    role: str,
    produced_by: str | None = None,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO run_artifacts (run_id, artifact_id, role, produced_by) "
            "VALUES (:run_id, :artifact_id, :role, :produced_by) "
            "ON CONFLICT (run_id, artifact_id, role) DO NOTHING"
        ),
        {"run_id": run_id, "artifact_id": artifact_id, "role": role, "produced_by": produced_by},
    )


async def get_artifact_by_id(
    conn: AsyncConnection, artifact_id: uuid.UUID
) -> StoredArtifact | None:
    """Fetch by id and re-verify the digest, like `get_artifact`."""
    sha = (
        await conn.execute(
            text("SELECT sha256 FROM artifacts WHERE id = :id AND deleted_at IS NULL"),
            {"id": artifact_id},
        )
    ).scalar_one_or_none()
    return None if sha is None else await get_artifact(conn, str(sha))


async def load_json(conn: AsyncConnection, artifact_id: uuid.UUID) -> Any:
    """Parsed content of a verified qc-json-v1 artifact; None when it is missing."""
    artifact = await get_artifact_by_id(conn, artifact_id)
    return None if artifact is None else json.loads(artifact.content)
