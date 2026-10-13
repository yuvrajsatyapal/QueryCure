"""The investigation graph (AGENT_SYSTEM §3).

intake → collect_context → supervisor_plan → Send fan-out to the planned analysts →
synthesize_hypotheses → [Mode C] optimization_engineer → approval_gate (interrupt) →
run_experiment → benchmark_auditor → next_round (bounded) → … → write_report. Any recorded
stop (budget, cancellation, invalid input) routes straight to write_report, which always runs.
"""

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from querycure.agents.nodes.analysts import (
    index_strategist_node,
    query_analyzer_node,
    workload_investigator_node,
)
from querycure.agents.nodes.approval_gate import approval_gate
from querycure.agents.nodes.benchmark_auditor import benchmark_auditor
from querycure.agents.nodes.collect_context import collect_context
from querycure.agents.nodes.intake import intake
from querycure.agents.nodes.optimization_engineer import optimization_engineer
from querycure.agents.nodes.optimization_loop import (
    APPROVAL_NODE,
    AUDIT_NODE,
    EXPERIMENT_NODE,
    NEXT_ROUND_NODE,
    OE_NODE,
    next_round,
    route_after_approval,
    route_after_candidates,
    route_after_experiment,
    route_after_next_round,
    route_after_synthesis,
)
from querycure.agents.nodes.run_experiment import run_experiment
from querycure.agents.nodes.supervisor import (
    route_after_plan,
    supervisor_plan,
    synthesize_hypotheses,
)
from querycure.agents.nodes.write_report import write_report
from querycure.agents.runtime import REPORT_NODE, RunContext, unless_stopped
from querycure.agents.state import InvestigationState

ANALYSTS = {
    "query_analyzer": query_analyzer_node,
    "index_strategist": index_strategist_node,
    "workload_investigator": workload_investigator_node,
}


def build_graph() -> StateGraph[InvestigationState, RunContext, Any, Any]:
    graph: StateGraph[InvestigationState, RunContext, Any, Any] = StateGraph(
        InvestigationState, context_schema=RunContext
    )
    graph.add_node("intake", intake)
    graph.add_node("collect_context", collect_context)
    graph.add_node("supervisor_plan", supervisor_plan)
    for name, node in ANALYSTS.items():
        graph.add_node(name, node)
    graph.add_node("synthesize_hypotheses", synthesize_hypotheses)
    graph.add_node(OE_NODE, optimization_engineer)
    graph.add_node(APPROVAL_NODE, approval_gate)
    graph.add_node(EXPERIMENT_NODE, run_experiment)
    graph.add_node(AUDIT_NODE, benchmark_auditor)
    graph.add_node(NEXT_ROUND_NODE, next_round)
    graph.add_node(REPORT_NODE, write_report)

    graph.add_edge(START, "intake")
    graph.add_conditional_edges(
        "intake", unless_stopped("collect_context"), ["collect_context", REPORT_NODE]
    )
    graph.add_conditional_edges(
        "collect_context", unless_stopped("supervisor_plan"), ["supervisor_plan", REPORT_NODE]
    )
    graph.add_conditional_edges("supervisor_plan", route_after_plan, [*ANALYSTS, REPORT_NODE])
    for name in ANALYSTS:
        # All analysts sent in one step finish before synthesis runs once (fan-in).
        graph.add_edge(name, "synthesize_hypotheses")
    graph.add_conditional_edges(
        "synthesize_hypotheses", route_after_synthesis, [OE_NODE, REPORT_NODE]
    )
    graph.add_conditional_edges(OE_NODE, route_after_candidates, [APPROVAL_NODE, REPORT_NODE])
    graph.add_conditional_edges(APPROVAL_NODE, route_after_approval, [EXPERIMENT_NODE, REPORT_NODE])
    graph.add_conditional_edges(
        EXPERIMENT_NODE, unless_stopped(AUDIT_NODE), [AUDIT_NODE, REPORT_NODE]
    )
    graph.add_conditional_edges(AUDIT_NODE, route_after_experiment, [NEXT_ROUND_NODE, REPORT_NODE])
    graph.add_conditional_edges(NEXT_ROUND_NODE, route_after_next_round, [OE_NODE, REPORT_NODE])
    graph.add_edge(REPORT_NODE, END)
    return graph


def compile_graph(
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[InvestigationState, RunContext, Any, Any]:
    return build_graph().compile(checkpointer=checkpointer)
