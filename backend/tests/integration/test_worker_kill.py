"""ROADMAP Phase 2 acceptance #2, literally: SIGKILL a real worker process after the analysis
fan-out checkpoint, start a new one, and the run completes without duplicates.

Uses the offline stub LLM (no model calls) with a per-call delay so the kill lands while the
synthesis call is in flight."""

import asyncio
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import psycopg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.jobs import queue
from tests.integration.test_investigation_graph import create_run, run_row

pytestmark = pytest.mark.integration

BACKEND = Path(__file__).parents[2]


def start_worker(db_url: str) -> subprocess.Popen[bytes]:
    env = {
        **os.environ,
        "DATABASE_URL": db_url,
        "DATABASE_URL_DIRECT": db_url,
        "LLM_PROVIDER": "stub",
        "LLM_STUB_DELAY_SECONDS": "1.5",
        "WORKER_LEASE_SECONDS": "5",
        "WORKER_HEARTBEAT_SECONDS": "1",
        "WORKER_POLL_SECONDS": "0.2",
        "LOG_LEVEL": "WARNING",
    }
    return subprocess.Popen(
        [sys.executable, "-m", "querycure.worker"],
        cwd=BACKEND,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def wait_for(predicate: object, limit: float) -> None:
    deadline = time.monotonic() + limit
    while not predicate():  # type: ignore[operator]
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        time.sleep(0.1)


def counts(owner: psycopg.Connection, run_id: uuid.UUID) -> tuple[int, ...]:
    row = owner.execute(
        "SELECT (SELECT count(*) FROM evidence WHERE run_id = %(r)s), "
        "(SELECT count(DISTINCT id) FROM evidence WHERE run_id = %(r)s), "
        "(SELECT count(*) FROM findings WHERE run_id = %(r)s), "
        "(SELECT count(*) FROM agent_executions WHERE run_id = %(r)s "
        " AND node IN ('query_analyzer', 'index_strategist') AND status = 'succeeded')",
        {"r": run_id},
    ).fetchone()
    assert row is not None
    return tuple(row)


async def test_sigkill_after_fan_out_then_restart_completes_without_duplicates(
    app_engine: AsyncEngine, owner: psycopg.Connection, migrated_db: str
) -> None:
    owner.execute("DELETE FROM jobs")
    run_id = await create_run(app_engine)
    async with app_engine.begin() as conn:
        await queue.enqueue(conn, kind="run_start", run_id=run_id, payload={})

    def synthesis_started() -> bool:
        return (
            owner.execute(
                "SELECT 1 FROM investigation_events WHERE run_id = %s AND type = 'node.started' "
                "AND payload->>'node' = 'synthesize_hypotheses'",
                (run_id,),
            ).fetchone()
            is not None
        )

    first = start_worker(migrated_db)
    try:
        await asyncio.to_thread(wait_for, synthesis_started, 60)
        before = counts(owner, run_id)
        first.send_signal(signal.SIGKILL)  # no cleanup, no lease release
        first.wait(10)
    finally:
        if first.poll() is None:
            first.kill()
    assert run_row(owner, run_id)[0] == "running"
    assert before[3] == 2  # both analysts finished before the kill

    second = start_worker(migrated_db)
    try:
        # The job is marked done after the handler returns; stopping earlier would (by
        # design) leave it to lease expiry.
        await asyncio.to_thread(
            wait_for,
            lambda: (
                owner.execute("SELECT status FROM jobs WHERE run_id = %s", (run_id,)).fetchone()
                == ("done",)
            ),
            60,
        )
    finally:
        second.send_signal(signal.SIGTERM)
        second.wait(10)

    assert run_row(owner, run_id) == ("completed", "unverified_recommendations", None)
    after = counts(owner, run_id)
    assert after == before  # no evidence or findings added, analysts not re-run
    assert after[0] == after[1]  # every evidence row distinct
    statuses = [
        r[0]
        for r in owner.execute(
            "SELECT payload->>'to' FROM investigation_events WHERE run_id = %s "
            "AND type = 'run.status_changed' ORDER BY seq",
            (run_id,),
        )
    ]
    assert statuses == ["running", "queued", "running", "completed"]
    job = owner.execute("SELECT status, attempts FROM jobs WHERE run_id = %s", (run_id,)).fetchone()
    assert job == ("done", 2)
