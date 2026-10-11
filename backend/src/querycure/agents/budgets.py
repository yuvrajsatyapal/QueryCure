"""Run budgets (AGENT_SYSTEM §11) and the guard that enforces them.

The counters live in `investigation_runs.usage` and every charge is one conditional UPDATE,
so parallel branches share one budget without races, and counts survive a worker crash.
The same statement observes `cancel_requested_at` and the wall-clock limit, which makes
every LLM/tool charge a cancellation point as well.
"""

import math
import uuid
from typing import NoReturn

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from querycure.core.config import Profile
from querycure.core.errors import BudgetExhaustedError, RunCancelledError
from querycure.domain.investigation import RunBudget
from querycure.events.emitter import emit
from querycure.events.types import EventType

WARNING_FRACTION = 0.8

_DEFAULTS = {
    Profile.LOCAL: RunBudget(
        llm_calls=40,
        total_tokens=400_000,
        tool_calls=80,
        tool_calls_per_agent=8,
        wall_clock_seconds=20 * 60,
    ),
    Profile.DEMO: RunBudget(
        llm_calls=20,
        total_tokens=150_000,
        tool_calls=40,
        tool_calls_per_agent=6,
        wall_clock_seconds=5 * 60,
    ),
}


def default_budget(profile: Profile) -> RunBudget:
    return _DEFAULTS[profile]


def _exhausted(budget: str, limit: int) -> BudgetExhaustedError:
    return BudgetExhaustedError(
        f"The run's {budget} budget is exhausted.", details=[{"budget": budget, "limit": limit}]
    )


_CHARGE_LLM = text(
    "UPDATE investigation_runs SET usage = usage || jsonb_build_object("
    "'llm_calls', coalesce((usage->>'llm_calls')::int, 0) + 1) "
    "WHERE id = :id AND cancel_requested_at IS NULL "
    "AND (started_at IS NULL OR now() - started_at < make_interval(secs => :wall)) "
    "AND coalesce((usage->>'llm_calls')::int, 0) < :calls "
    "AND coalesce((usage->>'input_tokens')::int, 0) "
    "+ coalesce((usage->>'output_tokens')::int, 0) < :tokens "
    "RETURNING (usage->>'llm_calls')::int"
)
_CHARGE_TOOL = text(
    "UPDATE investigation_runs SET usage = usage || jsonb_build_object("
    "'tool_calls', coalesce((usage->>'tool_calls')::int, 0) + 1) "
    "WHERE id = :id AND cancel_requested_at IS NULL "
    "AND (started_at IS NULL OR now() - started_at < make_interval(secs => :wall)) "
    "AND coalesce((usage->>'tool_calls')::int, 0) < :tools "
    "RETURNING (usage->>'tool_calls')::int"
)
_RECORD_TOKENS = text(
    "UPDATE investigation_runs SET usage = usage || jsonb_build_object("
    "'input_tokens', coalesce((usage->>'input_tokens')::int, 0) + :input, "
    "'output_tokens', coalesce((usage->>'output_tokens')::int, 0) + :output) "
    "WHERE id = :id "
    "RETURNING (usage->>'input_tokens')::int + (usage->>'output_tokens')::int"
)
_STATE = text(
    "SELECT cancel_requested_at IS NOT NULL AS cancelled, "
    "coalesce(extract(epoch FROM now() - started_at), 0) AS elapsed, "
    "coalesce((usage->>'llm_calls')::int, 0) AS llm_calls, "
    "coalesce((usage->>'tool_calls')::int, 0) AS tool_calls, "
    "coalesce((usage->>'input_tokens')::int, 0) "
    "+ coalesce((usage->>'output_tokens')::int, 0) AS tokens "
    "FROM investigation_runs WHERE id = :id"
)


class ToolAllowance:
    """Tool calls for one agent invocation: a local per-invocation cap plus the run budget."""

    def __init__(self, guard: "BudgetGuard") -> None:
        self._guard = guard
        self.used = 0

    async def charge(self) -> None:
        limit = self._guard.budget.tool_calls_per_agent
        if self.used >= limit:
            raise _exhausted("tool_calls_per_agent", limit)
        await self._guard.charge_tool_call()
        self.used += 1


class BudgetGuard:
    def __init__(self, engine: AsyncEngine, run_id: uuid.UUID, budget: RunBudget) -> None:
        self._engine = engine
        self.run_id = run_id
        self.budget = budget

    def _params(self) -> dict[str, object]:
        b = self.budget
        return {
            "id": self.run_id,
            "wall": b.wall_clock_seconds,
            "calls": b.llm_calls,
            "tokens": b.total_tokens,
            "tools": b.tool_calls,
        }

    async def check(self) -> None:
        """Cancellation and wall-clock check, for safe points between nodes."""
        async with self._engine.connect() as conn:
            await self._raise_if_closed(conn)

    async def charge_llm_call(self) -> None:
        async with self._engine.begin() as conn:
            used = (await conn.execute(_CHARGE_LLM, self._params())).scalar_one_or_none()
            if used is None:
                await self._raise_if_closed(conn)
                await self._raise_exhausted(conn, ("llm_calls", "total_tokens"))
            await self._warn_at_threshold(conn, "llm_calls", used - 1, used, self.budget.llm_calls)

    async def charge_tool_call(self) -> None:
        async with self._engine.begin() as conn:
            used = (await conn.execute(_CHARGE_TOOL, self._params())).scalar_one_or_none()
            if used is None:
                await self._raise_if_closed(conn)
                await self._raise_exhausted(conn, ("tool_calls",))
            await self._warn_at_threshold(
                conn, "tool_calls", used - 1, used, self.budget.tool_calls
            )

    def tool_allowance(self) -> ToolAllowance:
        return ToolAllowance(self)

    async def record_tokens(self, *, input_tokens: int | None, output_tokens: int | None) -> None:
        added = (input_tokens or 0) + (output_tokens or 0)
        if added == 0:
            return
        async with self._engine.begin() as conn:
            total = (
                await conn.execute(
                    _RECORD_TOKENS,
                    {"id": self.run_id, "input": input_tokens or 0, "output": output_tokens or 0},
                )
            ).scalar_one()
            await self._warn_at_threshold(
                conn, "total_tokens", total - added, total, self.budget.total_tokens
            )

    async def _raise_if_closed(self, conn: AsyncConnection) -> None:
        state = (await conn.execute(_STATE, {"id": self.run_id})).one()
        if state.cancelled:
            raise RunCancelledError("The run was cancelled.")
        if state.elapsed >= self.budget.wall_clock_seconds:
            raise _exhausted("wall_clock_seconds", self.budget.wall_clock_seconds)

    async def _raise_exhausted(self, conn: AsyncConnection, budgets: tuple[str, ...]) -> NoReturn:
        state = (await conn.execute(_STATE, {"id": self.run_id})).one()
        used = {"llm_calls": state.llm_calls, "tool_calls": state.tool_calls}
        used["total_tokens"] = state.tokens
        for name in budgets:
            limit = getattr(self.budget, name)
            if used[name] >= limit:
                raise _exhausted(name, limit)
        raise _exhausted(budgets[0], getattr(self.budget, budgets[0]))

    async def _warn_at_threshold(
        self, conn: AsyncConnection, budget: str, before: int, after: int, limit: int
    ) -> None:
        threshold = math.ceil(WARNING_FRACTION * limit)
        if before < threshold <= after:
            await emit(
                conn,
                self.run_id,
                EventType.BUDGET_WARNING,
                {"budget": budget, "used": after, "limit": limit},
            )
