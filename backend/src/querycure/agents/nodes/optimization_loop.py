"""Routing for the optimization loop (AGENT_SYSTEM §3, BENCHMARK_ENGINE §8 flowchart).

synthesize → optimization_engineer (Mode C with a workload and something to test)
           → approval_gate (candidates exist) → run_experiment (approved)
           → write_report (verified winner) | next_round → optimization_engineer (bounded).
"""

from typing import Any

from langgraph.runtime import Runtime

from querycure.agents.runtime import REPORT_NODE, RunContext, guarded
from querycure.agents.state import InvestigationState
from querycure.domain.runs import ExecutionMode

OE_NODE = "optimization_engineer"
APPROVAL_NODE = "approval_gate"
EXPERIMENT_NODE = "run_experiment"
NEXT_ROUND_NODE = "next_round"


def route_after_synthesis(state: InvestigationState) -> str:
    if state.get("stop_reason") is not None:
        return REPORT_NODE
    sandbox = ExecutionMode.SANDBOX_BENCHMARK.value in state.get("modes", [])
    material = (state.get("materiality") or {}).get("verdict") != "not_material"
    if sandbox and state.get("workload_id") and state.get("hypotheses") and material:
        return OE_NODE
    return REPORT_NODE


def route_after_candidates(state: InvestigationState) -> str:
    if state.get("stop_reason") is not None or not state.get("candidate_keys"):
        return REPORT_NODE
    return APPROVAL_NODE


def route_after_approval(state: InvestigationState) -> str:
    if state.get("stop_reason") is not None:
        return REPORT_NODE
    if state.get("approval_status") in ("approved", "partially_approved"):
        return EXPERIMENT_NODE
    return REPORT_NODE  # declined or expired: unverified recommendations / inconclusive


def route_after_experiment(state: InvestigationState) -> str:
    if state.get("stop_reason") is not None or state.get("winner"):
        return REPORT_NODE
    if state.get("verification") in ("rejected", "inconclusive"):
        return NEXT_ROUND_NODE
    return REPORT_NODE  # failed or not run: another round would hit the same sandbox problem


def route_after_next_round(state: InvestigationState) -> str:
    if state.get("stop_reason") is not None or state.get("rounds_exhausted"):
        return REPORT_NODE
    return OE_NODE


@guarded(NEXT_ROUND_NODE)
async def next_round(state: InvestigationState, runtime: Runtime[RunContext]) -> dict[str, Any]:
    """Bounded by budget.max_optimization_rounds extra rounds (default 2)."""
    current = state.get("optimization_round", 0)
    if current >= runtime.context.guard.budget.max_optimization_rounds:
        return {"rounds_exhausted": True}
    return {
        "optimization_round": current + 1,
        "candidate_keys": [],
        "approval_id": None,
        "approval_status": None,
    }
