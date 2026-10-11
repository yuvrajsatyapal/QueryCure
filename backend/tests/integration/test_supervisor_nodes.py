"""supervisor_plan + synthesize_hypotheses (T2.8) with scripted model output."""

import json
from typing import Any

import psycopg
import pytest
from langchain_core.exceptions import ModelAuthenticationError
from langgraph.runtime import Runtime
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.agents.nodes.supervisor import supervisor_plan, synthesize_hypotheses
from querycure.agents.state import InvestigationState
from tests.fake_llm import ScriptedClient
from tests.integration.run_helpers import add_evidence, context, new_run

pytestmark = pytest.mark.integration

QUERY = {"tables": [{"schema_name": None, "name": "orders"}], "order_by": [], "limit": 20}


def plan_json(agents: list[str]) -> str:
    return json.dumps({"agents": agents, "focus": ["Seq Scan"], "rationale": "because"})


def hypothesis(category: str, confidence: str, ev: str, statement: str = "") -> dict[str, Any]:
    return {
        "statement": statement or f"{category} is the cause",
        "category": category,
        "supporting_evidence": [ev],
        "contradicting_evidence": [],
        "confidence": confidence,
        "uncertainty_notes": "not benchmarked",
        "verification_method": "benchmark",
    }


async def test_plan_drops_ineligible_agents(app_engine: AsyncEngine) -> None:
    run_id = await new_run(app_engine)
    client = ScriptedClient([plan_json(["workload_investigator", "index_strategist"])])
    state: InvestigationState = {"query": QUERY, "modes": ["offline"], "objective": "slow?"}

    update = await supervisor_plan(state, Runtime(context=context(app_engine, run_id, client)))

    assert update["plan"]["agents"] == ["index_strategist"]
    prompt = client.calls[0][1].content
    assert "Eligible analysts: query_analyzer, index_strategist" in prompt


async def test_plan_falls_back_to_every_eligible_agent_when_the_model_fails(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    run_id = await new_run(app_engine)
    client = ScriptedClient([ModelAuthenticationError("bad key")])
    state: InvestigationState = {"query": QUERY, "modes": ["offline"], "objective": "slow?"}

    update = await supervisor_plan(state, Runtime(context=context(app_engine, run_id, client)))

    assert update["plan"]["agents"] == ["query_analyzer", "index_strategist"]
    assert update["errors"][0]["code"] == "AGENT_FAILED"
    assert update["errors"][0]["recoverable"] is True


async def test_no_eligible_analyst_skips_the_model(app_engine: AsyncEngine) -> None:
    run_id = await new_run(app_engine)
    client = ScriptedClient([])

    update = await supervisor_plan(
        {"modes": ["offline"]}, Runtime(context=context(app_engine, run_id, client))
    )

    assert update["plan"] is None
    assert client.calls == []


def findings_state(ids: list[str]) -> InvestigationState:
    return {
        "objective": "Why is it slow?",
        "findings": [
            {
                "agent": "query_analyzer",
                "title": "Row estimates are off",
                "detail": "The scan estimate differs from the actual rows.",
                "severity": "medium",
                "evidence_ids": [ids[0]],
            },
            {
                "agent": "index_strategist",
                "title": "No index on the filter column",
                "detail": "The filter column has no index.",
                "severity": "high",
                "evidence_ids": [ids[1]],
            },
        ],
    }


async def test_disagreeing_analysts_become_separate_ranked_hypotheses(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    run_id = await new_run(app_engine)
    ids = await add_evidence(app_engine, run_id, ["plan_node", "index_def"])
    client = ScriptedClient(
        [
            json.dumps(
                {
                    "hypotheses": [
                        hypothesis("cardinality_misestimate", "medium", ids[0]),
                        hypothesis("missing_index", "high", ids[1]),
                    ],
                    "summary": "Two competing explanations.",
                }
            )
        ]
    )
    ctx = context(app_engine, run_id, client)

    update = await synthesize_hypotheses(findings_state(ids), Runtime(context=ctx))

    assert [h["category"] for h in update["hypotheses"]] == [
        "missing_index",
        "cardinality_misestimate",
    ]
    rows = owner.execute(
        "SELECT rank, category, proposed_by FROM hypotheses WHERE run_id = %s ORDER BY rank",
        (run_id,),
    ).fetchall()
    assert rows == [
        (1, "missing_index", ["index_strategist"]),
        (2, "cardinality_misestimate", ["query_analyzer"]),
    ]
    events = owner.execute(
        "SELECT count(*) FROM investigation_events WHERE run_id = %s "
        "AND type = 'hypothesis.created'",
        (run_id,),
    ).fetchone()
    assert events == (2,)
    prompt = client.calls[0][1].content
    assert "No index on the filter column" in prompt
    assert "<<DATA" in prompt  # findings are fenced too


async def test_rerun_adds_no_hypotheses_or_events(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    run_id = await new_run(app_engine)
    ids = await add_evidence(app_engine, run_id, ["plan_node", "index_def"])
    output = json.dumps(
        {"hypotheses": [hypothesis("missing_index", "high", ids[1])], "summary": "s"}
    )
    state = findings_state(ids)

    await synthesize_hypotheses(
        state, Runtime(context=context(app_engine, run_id, ScriptedClient([output])))
    )
    again = await synthesize_hypotheses(
        state, Runtime(context=context(app_engine, run_id, ScriptedClient([])))
    )

    assert len(again["hypotheses"]) == 1
    counts = owner.execute(
        "SELECT (SELECT count(*) FROM hypotheses WHERE run_id = %(r)s), "
        "(SELECT count(*) FROM investigation_events WHERE run_id = %(r)s "
        "AND type = 'hypothesis.created')",
        {"r": run_id},
    ).fetchone()
    assert counts == (1, 1)


async def test_uncited_hypothesis_is_not_persisted(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    run_id = await new_run(app_engine)
    ids = await add_evidence(app_engine, run_id, ["plan_node", "index_def"])
    output = json.dumps(
        {
            "hypotheses": [
                hypothesis("missing_index", "high", ids[1]),
                hypothesis("lock_contention", "high", "ev_999999999999"),
            ],
            "summary": "s",
        }
    )

    update = await synthesize_hypotheses(
        findings_state(ids), Runtime(context=context(app_engine, run_id, ScriptedClient([output])))
    )

    assert [h["category"] for h in update["hypotheses"]] == ["missing_index"]


async def test_no_action_needed_requires_cited_evidence(app_engine: AsyncEngine) -> None:
    run_id = await new_run(app_engine)
    ids = await add_evidence(app_engine, run_id, ["plan_node", "index_def"])
    output = json.dumps(
        {
            "hypotheses": [],
            "summary": "Index Only Scan; nothing to fix.",
            "no_action_evidence": [ids[0], "ev_999999999999"],
        }
    )

    update = await synthesize_hypotheses(
        findings_state(ids), Runtime(context=context(app_engine, run_id, ScriptedClient([output])))
    )

    assert update["hypotheses"] == []
    assert update["no_action_evidence"] == [ids[0]]


async def test_no_findings_means_no_synthesis_call(app_engine: AsyncEngine) -> None:
    run_id = await new_run(app_engine)
    client = ScriptedClient([])

    update = await synthesize_hypotheses(
        {"findings": []}, Runtime(context=context(app_engine, run_id, client))
    )

    assert update["hypotheses"] == []
    assert client.calls == []
