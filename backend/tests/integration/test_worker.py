"""Worker loop (T2.2): dispatch, retry, lease-loss cancellation, reaping, shutdown."""

import asyncio
import uuid
from collections.abc import Callable

import psycopg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.jobs import queue
from querycure.jobs.queue import Job, ReapedJob
from querycure.worker.runner import PermanentJobError, Worker, WorkerTimings

pytestmark = pytest.mark.integration

FAST = WorkerTimings(lease_seconds=2, heartbeat_seconds=0.2, poll_seconds=0.05)


async def _enqueue(engine: AsyncEngine, **kwargs: object) -> uuid.UUID:
    async with engine.begin() as conn:
        job_id = await queue.enqueue(conn, kind="run_start", payload={}, **kwargs)  # type: ignore[arg-type]
    assert job_id is not None
    return job_id


def _status(owner: psycopg.Connection, job_id: uuid.UUID) -> str:
    row = owner.execute("SELECT status FROM jobs WHERE id = %s", (job_id,)).fetchone()
    assert row is not None
    return str(row[0])


async def _until(predicate: Callable[[], bool], limit: float = 5.0) -> None:
    async with asyncio.timeout(limit):
        # Polls database state written by the worker; there is no in-process event to await.
        while not predicate():  # noqa: ASYNC110
            await asyncio.sleep(0.02)


@pytest.fixture(autouse=True)
def _empty_queue(owner: psycopg.Connection) -> None:
    owner.execute("DELETE FROM jobs")


async def test_successful_handler_completes_job(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    seen: list[uuid.UUID] = []

    async def handler(job: Job) -> None:
        seen.append(job.id)

    job_id = await _enqueue(app_engine)
    worker = Worker(app_engine, {"run_start": handler}, worker_id="w1", timings=FAST)
    task = asyncio.create_task(worker.run())
    await _until(lambda: _status(owner, job_id) == "done")
    await worker.stop()
    await task

    assert seen == [job_id]


async def test_crashing_handler_is_retried_then_succeeds(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    calls = 0

    async def flaky(job: Job) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient")

    job_id = await _enqueue(app_engine)
    worker = Worker(app_engine, {"run_start": flaky}, worker_id="w1", timings=FAST)
    task = asyncio.create_task(worker.run())
    await _until(lambda: _status(owner, job_id) == "pending")
    owner.execute("UPDATE jobs SET run_after = now() WHERE id = %s", (job_id,))
    await _until(lambda: _status(owner, job_id) == "done")
    await worker.stop()
    await task

    assert calls == 2
    error = owner.execute("SELECT last_error FROM jobs WHERE id = %s", (job_id,)).fetchone()
    assert error is not None
    assert error[0]["code"] == "HANDLER_ERROR"
    assert "transient" not in str(error[0])  # exception text can carry secrets; never stored


async def test_permanent_error_dead_letters(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    async def bad(job: Job) -> None:
        raise PermanentJobError("RUN_NOT_FOUND")

    job_id = await _enqueue(app_engine)
    worker = Worker(app_engine, {"run_start": bad}, worker_id="w1", timings=FAST)
    task = asyncio.create_task(worker.run())
    await _until(lambda: _status(owner, job_id) == "dead")
    await worker.stop()
    await task


async def test_unknown_kind_dead_letters(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    job_id = await _enqueue(app_engine)
    worker = Worker(app_engine, {}, worker_id="w1", timings=FAST)
    task = asyncio.create_task(worker.run())
    await _until(lambda: _status(owner, job_id) == "dead")
    await worker.stop()
    await task


async def test_lost_lease_cancels_the_handler(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def slow(job: Job) -> None:
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    job_id = await _enqueue(app_engine)
    worker = Worker(app_engine, {"run_start": slow}, worker_id="w1", timings=FAST)
    task = asyncio.create_task(worker.run())
    await asyncio.wait_for(started.wait(), 5)
    # Another worker reclaimed the job (e.g. this one stalled past its lease).
    owner.execute("UPDATE jobs SET locked_by = 'other' WHERE id = %s", (job_id,))
    await asyncio.wait_for(cancelled.wait(), 5)
    await worker.stop()
    await task

    assert _status(owner, job_id) == "running"  # still owned by 'other'; untouched by w1


async def test_slots_run_jobs_concurrently(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    running = 0
    peak = 0
    release = asyncio.Event()

    async def handler(job: Job) -> None:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await release.wait()
        running -= 1

    ids = [await _enqueue(app_engine) for _ in range(3)]
    worker = Worker(app_engine, {"run_start": handler}, worker_id="w1", concurrency=3, timings=FAST)
    task = asyncio.create_task(worker.run())
    await _until(lambda: peak == 3)
    release.set()
    await _until(lambda: all(_status(owner, i) == "done" for i in ids))
    await worker.stop()
    await task


async def test_exhausted_crashed_jobs_are_reported(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    reaped: list[ReapedJob] = []
    run_id = uuid.uuid4()

    async def on_reaped(job: ReapedJob) -> None:
        reaped.append(job)

    job_id = await _enqueue(app_engine, run_id=run_id, max_attempts=1)
    owner.execute(
        "UPDATE jobs SET status = 'running', attempts = 1, locked_by = 'dead-worker', "
        "locked_until = now() - interval '1 second' WHERE id = %s",
        (job_id,),
    )
    worker = Worker(app_engine, {}, worker_id="w1", timings=FAST, on_reaped=on_reaped)
    task = asyncio.create_task(worker.run())
    await _until(lambda: len(reaped) == 1)
    await worker.stop()
    await task

    assert reaped[0].run_id == run_id
    assert _status(owner, job_id) == "dead"


async def test_stop_cancels_in_flight_work_and_leaves_lease_to_expire(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    started = asyncio.Event()

    async def slow(job: Job) -> None:
        started.set()
        await asyncio.sleep(30)

    job_id = await _enqueue(app_engine)
    worker = Worker(app_engine, {"run_start": slow}, worker_id="w1", timings=FAST)
    task = asyncio.create_task(worker.run())
    await asyncio.wait_for(started.wait(), 5)
    await worker.stop()
    await asyncio.wait_for(task, 5)

    # Not failed, not completed: another worker reclaims it after the lease expires.
    assert _status(owner, job_id) == "running"
