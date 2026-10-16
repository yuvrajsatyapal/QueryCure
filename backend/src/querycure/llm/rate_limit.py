"""Free-tier request limits (ADR-0016): a per-process minute window and a daily quota.

The daily count comes from `agent_executions` (one row per provider call), so it is shared by
every run and survives restarts. Rows are written as calls finish, so in-flight calls are not
yet counted: the default limit (45) leaves headroom below the provider's 50/day.
"""

import asyncio
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.core.config import FREE_ROUTER
from querycure.core.errors import BudgetExhaustedError

WINDOW_SECONDS = 60.0


class MinuteRateLimiter:
    def __init__(
        self,
        per_minute: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._limit = per_minute
        self._clock = clock
        self._sleep = sleep
        self._sent: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = self._clock()
                while self._sent and now - self._sent[0] >= WINDOW_SECONDS:
                    self._sent.popleft()
                if len(self._sent) < self._limit:
                    self._sent.append(now)
                    return
                await self._sleep(WINDOW_SECONDS - (now - self._sent[0]))


class DailyQuota:
    """Free requests today (UTC). Without `credential_id`: requests made with the server's own
    key (runs without a BYOK credential). With it: requests made with that user's key, which
    has its own provider allowance."""

    def __init__(
        self, engine: AsyncEngine, limit: int, *, credential_id: uuid.UUID | None = None
    ) -> None:
        self._engine = engine
        self.limit = limit
        self.credential_id = credential_id

    async def used_today(self) -> int:
        async with self._engine.connect() as conn:
            count = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM agent_executions e "
                        "JOIN investigation_runs r ON r.id = e.run_id "
                        "WHERE e.created_at >= date_trunc('day', now() AT TIME ZONE 'UTC') "
                        "AT TIME ZONE 'UTC' "
                        # Only requests that went to OpenRouter free models use the allowance.
                        "AND (e.requested_model LIKE :free_suffix "
                        "     OR e.requested_model = :free_router) "
                        "AND r.llm_credential_id IS NOT DISTINCT FROM CAST(:cred AS UUID)"
                    ),
                    {
                        "free_suffix": "%:free",
                        "free_router": FREE_ROUTER,
                        "cred": self.credential_id,
                    },
                )
            ).scalar_one()
        return int(count)

    async def check(self) -> None:
        if await self.used_today() >= self.limit:
            raise BudgetExhaustedError(
                "Today's free model requests are used up; the run stops here.",
                details=[{"budget": "llm_daily_requests", "limit": self.limit}],
            )


class LlmGate:
    """Runs before every provider call, after the run's own budget charge."""

    def __init__(self, limiter: MinuteRateLimiter, quota: DailyQuota | None = None) -> None:
        self._limiter = limiter
        self._quota = quota

    def with_quota(self, quota: DailyQuota) -> "LlmGate":
        """Same minute window (one process, one shared limiter), another daily allowance."""
        return LlmGate(self._limiter, quota)

    async def before_call(self) -> None:
        if self._quota is not None:
            await self._quota.check()
        await self._limiter.acquire()
