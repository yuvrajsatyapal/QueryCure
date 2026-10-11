"""Event emitter (T2.3): gap-free seq in the caller's transaction, NOTIFY, sealing."""

import asyncio
import uuid

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.core.errors import InvalidStateError, RunFinalizedError
from querycure.domain.runs import RunOutcome, RunStatus
from querycure.events.emitter import change_status, emit
from querycure.events.types import NOTIFY_CHANNEL, EventType

pytestmark = pytest.mark.integration


async def new_run(engine: AsyncEngine, status: str = "running") -> uuid.UUID:
    async with engine.begin() as conn:
        inv = (
            await conn.execute(
                text(
                    "INSERT INTO investigations (user_id, title, objective, modes) "
                    "VALUES (uuid_generate_v4(), 't', 'o', ARRAY['offline']) RETURNING id"
                )
            )
        ).scalar_one()
        run_id: uuid.UUID = (
            await conn.execute(
                text(
                    "INSERT INTO investigation_runs (investigation_id, run_number, kind, status, "
                    "budget, usage) VALUES (:inv, 1, 'initial', :s, '{}', '{}') RETURNING id"
                ),
                {"inv": inv, "s": status},
            )
        ).scalar_one()
    return run_id


def seqs(owner: psycopg.Connection, run_id: uuid.UUID) -> list[int]:
    return [
        r[0]
        for r in owner.execute(
            "SELECT seq FROM investigation_events WHERE run_id = %s ORDER BY seq", (run_id,)
        )
    ]


async def test_emit_assigns_increasing_seq(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    run_id = await new_run(app_engine)

    async with app_engine.begin() as conn:
        first = await emit(conn, run_id, EventType.NODE_STARTED, {"node": "intake", "attempt": 1})
        second = await emit(conn, run_id, EventType.NODE_COMPLETED, {"node": "intake"})

    assert (first, second) == (1, 2)
    row = owner.execute(
        "SELECT type, payload FROM investigation_events WHERE run_id = %s AND seq = 1", (run_id,)
    ).fetchone()
    assert row == ("node.started", {"node": "intake", "attempt": 1})


async def test_concurrent_emitters_produce_gap_free_seq(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    run_id = await new_run(app_engine)

    async def one(i: int) -> None:
        async with app_engine.begin() as conn:
            await emit(conn, run_id, EventType.AGENT_SUMMARY, {"agent": "a", "text": str(i)})

    await asyncio.gather(*(one(i) for i in range(25)))

    assert seqs(owner, run_id) == list(range(1, 26))


async def test_rolled_back_emit_leaves_no_gap(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    run_id = await new_run(app_engine)

    async def crash_after_emit() -> None:
        async with app_engine.begin() as conn:
            await emit(conn, run_id, EventType.NODE_STARTED, {"node": "x"})
            raise RuntimeError("node crashed before commit")

    with pytest.raises(RuntimeError):
        await crash_after_emit()
    async with app_engine.begin() as conn:
        seq = await emit(conn, run_id, EventType.NODE_STARTED, {"node": "x"})

    assert seq == 1
    assert seqs(owner, run_id) == [1]


async def test_unknown_run_is_rejected(app_engine: AsyncEngine) -> None:
    with pytest.raises(InvalidStateError):
        async with app_engine.begin() as conn:
            await emit(conn, uuid.uuid4(), EventType.NODE_STARTED, {})


async def test_finalized_run_accepts_only_lifecycle_events(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    run_id = await new_run(app_engine)
    owner.execute(
        "UPDATE investigation_runs SET finalized_at = now(), events_cutoff_seq = 0 WHERE id = %s",
        (run_id,),
    )

    with pytest.raises(RunFinalizedError):
        async with app_engine.begin() as conn:
            await emit(conn, run_id, EventType.FINDING_CREATED, {})
    async with app_engine.begin() as conn:
        seq = await emit(conn, run_id, EventType.REPORT_READY, {"outcome": "inconclusive"})

    assert seq == 1


async def test_emit_notifies_after_commit_only(app_engine: AsyncEngine, migrated_db: str) -> None:
    run_id = await new_run(app_engine)
    listener = await psycopg.AsyncConnection.connect(migrated_db, autocommit=True)
    await listener.execute(f"LISTEN {NOTIFY_CHANNEL}")

    async with app_engine.begin() as conn:
        await emit(conn, run_id, EventType.NODE_STARTED, {"node": "intake"})
        early = [n async for n in listener.notifies(timeout=0.3)]
    late = [n.payload async for n in listener.notifies(timeout=2, stop_after=1)]
    await listener.close()

    assert early == []
    assert late == [str(run_id)]


async def test_change_status_transitions_and_emits_in_one_transaction(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    run_id = await new_run(app_engine)

    async with app_engine.begin() as conn:
        await change_status(conn, run_id, RunStatus.COMPLETED, outcome=RunOutcome.INCONCLUSIVE)

    event = owner.execute(
        "SELECT type, payload FROM investigation_events WHERE run_id = %s", (run_id,)
    ).fetchone()
    assert event == (
        "run.status_changed",
        {"from": "running", "to": "completed", "outcome": "inconclusive"},
    )


async def test_rejected_transition_emits_nothing(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    run_id = await new_run(app_engine, status="completed")

    with pytest.raises(InvalidStateError):
        async with app_engine.begin() as conn:
            await change_status(conn, run_id, RunStatus.RUNNING)

    assert seqs(owner, run_id) == []


async def test_run_event_sink_commits_each_event(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    from querycure.events.emitter import RunEventSink

    run_id = await new_run(app_engine)
    sink = RunEventSink(app_engine, run_id)

    await sink.emit(EventType.NODE_STARTED, {"node": "intake"})
    await sink.emit(EventType.NODE_COMPLETED, {"node": "intake"})

    assert seqs(owner, run_id) == [1, 2]
