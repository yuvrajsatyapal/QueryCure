"""Job queue (T2.2): claim/lease/heartbeat/retry/dead-letter/dedupe, as qc_app."""

import asyncio
import uuid

import psycopg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.jobs import queue

pytestmark = pytest.mark.integration


async def _enqueue(engine: AsyncEngine, **kwargs: object) -> uuid.UUID | None:
    async with engine.begin() as conn:
        return await queue.enqueue(conn, kind="run_start", payload={}, **kwargs)  # type: ignore[arg-type]


async def _claim(engine: AsyncEngine, worker: str, lease: int = 60) -> queue.Job | None:
    async with engine.begin() as conn:
        return await queue.claim(conn, worker_id=worker, lease_seconds=lease)


def _expire_leases(owner: psycopg.Connection) -> None:
    owner.execute(
        "UPDATE jobs SET locked_until = now() - interval '1 second' WHERE status = 'running'"
    )


def _clear(owner: psycopg.Connection) -> None:
    owner.execute("DELETE FROM jobs")


async def test_concurrent_claimers_never_double_execute(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    _clear(owner)
    for _ in range(30):
        await _enqueue(app_engine)

    async def worker(name: str) -> list[uuid.UUID]:
        claimed: list[uuid.UUID] = []
        while (job := await _claim(app_engine, name)) is not None:
            claimed.append(job.id)
            async with app_engine.begin() as conn:
                await queue.complete(conn, job_id=job.id, worker_id=name)
        return claimed

    results = await asyncio.gather(*(worker(f"w{i}") for i in range(6)))

    all_ids = [job_id for ids in results for job_id in ids]
    assert len(all_ids) == 30
    assert len(set(all_ids)) == 30
    done = owner.execute("SELECT count(*) FROM jobs WHERE status = 'done'").fetchone()
    assert done == (30,)


async def test_claim_returns_none_when_empty(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    _clear(owner)

    assert await _claim(app_engine, "w1") is None


async def test_expired_lease_is_reclaimed_by_another_worker(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    _clear(owner)
    await _enqueue(app_engine)
    first = await _claim(app_engine, "crashed")
    assert first is not None
    assert await _claim(app_engine, "w2") is None  # lease still held

    _expire_leases(owner)
    second = await _claim(app_engine, "w2")

    assert second is not None
    assert second.id == first.id
    assert second.attempts == 2
    assert second.reclaimed is True


async def test_heartbeat_extends_only_own_lease(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    _clear(owner)
    await _enqueue(app_engine)
    job = await _claim(app_engine, "w1", lease=5)
    assert job is not None

    async with app_engine.begin() as conn:
        assert await queue.heartbeat(conn, job_id=job.id, worker_id="w1", lease_seconds=60)
        assert not await queue.heartbeat(
            conn, job_id=job.id, worker_id="intruder", lease_seconds=60
        )

    remaining = owner.execute(
        "SELECT extract(epoch FROM locked_until - now()) FROM jobs WHERE id = %s", (job.id,)
    ).fetchone()
    assert remaining is not None
    assert remaining[0] > 30


async def test_worker_that_lost_its_lease_cannot_complete(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    _clear(owner)
    await _enqueue(app_engine)
    stale = await _claim(app_engine, "slow")
    assert stale is not None
    _expire_leases(owner)
    fresh = await _claim(app_engine, "fast")
    assert fresh is not None

    async with app_engine.begin() as conn:
        assert not await queue.complete(conn, job_id=stale.id, worker_id="slow")
        assert not await queue.heartbeat(conn, job_id=stale.id, worker_id="slow", lease_seconds=60)
        assert await queue.complete(conn, job_id=fresh.id, worker_id="fast")


async def test_failure_retries_with_backoff_then_dead_letters(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    _clear(owner)
    await _enqueue(app_engine, max_attempts=2)

    job = await _claim(app_engine, "w1")
    assert job is not None
    async with app_engine.begin() as conn:
        status = await queue.fail(conn, job_id=job.id, worker_id="w1", error={"code": "X"})
    assert status == "pending"
    row = owner.execute(
        "SELECT run_after > now(), last_error->>'code' FROM jobs WHERE id = %s", (job.id,)
    ).fetchone()
    assert row == (True, "X")
    assert await _claim(app_engine, "w1") is None  # backoff not elapsed

    owner.execute("UPDATE jobs SET run_after = now() WHERE id = %s", (job.id,))
    again = await _claim(app_engine, "w1")
    assert again is not None
    assert again.attempts == 2
    async with app_engine.begin() as conn:
        status = await queue.fail(conn, job_id=job.id, worker_id="w1", error={"code": "X"})

    assert status == "dead"


async def test_non_retryable_failure_dead_letters_immediately(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    _clear(owner)
    await _enqueue(app_engine)
    job = await _claim(app_engine, "w1")
    assert job is not None

    async with app_engine.begin() as conn:
        status = await queue.fail(
            conn, job_id=job.id, worker_id="w1", error={"code": "BAD"}, retryable=False
        )

    assert status == "dead"


async def test_crashed_job_out_of_attempts_is_reaped_not_reclaimed(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    _clear(owner)
    run_id = uuid.uuid4()
    await _enqueue(app_engine, run_id=run_id, max_attempts=1)
    assert await _claim(app_engine, "crashed") is not None
    _expire_leases(owner)

    async with app_engine.begin() as conn:
        reaped = await queue.reap_exhausted(conn)
    assert await _claim(app_engine, "w2") is None

    assert [(r.run_id, r.kind) for r in reaped] == [(run_id, "run_start")]
    status = owner.execute("SELECT status FROM jobs WHERE run_id = %s", (run_id,)).fetchone()
    assert status == ("dead",)


async def test_dedupe_key_blocks_duplicate_active_jobs_only(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    _clear(owner)
    first = await _enqueue(app_engine, dedupe_key="resume:abc")
    duplicate = await _enqueue(app_engine, dedupe_key="resume:abc")
    assert first is not None
    assert duplicate is None

    job = await _claim(app_engine, "w1")
    assert job is not None
    async with app_engine.begin() as conn:
        await queue.complete(conn, job_id=job.id, worker_id="w1")

    later = await _enqueue(app_engine, dedupe_key="resume:abc")
    assert later is not None


async def test_jobs_are_claimed_in_run_after_order(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    _clear(owner)
    late = await _enqueue(app_engine)
    early = await _enqueue(app_engine)
    owner.execute("UPDATE jobs SET run_after = now() - interval '1 hour' WHERE id = %s", (early,))

    job = await _claim(app_engine, "w1")

    assert job is not None
    assert job.id == early
    assert late != early
