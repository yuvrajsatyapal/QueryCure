"""Worker presence and operational metrics (OBSERVABILITY §5, 2026-10-18).

Job leases only heartbeat while a job runs, so an idle or dead worker was invisible until the
queue backed up. Every worker now upserts a `worker_heartbeats` row with its source digest
(which code it runs) and marks it stopped on a clean shutdown; the metrics endpoint reports
live workers, model-call outcomes, the free daily allowance, connection use and experiment
failures.
"""

import asyncio
import uuid
from pathlib import Path

import httpx2 as httpx
import psycopg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.api.main import create_app
from querycure.core.config import Settings
from querycure.ops.retention import sweep
from querycure.worker.__main__ import serve
from querycure.worker.heartbeat import WorkerIdentity, beat, mark_stopped, source_digest
from querycure.worker.runner import Worker, WorkerTimings

pytestmark = pytest.mark.integration


def _identity(worker_id: str | None = None) -> WorkerIdentity:
    return WorkerIdentity(
        worker_id=worker_id or f"w-{uuid.uuid4().hex[:8]}",
        source_digest="d" * 64,
        bench_path="docker-network",
        hostname="test-host",
    )


def _row(owner: psycopg.Connection, worker_id: str) -> tuple:
    row = owner.execute(
        "SELECT source_digest, bench_path, last_seen_at, stopped_at, started_at "
        "FROM worker_heartbeats WHERE worker_id = %s AND deleted_at IS NULL",
        (worker_id,),
    ).fetchone()
    assert row is not None
    return row


async def test_beats_upsert_one_row_per_worker_and_stop_marks_it(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    me = _identity()
    await beat(app_engine, me)
    first = _row(owner, me.worker_id)
    await asyncio.sleep(0.01)
    await beat(app_engine, me)
    second = _row(owner, me.worker_id)

    assert first[0] == "d" * 64
    assert first[1] == "docker-network"
    assert second[2] > first[2]  # last_seen_at advanced
    assert second[4] == first[4]  # started_at kept
    count = owner.execute(
        "SELECT count(*) FROM worker_heartbeats WHERE worker_id = %s", (me.worker_id,)
    ).fetchone()
    assert count == (1,)

    await mark_stopped(app_engine, me)
    assert _row(owner, me.worker_id)[3] is not None


async def test_serve_beats_while_running_and_marks_stopped_on_exit(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    me = _identity()
    worker = Worker(
        app_engine, {}, worker_id=me.worker_id,
        timings=WorkerTimings(lease_seconds=4, heartbeat_seconds=0.05, poll_seconds=0.05),
    )  # fmt: skip
    task = asyncio.create_task(serve(worker, app_engine, None, identity=me))
    await asyncio.sleep(0.3)
    running = _row(owner, me.worker_id)
    assert running[3] is None
    await worker.stop()
    await asyncio.wait_for(task, 5)
    assert _row(owner, me.worker_id)[3] is not None


def test_source_digest_names_the_code_and_changes_with_it(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "a.py").write_text("x = 1\n")
    (pkg / "b.py").write_text("y = 2\n")
    (pkg / "notes.txt").write_text("ignored")
    before = source_digest(pkg)

    assert before == source_digest(pkg)
    (pkg / "notes.txt").write_text("still ignored")
    assert before == source_digest(pkg)
    (pkg / "b.py").write_text("y = 3\n")
    assert before != source_digest(pkg)


async def test_metrics_report_workers_models_quota_connections_and_experiments(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    live, gone = _identity("w-live"), _identity("w-gone")
    await beat(app_engine, live)
    await beat(app_engine, gone)
    owner.execute(
        "UPDATE worker_heartbeats SET last_seen_at = now() - interval '10 minutes' "
        "WHERE worker_id = 'w-gone'"
    )
    app = create_app(Settings(_env_file=None), engine=app_engine)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://t"
    ) as client:
        r = await client.get("/api/v1/internal/metrics")
    assert r.status_code == 200
    body = r.text
    assert "qc_workers_alive 1" in body
    assert (
        'qc_worker_last_seen_seconds{bench_path="docker-network",source_digest="dddddddddddd",worker_id="w-live"}'
        in body
    )
    assert "qc_llm_free_requests_today " in body
    assert "qc_llm_daily_request_limit " in body
    assert "qc_db_connections " in body
    assert "qc_db_max_connections " in body
    assert "# TYPE qc_llm_calls_24h gauge" in body
    assert "# TYPE qc_experiments gauge" in body


async def test_retention_removes_long_gone_workers_only(
    app_engine: AsyncEngine, owner: psycopg.Connection, migrated_db: str
) -> None:
    old, recent = _identity(), _identity()
    await beat(app_engine, old)
    await beat(app_engine, recent)
    owner.execute(
        "UPDATE worker_heartbeats SET last_seen_at = now() - interval '40 days' "
        "WHERE worker_id = %s",
        (old.worker_id,),
    )
    from querycure.db.engine import make_engine

    retention = make_engine(migrated_db, set_role="qc_retention")
    try:
        result = await sweep(retention)
    finally:
        await retention.dispose()
    assert result.worker_heartbeats >= 1
    ids = {r[0] for r in owner.execute("SELECT worker_id FROM worker_heartbeats").fetchall()}
    assert old.worker_id not in ids
    assert recent.worker_id in ids


def test_app_cannot_delete_heartbeats(as_app: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_app.execute("DELETE FROM worker_heartbeats")
