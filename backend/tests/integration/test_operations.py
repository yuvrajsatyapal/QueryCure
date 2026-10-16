"""Phase 5 operations: metrics, stuck-work detection, graceful drain, log correlation, server-side
connection timeouts and the embedded worker's lifecycle."""

import asyncio
import base64
import io
import json
import os
import uuid
from collections.abc import Callable

import httpx2 as httpx
import psycopg
import pytest
import structlog
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.api.main import create_app
from querycure.core.config import Profile, Settings, WorkerMode
from querycure.core.logging import configure_logging, get_logger
from querycure.db.engine import make_engine
from querycure.jobs import queue
from querycure.jobs.queue import Job
from querycure.worker.__main__ import report_stuck_work
from querycure.worker.runner import Worker, WorkerTimings

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _empty_queue(owner: psycopg.Connection) -> None:
    owner.execute("DELETE FROM jobs")
    owner.execute("DELETE FROM rate_limit_buckets")


async def _until(predicate: Callable[[], bool], limit: float = 5.0) -> None:
    async with asyncio.timeout(limit):
        while not predicate():  # noqa: ASYNC110 - polls rows written by the worker
            await asyncio.sleep(0.02)


def _status(owner: psycopg.Connection, job_id: uuid.UUID) -> str:
    row = owner.execute("SELECT status FROM jobs WHERE id = %s", (job_id,)).fetchone()
    assert row is not None
    return str(row[0])


async def test_metrics_are_open_locally_and_token_gated_elsewhere(
    migrated_db: str, owner: psycopg.Connection
) -> None:
    owner.execute(
        "INSERT INTO jobs (kind, payload, status, locked_by, locked_until, attempts) VALUES "
        "('run_start', '{}', 'running', 'w-gone', now() - interval '5 minutes', 2)"
    )
    engine = make_engine(migrated_db, set_role="qc_app")
    demo = Settings(
        _env_file=None, profile=Profile.DEMO, allow_private_targets=False,
        master_key=base64.b64encode(os.urandom(32)).decode(), metrics_token=SecretStr("m-token"),
    )  # fmt: skip
    try:
        for settings, headers, expected in (
            (Settings(_env_file=None), {}, 200),
            (demo, {}, 404),
            (demo, {"Authorization": "Bearer wrong"}, 404),
            (demo, {"Authorization": "Bearer m-token"}, 200),
        ):
            app = create_app(settings, engine=engine)
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="https://t") as client:
                r = await client.get("/api/v1/internal/metrics", headers=headers)
            assert r.status_code == expected, (settings.profile, headers)
            if expected == 200:
                assert r.headers["content-type"].startswith("text/plain; version=0.0.4")
                assert 'qc_jobs{kind="run_start",status="running"} 1' in r.text
                assert 'qc_jobs_lease_expired{kind="run_start"} 1' in r.text
                assert 'qc_jobs_retried{kind="run_start"} 1' in r.text
                assert "qc_run_duration_seconds_count" in r.text or "qc_runs" in r.text
    finally:
        await engine.dispose()


async def test_stuck_work_report_counts_expired_leases_and_orphaned_runs(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    inv = owner.execute(
        "INSERT INTO investigations (user_id, title, objective, modes) VALUES "
        "(uuid_generate_v4(), 't', 'o', ARRAY['offline']) RETURNING id"
    ).fetchone()
    assert inv is not None
    owner.execute(
        "INSERT INTO investigation_runs (investigation_id, run_number, kind, status, budget, "
        "usage, created_at) VALUES (%s, 1, 'initial', 'queued', '{}', '{}', "
        "now() - interval '1 hour')",
        (inv[0],),
    )
    owner.execute(
        "INSERT INTO jobs (kind, payload, status, locked_by, locked_until) VALUES "
        "('run_start', '{}', 'running', 'w-gone', now() - interval '1 minute')"
    )
    counts = await report_stuck_work(app_engine)
    assert counts["expired_leases"] == 1
    assert counts["orphaned_runs"] >= 1


async def test_stop_drains_an_in_flight_job_within_the_grace_period(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    started = asyncio.Event()

    async def slow(job: Job) -> None:
        started.set()
        await asyncio.sleep(0.5)

    async with app_engine.begin() as conn:
        job_id = await queue.enqueue(conn, kind="run_start", payload={})
    assert job_id is not None
    timings = WorkerTimings(
        lease_seconds=5, heartbeat_seconds=0.2, poll_seconds=0.05, shutdown_grace_seconds=3
    )
    worker = Worker(app_engine, {"run_start": slow}, worker_id="drain", timings=timings)
    task = asyncio.create_task(worker.run())
    await asyncio.wait_for(started.wait(), 5)
    await worker.stop()
    await task
    assert _status(owner, job_id) == "done"  # finished during the grace, not abandoned


async def test_job_logs_carry_correlation_ids(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    stream = io.StringIO()
    configure_logging(stream=stream)
    run_id = uuid.uuid4()

    async def handler(job: Job) -> None:
        get_logger("querycure.test").info("inside_the_handler")

    async with app_engine.begin() as conn:
        job_id = await queue.enqueue(conn, kind="run_start", payload={}, run_id=run_id)
    worker = Worker(
        app_engine, {"run_start": handler}, worker_id="corr",
        timings=WorkerTimings(lease_seconds=5, heartbeat_seconds=0.2, poll_seconds=0.05),
    )  # fmt: skip
    task = asyncio.create_task(worker.run())
    try:
        await _until(lambda: _status(owner, job_id) == "done" if job_id else False)
    finally:
        await worker.stop()
        await task
        configure_logging()
    lines = [json.loads(line) for line in stream.getvalue().splitlines() if line.startswith("{")]
    inside = next(line for line in lines if line["event"] == "inside_the_handler")
    assert inside["job_id"] == str(job_id)
    assert inside["run_id"] == str(run_id)
    assert inside["job_kind"] == "run_start"
    assert "job_id" not in structlog.contextvars.get_contextvars()


async def test_metadata_connections_carry_server_side_timeouts(migrated_db: str) -> None:
    engine = make_engine(
        migrated_db, set_role="qc_app", statement_timeout_ms=1500,
        idle_in_transaction_timeout_ms=4000,
    )  # fmt: skip
    try:
        async with engine.connect() as conn:
            statement = (await conn.execute(text("SHOW statement_timeout"))).scalar_one()
            idle = (
                await conn.execute(text("SHOW idle_in_transaction_session_timeout"))
            ).scalar_one()
            with pytest.raises(Exception, match="statement timeout"):
                await conn.execute(text("SELECT pg_sleep(3)"))
    finally:
        await engine.dispose()
    assert (statement, idle) == ("1500ms", "4s")


async def test_embedded_worker_starts_and_stops_with_the_api(
    migrated_db: str, owner: psycopg.Connection
) -> None:
    stream = io.StringIO()
    configure_logging(stream=stream)
    settings = Settings(
        _env_file=None, database_url=SecretStr(migrated_db), worker_mode=WorkerMode.EMBEDDED,
        llm_provider="stub", worker_poll_seconds=0.05,
    )  # fmt: skip
    app = create_app(settings)
    configure_logging(stream=stream)  # create_app configured stdout logging
    try:
        async with app.router.lifespan_context(app):
            await _until(lambda: "worker_started" in stream.getvalue())
    finally:
        configure_logging()
    assert "worker_stopped" in stream.getvalue()
