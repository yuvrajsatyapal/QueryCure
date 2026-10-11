"""Node wrapper and routing (T2.5): budget exhaustion and cancellation route to the report."""

import uuid
from typing import Any

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Send

from querycure.agents.runtime import REPORT_NODE, RunContext, guarded, unless_stopped
from querycure.agents.state import InvestigationState, merge_stop_reason
from querycure.core.errors import BudgetExhaustedError
from tests.unit.agents.fakes import FakeEvents, FakeGuard


def build(nodes_called: list[str]) -> Any:
    @guarded("analyze", agent="query_analyzer")
    async def analyze(state: InvestigationState, runtime: Runtime[RunContext]) -> dict[str, Any]:
        nodes_called.append("analyze")
        await runtime.context.guard.charge_llm_call()
        return {"findings": [{"from": "analyze"}]}

    @guarded("synthesize")
    async def synthesize(state: InvestigationState, runtime: Runtime[RunContext]) -> dict[str, Any]:
        nodes_called.append("synthesize")
        return {}

    @guarded(REPORT_NODE, terminal=True)
    async def write_report(
        state: InvestigationState, runtime: Runtime[RunContext]
    ) -> dict[str, Any]:
        nodes_called.append(REPORT_NODE)
        return {"outcome": "inconclusive" if state.get("stop_reason") else "no_action_needed"}

    graph = StateGraph(InvestigationState, context_schema=RunContext)
    graph.add_node("analyze", analyze)
    graph.add_node("synthesize", synthesize)
    graph.add_node(REPORT_NODE, write_report)
    graph.add_edge(START, "analyze")
    graph.add_conditional_edges(
        "analyze", unless_stopped("synthesize"), ["synthesize", REPORT_NODE]
    )
    graph.add_edge("synthesize", REPORT_NODE)
    graph.add_edge(REPORT_NODE, END)
    return graph.compile()


def ctx(guard: FakeGuard, events: FakeEvents) -> RunContext:
    return RunContext(run_id=uuid.uuid4(), guard=guard, events=events)


async def test_happy_path_runs_every_node_and_emits_progress() -> None:
    called: list[str] = []
    events = FakeEvents()

    result = await build(called).ainvoke({}, context=ctx(FakeGuard(), events))

    assert called == ["analyze", "synthesize", REPORT_NODE]
    assert result["outcome"] == "no_action_needed"
    assert events.types()[:2] == ["node.started", "node.completed"]
    assert events.events[0][1] == {"node": "analyze", "agent": "query_analyzer", "attempt": 1}
    assert "duration_ms" in events.events[1][1]


async def test_budget_exhaustion_skips_to_the_report() -> None:
    called: list[str] = []
    events = FakeEvents()

    result = await build(called).ainvoke({}, context=ctx(FakeGuard(llm_calls=0), events))

    assert called == ["analyze", REPORT_NODE]
    assert result["stop_reason"] == "budget_exhausted"
    assert result["outcome"] == "inconclusive"
    assert result["errors"][0]["code"] == "BUDGET_EXHAUSTED"
    assert "error" in events.types()


async def test_cancellation_stops_before_any_work() -> None:
    called: list[str] = []

    result = await build(called).ainvoke({}, context=ctx(FakeGuard(cancelled=True), FakeEvents()))

    assert called == [REPORT_NODE]  # no analysis, but the partial report is still written
    assert result["stop_reason"] == "cancelled"
    assert result["outcome"] == "inconclusive"


async def test_parallel_branches_that_both_stop_merge_their_reasons() -> None:
    async def fan(state: InvestigationState) -> dict[str, Any]:
        return {}

    def to_branches(state: InvestigationState) -> list[Send]:
        return [Send("budget_branch", state), Send("cancel_branch", state)]

    async def budget_branch(state: InvestigationState) -> dict[str, Any]:
        return {"stop_reason": "budget_exhausted"}

    async def cancel_branch(state: InvestigationState) -> dict[str, Any]:
        return {"stop_reason": "cancelled"}

    graph = StateGraph(InvestigationState)
    graph.add_node("fan", fan)
    graph.add_node("budget_branch", budget_branch)
    graph.add_node("cancel_branch", cancel_branch)
    graph.add_edge(START, "fan")
    graph.add_conditional_edges("fan", to_branches, ["budget_branch", "cancel_branch"])
    graph.add_edge("budget_branch", END)
    graph.add_edge("cancel_branch", END)

    result = await graph.compile().ainvoke({})

    assert result["stop_reason"] == "cancelled"


def test_stop_reason_priority() -> None:
    assert merge_stop_reason(None, "budget_exhausted") == "budget_exhausted"
    assert merge_stop_reason("cancelled", "budget_exhausted") == "cancelled"
    assert merge_stop_reason("budget_exhausted", "cancelled") == "cancelled"
    assert merge_stop_reason("failed", None) == "failed"


async def test_unexpected_errors_propagate_for_job_retry() -> None:
    @guarded("boom")
    async def boom(state: InvestigationState, runtime: Runtime[RunContext]) -> dict[str, Any]:
        raise RuntimeError("db went away")

    graph = StateGraph(InvestigationState, context_schema=RunContext)
    graph.add_node("boom", boom)
    graph.add_edge(START, "boom")
    graph.add_edge("boom", END)

    with pytest.raises(RuntimeError, match="db went away"):
        await graph.compile().ainvoke({}, context=ctx(FakeGuard(), FakeEvents()))


def test_budget_error_details_shape() -> None:
    err = BudgetExhaustedError("x", details=[{"budget": "llm_calls", "limit": 1}])

    assert err.code == "BUDGET_EXHAUSTED"
