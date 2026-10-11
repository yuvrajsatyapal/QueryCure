"""Shared setup for graph-node integration tests: a running run with some evidence."""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.agents.budgets import BudgetGuard
from querycure.agents.runtime import LlmClients, RunContext
from querycure.domain.investigation import Evidence, EvidenceKind, RunBudget
from querycure.events.emitter import RunEventSink
from querycure.evidence.ids import evidence_id
from querycure.evidence.store import record_evidence
from querycure.llm.structured import RetryPolicy
from querycure.llm.types import ChatClient

BUDGET = RunBudget(
    llm_calls=20,
    total_tokens=200_000,
    tool_calls=20,
    tool_calls_per_agent=8,
    wall_clock_seconds=600,
)
NO_BACKOFF = RetryPolicy(backoff_base=0.0, jitter_seconds=0.0)


async def new_run(engine: AsyncEngine, *, modes: tuple[str, ...] = ("offline",)) -> uuid.UUID:
    async with engine.begin() as conn:
        inv = (
            await conn.execute(
                text(
                    "INSERT INTO investigations (user_id, title, objective, modes) "
                    "VALUES (uuid_generate_v4(), 't', 'Why is it slow?', :modes) RETURNING id"
                ),
                {"modes": list(modes)},
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


async def add_evidence(
    engine: AsyncEngine, run_id: uuid.UUID, kinds: list[EvidenceKind]
) -> list[str]:
    items = [
        Evidence(
            id=evidence_id(run_id, kind, None, f"/e/{i}"),
            kind=kind,
            artifact_sha256=None,
            locator=f"/e/{i}",
            summary=f"{kind} fact {i}",
            data={},
            provenance="imported",
        )
        for i, kind in enumerate(kinds)
    ]
    return await record_evidence(engine, run_id, items)


def context(
    engine: AsyncEngine,
    run_id: uuid.UUID,
    client: ChatClient | None = None,
    budget: RunBudget = BUDGET,
) -> RunContext:
    return RunContext(
        run_id=run_id,
        guard=BudgetGuard(engine, run_id, budget),
        events=RunEventSink(engine, run_id),
        engine=engine,
        llm=LlmClients(primary=client) if client is not None else None,
        llm_retry=NO_BACKOFF,
    )
