"""Agent runner (T2.7): citation retry threshold, persistence, idempotent reuse."""

import json
import uuid

import psycopg
import pytest
from langchain_core.exceptions import ModelRateLimitError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.agents.agent_runner import AgentFailedError, run_agent
from querycure.agents.budgets import BudgetGuard
from querycure.agents.outputs import AgentAnalysis, judge_analysis
from querycure.agents.runtime import LlmClients, RunContext
from querycure.core.errors import BudgetExhaustedError
from querycure.domain.investigation import Evidence, RunBudget
from querycure.events.emitter import RunEventSink
from querycure.evidence.ids import evidence_id
from querycure.evidence.store import record_evidence
from querycure.llm.structured import RetryPolicy
from querycure.llm.types import ChatMessage
from tests.fake_llm import ScriptedClient

pytestmark = pytest.mark.integration

BUDGET = RunBudget(
    llm_calls=10,
    total_tokens=100_000,
    tool_calls=10,
    tool_calls_per_agent=5,
    wall_clock_seconds=600,
)
PROMPT = [ChatMessage(role="system", content="analyst"), ChatMessage(role="user", content="go")]


async def setup(engine: AsyncEngine, budget: RunBudget = BUDGET) -> tuple[RunContext, list[str]]:
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
    items = [
        Evidence(
            id=evidence_id(run_id, "plan_node", None, f"/n/{i}"),
            kind="plan_node",
            artifact_sha256=None,
            locator=f"/n/{i}",
            summary=f"node {i}",
            data={},
            provenance="imported",
        )
        for i in range(2)
    ]
    ids = await record_evidence(engine, run_id, items)
    ctx = RunContext(
        run_id=run_id,
        guard=BudgetGuard(engine, run_id, budget),
        events=RunEventSink(engine, run_id),
        engine=engine,
    )
    return ctx, ids


def analysis(*cited: list[str], summary: str = "s") -> str:
    return json.dumps(
        {
            "summary": summary,
            "findings": [
                {"title": f"f{i}", "detail": "d", "severity": "high", "evidence_ids": ids}
                for i, ids in enumerate(cited)
            ],
        }
    )


async def invoke(ctx: RunContext, client: ScriptedClient, key: str = "qa:1") -> object:
    ctx.llm = LlmClients(primary=client)
    return await run_agent(
        ctx,
        agent="query_analyzer",
        node="query_analyzer",
        invocation_key=key,
        prompt_version="query_analyzer@1",
        messages=PROMPT,
        output_type=AgentAnalysis,
        judge=judge_analysis,
    )


def executions(owner: psycopg.Connection, run_id: uuid.UUID) -> list[tuple[object, ...]]:
    return owner.execute(
        "SELECT attempt, status, prompt_version, model, input_tokens, error->>'code', "
        "output_artifact_id IS NOT NULL FROM agent_executions WHERE run_id = %s ORDER BY attempt",
        (run_id,),
    ).fetchall()


async def test_cited_output_is_accepted_and_recorded(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    ctx, ids = await setup(app_engine)

    result = await invoke(ctx, ScriptedClient([analysis([ids[0]], [ids[1]])]))

    assert [f.evidence_ids for f in result.output.findings] == [[ids[0]], [ids[1]]]  # type: ignore[attr-defined]
    assert executions(owner, ctx.run_id) == [
        (1, "succeeded", "query_analyzer@1", "fake-1", 100, None, True)
    ]
    usage = owner.execute(
        "SELECT usage FROM investigation_runs WHERE id = %s", (ctx.run_id,)
    ).fetchone()
    assert usage == ({"llm_calls": 1, "input_tokens": 100, "output_tokens": 20},)
    role = owner.execute(
        "SELECT produced_by FROM run_artifacts WHERE run_id = %s AND role = 'output.agent'",
        (ctx.run_id,),
    ).fetchone()
    assert role == ("query_analyzer",)


async def test_mostly_uncited_output_is_retried_once_with_the_problems(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    ctx, ids = await setup(app_engine)
    client = ScriptedClient(
        [analysis(["ev_000000000000"], [], [ids[0]]), analysis([ids[0]], [ids[1]])]
    )

    result = await invoke(ctx, client)

    assert len(result.output.findings) == 2  # type: ignore[attr-defined]
    feedback = next(
        m.content
        for m in client.calls[1]
        if m.role == "user" and "could not be checked" in m.content
    )
    assert "ev_000000000000" in feedback
    assert "does not exist" in feedback
    rows = executions(owner, ctx.run_id)
    assert [(r[0], r[1], r[5]) for r in rows] == [
        (1, "invalid_output", "UNCITED_CLAIMS"),
        (2, "succeeded", None),
    ]


async def test_second_failure_keeps_only_the_cited_claims(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    ctx, ids = await setup(app_engine)
    bad = analysis([], ["ev_000000000000"], [ids[0]])
    client = ScriptedClient([bad, bad])

    result = await invoke(ctx, client)

    assert [f.evidence_ids for f in result.output.findings] == [[ids[0]]]  # type: ignore[attr-defined]
    assert result.report.removed == 2  # type: ignore[attr-defined]
    assert [r[1] for r in executions(owner, ctx.run_id)] == ["invalid_output", "succeeded"]


async def test_exactly_half_removed_is_not_retried(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    ctx, ids = await setup(app_engine)

    await invoke(ctx, ScriptedClient([analysis([ids[0]], [])]))

    assert [r[1] for r in executions(owner, ctx.run_id)] == ["succeeded"]


async def test_rerun_after_a_crash_reuses_the_stored_output_without_calling_the_model(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    ctx, ids = await setup(app_engine)
    first = await invoke(ctx, ScriptedClient([analysis([ids[0]])]))

    empty = ScriptedClient([])
    second = await invoke(ctx, empty)

    assert empty.calls == []
    assert second.reused is True  # type: ignore[attr-defined]
    assert second.output == first.output  # type: ignore[attr-defined]
    assert len(executions(owner, ctx.run_id)) == 1


async def test_provider_outage_fails_the_agent_but_records_the_calls(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    ctx, _ = await setup(app_engine)
    client = ScriptedClient([ModelRateLimitError("429")] * 4)

    ctx.llm_retry = RetryPolicy(backoff_base=0.0, jitter_seconds=0.0)

    with pytest.raises(AgentFailedError) as info:
        await invoke(ctx, client)

    assert info.value.details == [{"code": "LLM_UNAVAILABLE", "cause": "LLM_RATE_LIMITED"}]
    rows = executions(owner, ctx.run_id)
    assert [r[1] for r in rows] == ["failed"] * 4
    assert {r[5] for r in rows} == {"LLM_RATE_LIMITED"}


async def test_budget_exhaustion_propagates_before_any_call(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    tiny = BUDGET.model_copy(update={"llm_calls": 1})
    ctx, ids = await setup(app_engine, tiny)
    await invoke(ctx, ScriptedClient([analysis([ids[0]])]), key="qa:1")

    client = ScriptedClient([analysis([ids[0]])])
    with pytest.raises(BudgetExhaustedError):
        await invoke(ctx, client, key="is:1")

    assert client.calls == []
    assert len(executions(owner, ctx.run_id)) == 1
