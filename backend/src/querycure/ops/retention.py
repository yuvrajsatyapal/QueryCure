"""Retention sweep for operational rows (Phase 5). Runs as `qc_retention`, the only role that
may DELETE; the app role `qc_app` cannot, by design (DATABASE_DESIGN, grant tests).

Only data that is pure bookkeeping is removed: long-expired or revoked sessions, rate-limit
buckets idle for a day (a fresh bucket starts full, so deleting one only forgives), and
credential rows whose ciphertext was already wiped, and worker presence rows not seen for 30
days. Investigations, events, artifacts and
reports are evidence and are never touched here (their retention needs its own design:
replay depends on them).
"""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

SESSION_GRACE_DAYS = 7
BUCKET_IDLE_HOURS = 24
WIPED_CREDENTIAL_DAYS = 30
WORKER_GONE_DAYS = 30


@dataclass(frozen=True)
class SweepResult:
    sessions: int
    rate_limit_buckets: int
    wiped_credentials: int
    worker_heartbeats: int = 0


async def sweep(engine: AsyncEngine) -> SweepResult:
    async with engine.begin() as conn:
        sessions = await conn.execute(
            text(
                "DELETE FROM sessions WHERE expires_at < now() - make_interval(days => :d) "
                "OR deleted_at < now() - make_interval(days => :d)"
            ),
            {"d": SESSION_GRACE_DAYS},
        )
        buckets = await conn.execute(
            text(
                "DELETE FROM rate_limit_buckets WHERE refilled_at < now() - "
                "make_interval(hours => :h)"
            ),
            {"h": BUCKET_IDLE_HOURS},
        )
        credentials = await conn.execute(
            text(
                "DELETE FROM llm_credentials WHERE deleted_at < now() - "
                "make_interval(days => :d) AND ciphertext IS NULL"
            ),
            {"d": WIPED_CREDENTIAL_DAYS},
        )
        workers = await conn.execute(
            text(
                "DELETE FROM worker_heartbeats WHERE last_seen_at < now() - "
                "make_interval(days => :d)"
            ),
            {"d": WORKER_GONE_DAYS},
        )
    return SweepResult(
        worker_heartbeats=workers.rowcount,
        sessions=sessions.rowcount,
        rate_limit_buckets=buckets.rowcount,
        wiped_credentials=credentials.rowcount,
    )
