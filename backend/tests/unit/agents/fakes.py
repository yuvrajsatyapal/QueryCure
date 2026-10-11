"""In-memory stand-ins for the run context's guard and event sink."""

from typing import Any

from querycure.core.errors import BudgetExhaustedError, RunCancelledError
from querycure.events.types import EventType


class FakeGuard:
    def __init__(self, *, llm_calls: int = 100, cancelled: bool = False) -> None:
        self.remaining = llm_calls
        self.cancelled = cancelled
        self.tokens = 0

    async def check(self) -> None:
        if self.cancelled:
            raise RunCancelledError("cancelled")

    async def charge_llm_call(self) -> None:
        await self.check()
        if self.remaining <= 0:
            raise BudgetExhaustedError(
                "The run's llm_calls budget is exhausted.",
                details=[{"budget": "llm_calls", "limit": 0}],
            )
        self.remaining -= 1

    async def record_tokens(self, *, input_tokens: int | None, output_tokens: int | None) -> None:
        self.tokens += (input_tokens or 0) + (output_tokens or 0)


class FakeEvents:
    def __init__(self) -> None:
        self.events: list[tuple[EventType, dict[str, Any]]] = []

    async def emit(self, type: EventType, payload: dict[str, Any]) -> None:
        self.events.append((type, payload))

    def types(self) -> list[str]:
        return [t.value for t, _ in self.events]
