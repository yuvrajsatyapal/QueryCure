"""Per-run context handed to nodes (not checkpointed) and the node wrapper."""

import asyncio
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from langgraph.runtime import Runtime
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.agents.services import InspectorFactory
from querycure.agents.state import InvestigationState
from querycure.benchmark.engine import EngineOptions
from querycure.benchmark.measurement_fixtures import ContextOpener, MeasureFn
from querycure.core.errors import BudgetExhaustedError, RunCancelledError
from querycure.core.logging import get_logger
from querycure.domain.investigation import NodeError, RunBudget
from querycure.events.types import EventType
from querycure.llm.rate_limit import LlmGate
from querycure.llm.structured import RetryPolicy
from querycure.llm.types import ChatClient
from querycure.sandbox.provisioner import SandboxProvisioner

log = get_logger(__name__)

REPORT_NODE = "write_report"


@dataclass(frozen=True)
class LlmClients:
    primary: ChatClient
    fallback: ChatClient | None = None


class ToolAllowanceLike(Protocol):
    async def charge(self) -> None: ...


class Guard(Protocol):
    budget: RunBudget

    def tool_allowance(self) -> ToolAllowanceLike: ...
    async def check(self) -> None: ...
    async def charge_llm_call(self) -> None: ...
    async def record_tokens(
        self, *, input_tokens: int | None, output_tokens: int | None
    ) -> None: ...


class EventSink(Protocol):
    async def emit(self, type: EventType, payload: dict[str, Any]) -> None: ...


@dataclass
class RunContext:
    """Everything a node needs that must not live in checkpointed state (clients, keys)."""

    run_id: uuid.UUID
    guard: Guard
    events: EventSink
    attempt: int = 1
    engine: AsyncEngine | None = None
    inspectors: InspectorFactory | None = None
    llm: "LlmClients | None" = None
    llm_retry: RetryPolicy = field(default_factory=RetryPolicy)
    # Free-tier minute window + daily quota, shared by every run in the process (ADR-0016).
    llm_gate: LlmGate | None = None
    # Per-run cap on concurrent LLM calls across parallel branches (AGENT_SYSTEM §6).
    llm_slots: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(3))
    # Mode C (Phase 3): None when the sandbox is not configured for this process.
    sandbox: SandboxProvisioner | None = None
    engine_options: EngineOptions = field(default_factory=EngineOptions)
    # Measurement seam (benchmark.measurement_fixtures): None = the live engine. Evals pass a
    # capturing source (record mode) or a prerecorded fixture source (deterministic replay).
    measure: MeasureFn | None = None
    # Mode C context seam (evals): None = a live sandbox clone (`services.sandbox_inspector`).
    context_inspector: ContextOpener | None = None

    async def before_llm_call(self) -> None:
        """Run budget first, then the provider's free-tier limits."""
        await self.guard.charge_llm_call()
        if self.llm_gate is not None:
            await self.llm_gate.before_call()

    def clients(self) -> "LlmClients":
        if self.llm is None:
            raise RuntimeError("this node needs an LLM client")
        return self.llm

    def db(self) -> AsyncEngine:
        if self.engine is None:
            raise RuntimeError("this node needs the metadata database")
        return self.engine


class NodeFn(Protocol):
    __name__: str

    async def __call__(
        self, state: InvestigationState, runtime: Runtime[RunContext]
    ) -> dict[str, Any]: ...


def guarded(
    name: str, *, agent: str | None = None, terminal: bool = False
) -> Callable[[NodeFn], NodeFn]:
    """Safe point around a node: cancellation/wall-clock check, progress events, and turning
    budget exhaustion or cancellation into a stop_reason that routes to write_report.

    `terminal` marks write_report: it always runs (cancelled and failed runs get partial
    reports too) and skips the guard check, which would otherwise refuse a cancelled run."""

    def wrap(fn: NodeFn) -> NodeFn:
        async def node(state: InvestigationState, runtime: Runtime[RunContext]) -> dict[str, Any]:
            if state.get("stop_reason") is not None and not terminal:
                return {}
            ctx = runtime.context
            started = time.monotonic()
            meta = {"node": name, "agent": agent, "attempt": ctx.attempt}
            try:
                if not terminal:
                    await ctx.guard.check()
                await ctx.events.emit(EventType.NODE_STARTED, meta)
                update = await fn(state, runtime)
            except BudgetExhaustedError as exc:
                error = NodeError(node=name, code=exc.code, message=exc.message, recoverable=False)
                await ctx.events.emit(EventType.ERROR, error.model_dump())
                return {"stop_reason": "budget_exhausted", "errors": [error.model_dump()]}
            except RunCancelledError:
                log.info("run_cancel_observed", run_id=str(ctx.run_id), node=name)
                return {"stop_reason": "cancelled"}
            duration_ms = int((time.monotonic() - started) * 1000)
            # write_report seals the event log (finalize_run); its completion is the
            # lifecycle events run.status_changed / report.ready, not a content event.
            if not terminal:
                await ctx.events.emit(
                    EventType.NODE_COMPLETED, {**meta, "duration_ms": duration_ms}
                )
            return update

        node.__name__ = name
        return node

    return wrap


def unless_stopped(next_node: str) -> Callable[[InvestigationState], str]:
    """Edge router: continue to `next_node`, or go to write_report once a stop is recorded."""

    def route(state: InvestigationState) -> str:
        return REPORT_NODE if state.get("stop_reason") is not None else next_node

    return route
