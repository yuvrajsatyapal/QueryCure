"""BudgetGuard (T2.5): atomic DB-side charges shared by parallel branches; cancellation."""

import asyncio
import uuid

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.agents.budgets import BudgetGuard, default_budget
from querycure.core.config import Profile
from querycure.core.errors import BudgetExhaustedError, RunCancelledError
from querycure.domain.investigation import RunBudget

pytestmark = pytest.mark.integration

SMALL = RunBudget(
    llm_calls=5, total_tokens=1000, tool_calls=4, tool_calls_per_agent=2, wall_clock_seconds=600
)


async def new_run(engine: AsyncEngine) -> uuid.UUID:
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
                    "budget, usage, started_at) "
                    "VALUES (:inv, 1, 'initial', 'running', '{}', '{}', now()) RETURNING id"
                ),
                {"inv": inv},
            )
        ).scalar_one()
    return run_id


def usage(owner: psycopg.Connection, run_id: uuid.UUID) -> dict[str, int]:
    row = owner.execute("SELECT usage FROM investigation_runs WHERE id = %s", (run_id,)).fetchone()
    assert row is not None
    return row[0]  # type: ignore[no-any-return]


def test_profile_defaults_match_agent_system_section_11() -> None:
    local, demo = default_budget(Profile.LOCAL), default_budget(Profile.DEMO)

    assert (local.llm_calls, local.total_tokens, local.tool_calls) == (40, 400_000, 80)
    assert (local.tool_calls_per_agent, local.wall_clock_seconds) == (8, 1200)
    assert (demo.llm_calls, demo.total_tokens, demo.tool_calls) == (20, 150_000, 40)
    assert (demo.tool_calls_per_agent, demo.wall_clock_seconds) == (6, 300)


async def test_llm_calls_stop_at_the_limit(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    run_id = await new_run(app_engine)
    guard = BudgetGuard(app_engine, run_id, SMALL)

    for _ in range(5):
        await guard.charge_llm_call()
    with pytest.raises(BudgetExhaustedError) as info:
        await guard.charge_llm_call()

    assert info.value.details == [{"budget": "llm_calls", "limit": 5}]
    assert usage(owner, run_id)["llm_calls"] == 5


async def test_parallel_branches_cannot_overspend(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    run_id = await new_run(app_engine)
    guards = [BudgetGuard(app_engine, run_id, SMALL) for _ in range(3)]

    async def spend(guard: BudgetGuard) -> int:
        granted = 0
        for _ in range(5):
            try:
                await guard.charge_llm_call()
                granted += 1
            except BudgetExhaustedError:
                pass
        return granted

    granted = await asyncio.gather(*(spend(g) for g in guards))

    assert sum(granted) == 5
    assert usage(owner, run_id)["llm_calls"] == 5


async def test_tokens_are_recorded_and_enforced_on_the_next_call(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    run_id = await new_run(app_engine)
    guard = BudgetGuard(app_engine, run_id, SMALL)

    await guard.charge_llm_call()
    await guard.record_tokens(input_tokens=900, output_tokens=150)

    with pytest.raises(BudgetExhaustedError) as info:
        await guard.charge_llm_call()
    assert info.value.details[0]["budget"] == "total_tokens"
    assert usage(owner, run_id) == {"llm_calls": 1, "input_tokens": 900, "output_tokens": 150}


async def test_tool_calls_have_run_and_per_invocation_limits(app_engine: AsyncEngine) -> None:
    run_id = await new_run(app_engine)
    guard = BudgetGuard(app_engine, run_id, SMALL)

    first = guard.tool_allowance()
    await first.charge()
    await first.charge()
    with pytest.raises(BudgetExhaustedError) as per_agent:
        await first.charge()
    second = guard.tool_allowance()
    await second.charge()
    await second.charge()
    with pytest.raises(BudgetExhaustedError) as per_run:
        await guard.tool_allowance().charge()

    assert per_agent.value.details[0]["budget"] == "tool_calls_per_agent"
    assert per_run.value.details[0]["budget"] == "tool_calls"


async def test_cancellation_is_observed_at_the_next_charge(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    run_id = await new_run(app_engine)
    guard = BudgetGuard(app_engine, run_id, SMALL)
    await guard.charge_llm_call()

    owner.execute(
        "UPDATE investigation_runs SET cancel_requested_at = now() WHERE id = %s", (run_id,)
    )

    with pytest.raises(RunCancelledError):
        await guard.charge_llm_call()
    with pytest.raises(RunCancelledError):
        await guard.check()
    assert usage(owner, run_id)["llm_calls"] == 1


async def test_wall_clock_limit(app_engine: AsyncEngine, owner: psycopg.Connection) -> None:
    run_id = await new_run(app_engine)
    owner.execute(
        "UPDATE investigation_runs SET started_at = now() - interval '11 minutes' WHERE id = %s",
        (run_id,),
    )
    guard = BudgetGuard(app_engine, run_id, SMALL)

    with pytest.raises(BudgetExhaustedError) as info:
        await guard.check()

    assert info.value.details[0]["budget"] == "wall_clock_seconds"


async def test_warning_event_is_emitted_once_at_eighty_percent(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    run_id = await new_run(app_engine)
    guard = BudgetGuard(app_engine, run_id, SMALL)

    for _ in range(5):
        await guard.charge_llm_call()

    events = owner.execute(
        "SELECT payload FROM investigation_events WHERE run_id = %s AND type = 'budget.warning'",
        (run_id,),
    ).fetchall()
    assert [e[0] for e in events] == [{"budget": "llm_calls", "used": 4, "limit": 5}]
