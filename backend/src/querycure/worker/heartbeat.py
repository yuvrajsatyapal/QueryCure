"""Worker presence (OBSERVABILITY §5): one `worker_heartbeats` row per worker process.

Job leases heartbeat only while a job runs; this row also proves an idle worker is alive and
names the code it runs. `source_digest` is the SHA-256 of the installed `querycure` Python
sources (relative path and bytes, sorted), so after a restart an operator can compare it with
the digest of the checkout that was meant to be deployed, without a git checkout in the image.
"""

import asyncio
import contextlib
import hashlib
import socket
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.core.logging import get_logger

log = get_logger(__name__)
PACKAGE_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class WorkerIdentity:
    worker_id: str
    source_digest: str
    bench_path: str | None
    hostname: str | None


def source_digest(root: Path = PACKAGE_ROOT) -> str:
    h = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        h.update(path.relative_to(root).as_posix().encode() + b"\0")
        h.update(path.read_bytes() + b"\0")
    return h.hexdigest()


def identity(worker_id: str, *, bench_path: str | None) -> WorkerIdentity:
    return WorkerIdentity(
        worker_id=worker_id,
        source_digest=source_digest(),
        bench_path=bench_path,
        hostname=socket.gethostname()[:255] or None,
    )


async def beat(engine: AsyncEngine, me: WorkerIdentity) -> None:
    async with engine.begin() as conn:
        updated = await conn.execute(
            text(
                "UPDATE worker_heartbeats SET last_seen_at = now(), stopped_at = NULL, "
                "source_digest = :digest, bench_path = :path, hostname = :host "
                "WHERE worker_id = :id AND deleted_at IS NULL"
            ),
            {"id": me.worker_id, "digest": me.source_digest, "path": me.bench_path,
             "host": me.hostname},
        )  # fmt: skip
        if updated.rowcount == 0:
            await conn.execute(
                text(
                    "INSERT INTO worker_heartbeats (worker_id, hostname, source_digest, "
                    "bench_path, started_at, last_seen_at) "
                    "VALUES (:id, :host, :digest, :path, now(), now()) "
                    "ON CONFLICT (worker_id) WHERE deleted_at IS NULL "
                    "DO UPDATE SET last_seen_at = now()"
                ),
                {"id": me.worker_id, "digest": me.source_digest, "path": me.bench_path,
                 "host": me.hostname},
            )  # fmt: skip


async def mark_stopped(engine: AsyncEngine, me: WorkerIdentity) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE worker_heartbeats SET stopped_at = now(), last_seen_at = now() "
                "WHERE worker_id = :id AND deleted_at IS NULL"
            ),
            {"id": me.worker_id},
        )


async def heartbeat_loop(
    engine: AsyncEngine, me: WorkerIdentity, stop: asyncio.Event, interval: float
) -> None:
    while not stop.is_set():
        try:
            await beat(engine, me)
        except Exception:
            # A metadata DB outage must not stop the worker; the row just goes stale.
            log.warning("worker_heartbeat_failed", worker_id=me.worker_id, exc_info=True)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), interval)
