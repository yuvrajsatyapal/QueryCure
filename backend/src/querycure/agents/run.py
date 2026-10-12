"""Execute (or resume) one investigation run inside a worker job."""

import asyncio
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.runnables import RunnableConfig
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.agents.budgets import BudgetGuard
from querycure.agents.checkpointer import open_checkpointer
from querycure.agents.graph import compile_graph
from querycure.agents.runtime import LlmClients, RunContext
from querycure.agents.services import GatewayInspectorFactory
from querycure.agents.state import InvestigationState
from querycure.core.config import Settings
from querycure.core.errors import ConfigurationError
from querycure.core.logging import get_logger
from querycure.db.repositories.investigations import RunInputs, get_run_inputs
from querycure.db.repositories.runs import get_run_status
from querycure.domain.investigation import RunBudget
from querycure.domain.runs import TERMINAL_STATUSES, RunStatus
from querycure.events.emitter import RunEventSink, change_status
from querycure.llm.credentials import resolve_api_key
from querycure.llm.providers import build_client
from querycure.llm.rate_limit import LlmGate
from querycure.llm.structured import RetryPolicy
from querycure.llm.stub import StubClient

log = get_logger(__name__)

ClientsFactory = Callable[[RunInputs], LlmClients]


def env_clients(settings: Settings) -> ClientsFactory:
    """Local profile: the configured provider with the env key (resolved per run)."""

    def make(inputs: RunInputs) -> LlmClients:
        if settings.llm_provider == "stub":
            return LlmClients(primary=StubClient(settings.llm_stub_delay_seconds))
        key = resolve_api_key(settings, settings.llm_provider)
        primary = build_client(settings.llm_provider, settings.llm_model, key, settings=settings)
        fallback = (
            build_client(settings.llm_provider, settings.llm_fallback_model, key, settings=settings)
            if settings.llm_fallback_model
            else None
        )
        return LlmClients(primary=primary, fallback=fallback)

    return make


@dataclass
class RunServices:
    engine: AsyncEngine
    settings: Settings
    checkpoint_url: str
    clients: ClientsFactory
    llm_gate: LlmGate | None = None  # one per process: free-tier limits span every run
    checkpoint_role: str | None = None  # tests only


async def fail_run(engine: AsyncEngine, run_id: uuid.UUID, error: dict[str, Any]) -> None:
    """Terminal failure outside the graph (dead-lettered job, missing configuration)."""
    async with engine.begin() as conn:
        status = await get_run_status(conn, run_id)
        if status is None or status in TERMINAL_STATUSES:
            return
        await conn.execute(
            text("UPDATE investigation_runs SET error = CAST(:e AS JSONB) WHERE id = :id"),
            {"id": run_id, "e": json.dumps(error)},
        )
        if status is RunStatus.CANCELLING or status is RunStatus.AWAITING_APPROVAL:
            await change_status(conn, run_id, RunStatus.CANCELLED)
        else:
            await change_status(conn, run_id, RunStatus.FAILED)


async def _start(engine: AsyncEngine, run_id: uuid.UUID, *, reclaimed: bool) -> RunStatus | None:
    async with engine.begin() as conn:
        status = await get_run_status(conn, run_id)
        if status is None or status in TERMINAL_STATUSES:
            return status
        if status is RunStatus.RUNNING and reclaimed:
            # The previous worker's lease expired: record the hand-over (AGENT_SYSTEM §9).
            await change_status(conn, run_id, RunStatus.QUEUED)
            status = RunStatus.QUEUED
        if status is RunStatus.QUEUED:
            await change_status(conn, run_id, RunStatus.RUNNING)
            status = RunStatus.RUNNING
    return status


async def execute_run(
    services: RunServices, run_id: uuid.UUID, *, attempt: int, reclaimed: bool
) -> None:
    engine = services.engine
    status = await _start(engine, run_id, reclaimed=reclaimed)
    if status is None or status in TERMINAL_STATUSES:
        log.info("run_already_finished", run_id=str(run_id))
        return

    async with engine.connect() as conn:
        inputs = await get_run_inputs(conn, run_id)
        budget_raw = (
            await conn.execute(
                text("SELECT budget FROM investigation_runs WHERE id = :id"), {"id": run_id}
            )
        ).scalar_one()
    try:
        clients = services.clients(inputs)
    except ConfigurationError as exc:
        await fail_run(engine, run_id, {"code": exc.code, "message": exc.message})
        return
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE investigation_runs SET llm_provider = :p, llm_model = :m WHERE id = :id"),
            {"id": run_id, "p": clients.primary.provider, "m": clients.primary.model},
        )

    ctx = RunContext(
        run_id=run_id,
        guard=BudgetGuard(engine, run_id, RunBudget.model_validate(budget_raw)),
        events=RunEventSink(engine, run_id),
        attempt=attempt,
        engine=engine,
        inspectors=GatewayInspectorFactory(engine, services.settings, inputs.user_id),
        llm=clients,
        llm_gate=services.llm_gate,
        llm_retry=RetryPolicy(call_timeout_seconds=services.settings.llm_call_timeout_seconds),
        llm_slots=asyncio.Semaphore(services.settings.llm_max_concurrency),
    )
    config: RunnableConfig = {"configurable": {"thread_id": str(run_id)}}
    async with open_checkpointer(services.checkpoint_url, role=services.checkpoint_role) as saver:
        graph = compile_graph(saver)
        resume = await saver.aget_tuple(config) is not None
        log.info("run_executing", run_id=str(run_id), attempt=attempt, resume=resume)
        # None resumes from the last checkpoint; an empty state starts the graph fresh.
        initial: InvestigationState | None = None if resume else InvestigationState()
        await graph.ainvoke(initial, config, context=ctx)
