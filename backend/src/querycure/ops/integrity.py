"""Restore verification (DEPLOYMENT §4c): every artifact re-read through the digest check, every
sealed report replayed. One READ ONLY transaction, so it is safe against a restored copy or a
Neon point-in-time branch, and it never writes `replay_attempts` (the API's replay route does)."""

import uuid
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from querycure.replay.artifact_store import ArtifactIntegrityError, get_artifact_by_id
from querycure.replay.report_replay import verify_report

CHUNK_SIZE = 500
MAX_CHUNKS = 10_000  # 5M artifacts: far beyond a 5 MB-per-artifact demo database
VERIFIED = frozenset({"verified", "verified_stored_only"})


@dataclass
class IntegrityResult:
    artifacts_checked: int = 0
    artifact_failures: list[str] = field(default_factory=list)
    reports_checked: int = 0
    report_statuses: dict[str, int] = field(default_factory=dict)
    report_failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.artifact_failures and not self.report_failures


async def _artifacts(conn: AsyncConnection, result: IntegrityResult) -> None:
    last = uuid.UUID(int=0)
    for _ in range(MAX_CHUNKS):
        ids = (
            (
                await conn.execute(
                    text(
                        "SELECT id FROM artifacts WHERE deleted_at IS NULL AND id > :last "
                        "ORDER BY id LIMIT :limit"
                    ),
                    {"last": last, "limit": CHUNK_SIZE},
                )
            )
            .scalars()
            .all()
        )
        for artifact_id in ids:
            result.artifacts_checked += 1
            try:
                await get_artifact_by_id(conn, artifact_id)
            except ArtifactIntegrityError:
                result.artifact_failures.append(str(artifact_id))
        if len(ids) < CHUNK_SIZE:
            return
        last = ids[-1]
    raise RuntimeError(f"more than {MAX_CHUNKS * CHUNK_SIZE} artifacts; raise MAX_CHUNKS")


async def _reports(conn: AsyncConnection, result: IntegrityResult) -> None:
    run_ids = (
        (
            await conn.execute(
                text(
                    "SELECT r.id FROM investigation_runs r "
                    "JOIN replay_manifests m ON m.run_id = r.id "
                    "WHERE r.finalized_at IS NOT NULL AND m.deleted_at IS NULL ORDER BY r.id"
                )
            )
        )
        .scalars()
        .all()
    )
    statuses: Counter[str] = Counter()
    for run_id in run_ids:
        replayed = await verify_report(conn, run_id)
        statuses[replayed.status] += 1
        if replayed.status not in VERIFIED:
            result.report_failures.append(str(run_id))
    result.reports_checked = len(run_ids)
    result.report_statuses = dict(statuses)


async def verify_integrity(engine: AsyncEngine) -> IntegrityResult:
    result = IntegrityResult()
    async with engine.connect() as conn:
        await conn.execute(text("SET TRANSACTION READ ONLY"))
        await _artifacts(conn, result)
        await _reports(conn, result)
        await conn.rollback()
    return result
