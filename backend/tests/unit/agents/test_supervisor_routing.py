"""Supervisor routing and ranking (T2.8): pure functions on state."""

import uuid

from langgraph.types import Send

from querycure.agents.nodes.supervisor import eligible_agents, rank_hypotheses, route_after_plan
from querycure.agents.outputs import HypothesisDraft, HypothesisSet
from querycure.agents.runtime import REPORT_NODE
from querycure.agents.state import InvestigationState
from querycure.domain.investigation import Finding

QUERY = {"tables": [{"schema_name": None, "name": "orders"}], "order_by": [], "limit": None}
STATS = {"has_pg_stat_statements": True, "can_read_all_stats": False}


def test_offline_query_runs_the_query_and_index_analysts() -> None:
    state: InvestigationState = {"query": QUERY, "modes": ["offline"]}

    assert eligible_agents(state) == ["query_analyzer", "index_strategist"]


def test_plan_upload_without_query_runs_only_the_query_analyzer() -> None:
    state: InvestigationState = {"query": None, "plan_sha256": "a" * 64, "modes": ["offline"]}

    assert eligible_agents(state) == ["query_analyzer"]


def test_workload_investigator_needs_live_mode_and_a_workload_capability() -> None:
    live: InvestigationState = {"query": QUERY, "modes": ["live_inspection"], "capabilities": STATS}
    no_caps: InvestigationState = {
        "query": QUERY,
        "modes": ["live_inspection"],
        "capabilities": {"has_pg_stat_statements": False, "can_read_all_stats": False},
    }
    offline_with_caps: InvestigationState = {
        "query": QUERY,
        "modes": ["offline"],
        "capabilities": STATS,
    }

    assert "workload_investigator" in eligible_agents(live)
    assert "workload_investigator" not in eligible_agents(no_caps)
    assert "workload_investigator" not in eligible_agents(offline_with_caps)


def test_nothing_to_analyse_means_no_analysts() -> None:
    assert eligible_agents({"modes": ["offline"]}) == []


def test_route_fans_out_to_exactly_the_planned_agents() -> None:
    state: InvestigationState = {
        "plan": {"agents": ["query_analyzer", "index_strategist"], "focus": [], "rationale": "r"}
    }

    sends = route_after_plan(state)

    assert isinstance(sends, list)
    assert [s.node for s in sends] == ["query_analyzer", "index_strategist"]
    assert all(isinstance(s, Send) for s in sends)


def test_route_goes_to_the_report_on_stop_or_without_a_plan() -> None:
    stopped: InvestigationState = {
        "plan": {"agents": ["query_analyzer"], "focus": [], "rationale": "r"},
        "stop_reason": "budget_exhausted",
    }

    assert route_after_plan(stopped) == REPORT_NODE
    assert route_after_plan({"plan": None}) == REPORT_NODE


def _draft(category: str, confidence: str, ev: str) -> HypothesisDraft:
    return HypothesisDraft(
        statement=f"{category} explains it",
        category=category,  # type: ignore[arg-type]
        supporting_evidence=[ev],
        confidence=confidence,  # type: ignore[arg-type]
        uncertainty_notes="",
        verification_method="benchmark",
    )


def test_ranking_is_by_confidence_then_model_order_with_stable_keys() -> None:
    run_id = uuid.uuid4()
    output = HypothesisSet(
        hypotheses=[
            _draft("cardinality_misestimate", "medium", "ev_aaaaaaaaaaaa"),
            _draft("missing_index", "high", "ev_bbbbbbbbbbbb"),
            _draft("inefficient_sort", "medium", "ev_cccccccccccc"),
        ],
        summary="s",
    )
    findings = [
        Finding(
            agent="index_strategist",
            title="t",
            detail="d",
            severity="high",
            evidence_ids=["ev_bbbbbbbbbbbb"],
        ),
        Finding(
            agent="query_analyzer",
            title="t",
            detail="d",
            severity="medium",
            evidence_ids=["ev_aaaaaaaaaaaa", "ev_bbbbbbbbbbbb"],
        ),
    ]

    ranked = rank_hypotheses(run_id, 0, output, findings)
    again = rank_hypotheses(run_id, 0, output, findings)

    assert [h.category for h in ranked] == [
        "missing_index",
        "cardinality_misestimate",
        "inefficient_sort",
    ]
    assert [h.rank for h in ranked] == [1, 2, 3]
    assert [h.key for h in ranked] == [h.key for h in again]
    assert ranked[0].proposed_by == ["index_strategist", "query_analyzer"]
    assert ranked[1].proposed_by == ["query_analyzer"]
    assert ranked[2].proposed_by == ["supervisor"]  # no analyst cited that evidence
