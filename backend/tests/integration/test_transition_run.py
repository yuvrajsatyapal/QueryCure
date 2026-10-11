"""transition_run enforces AGENT_SYSTEM §9 in one UPDATE (DATABASE_DESIGN §7). Runs as qc_app."""

import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.core.errors import InvalidStateError
from querycure.db.repositories.runs import transition_run
from querycure.domain.runs import RunOutcome, RunStatus

pytestmark = pytest.mark.integration


async def _run(engine: AsyncEngine, status: str = "queued") -> uuid.UUID:
    async with engine.begin() as conn:
        inv = (
            await conn.execute(
                text(
                    "INSERT INTO investigations (user_id, title, objective, modes) "
                    "VALUES (uuid_generate_v4(), 't', 'o', ARRAY['offline']) RETURNING id"
                )
            )
        ).scalar_one()
        return (  # type: ignore[no-any-return]
            await conn.execute(
                text(
                    "INSERT INTO investigation_runs (investigation_id, run_number, kind, status, "
                    "budget, usage) VALUES (:inv, 1, 'initial', :status, '{}', '{}') RETURNING id"
                ),
                {"inv": inv, "status": status},
            )
        ).scalar_one()


async def test_allowed_transition_returns_previous_status(app_engine: AsyncEngine) -> None:
    run_id = await _run(app_engine)

    async with app_engine.begin() as conn:
        previous = await transition_run(conn, run_id, RunStatus.RUNNING)
        row = (
            await conn.execute(
                text("SELECT status, started_at FROM investigation_runs WHERE id = :id"),
                {"id": run_id},
            )
        ).one()

    assert previous is RunStatus.QUEUED
    assert row.status == "running"
    assert row.started_at is not None


async def test_disallowed_transition_raises_and_changes_nothing(app_engine: AsyncEngine) -> None:
    run_id = await _run(app_engine)

    with pytest.raises(InvalidStateError):
        async with app_engine.begin() as conn:
            await transition_run(conn, run_id, RunStatus.COMPLETED, outcome=RunOutcome.INCONCLUSIVE)

    async with app_engine.connect() as conn:
        status = (
            await conn.execute(
                text("SELECT status FROM investigation_runs WHERE id = :id"), {"id": run_id}
            )
        ).scalar_one()
    assert status == "queued"


async def test_unknown_run_raises(app_engine: AsyncEngine) -> None:
    with pytest.raises(InvalidStateError):
        async with app_engine.begin() as conn:
            await transition_run(conn, uuid.uuid4(), RunStatus.RUNNING)


async def test_completed_requires_outcome_and_sets_finished_at(app_engine: AsyncEngine) -> None:
    run_id = await _run(app_engine, status="running")

    with pytest.raises(ValueError, match="outcome"):
        async with app_engine.begin() as conn:
            await transition_run(conn, run_id, RunStatus.COMPLETED)

    async with app_engine.begin() as conn:
        await transition_run(conn, run_id, RunStatus.COMPLETED, outcome=RunOutcome.INCONCLUSIVE)
        row = (
            await conn.execute(
                text("SELECT outcome, finished_at FROM investigation_runs WHERE id = :id"),
                {"id": run_id},
            )
        ).one()
    assert row.outcome == "inconclusive"
    assert row.finished_at is not None


async def test_outcome_rejected_for_non_completed_target(app_engine: AsyncEngine) -> None:
    run_id = await _run(app_engine, status="running")

    with pytest.raises(ValueError, match="outcome"):
        async with app_engine.begin() as conn:
            await transition_run(conn, run_id, RunStatus.FAILED, outcome=RunOutcome.INCONCLUSIVE)


async def test_concurrent_claims_only_one_wins(app_engine: AsyncEngine) -> None:
    run_id = await _run(app_engine)

    async def claim() -> bool:
        try:
            async with app_engine.begin() as conn:
                await transition_run(conn, run_id, RunStatus.RUNNING)
            return True
        except InvalidStateError:
            return False

    results = await asyncio.gather(*(claim() for _ in range(6)))

    assert results.count(True) == 1
