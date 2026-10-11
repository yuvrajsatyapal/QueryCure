"""Invariants on real PostgreSQL 17 captures (provenance: tests/fixtures/plans/README.md)."""

from pathlib import Path

import pytest

from querycure.plans.metrics import compute_metrics
from querycure.plans.parser import parse_plan

FIXTURES = Path(__file__).parents[2] / "fixtures" / "plans"
ANALYZED = ["pg17_canonical_hot_analyze.json", "pg17_join_aggregate_analyze.json"]


@pytest.mark.parametrize("name", ANALYZED)
def test_real_analyzed_plans_parse_with_timing_and_buffers(name: str) -> None:
    tree = parse_plan((FIXTURES / name).read_text())

    assert tree.analyzed
    assert tree.has_timing
    assert tree.has_buffers
    assert tree.execution_time_ms is not None


@pytest.mark.parametrize("name", ANALYZED)
def test_self_times_are_non_negative_and_add_up_to_the_root(name: str) -> None:
    tree = parse_plan((FIXTURES / name).read_text())
    metrics = compute_metrics(tree)

    self_times = [m.self_time_ms for m in metrics]
    assert all(t is not None and t >= 0 for t in self_times)
    root = metrics[0].inclusive_time_ms
    assert root is not None
    # Parallel per-loop averages are rounded by PostgreSQL, so allow a little slack.
    assert sum(t for t in self_times if t is not None) == pytest.approx(root, rel=0.05)


def test_canonical_query_shows_the_injected_problem() -> None:
    tree = parse_plan((FIXTURES / "pg17_canonical_hot_analyze.json").read_text())
    metrics = compute_metrics(tree)

    types = [n.node_type for n in tree.nodes]
    assert types == ["Limit", "Gather Merge", "Sort", "Seq Scan"]
    scan = tree.nodes[3]
    assert scan.relation_name == "orders"
    # 1M rows, 10,013 for customer 1024: almost everything is read and thrown away.
    removed = metrics[3].rows_removed_by_filter_total
    assert removed == pytest.approx(1_000_000 - 10_013, rel=0.01)
    hottest = max(metrics, key=lambda m: m.self_time_ms or 0)
    assert tree.nodes[hottest.node_id].node_type == "Seq Scan"


def test_parallel_nodes_are_not_summed_across_workers() -> None:
    tree = parse_plan((FIXTURES / "pg17_canonical_hot_analyze.json").read_text())
    metrics = compute_metrics(tree)

    scan, gather = tree.nodes[3], tree.nodes[1]
    assert gather.workers_launched == 2
    assert scan.actual_loops == 3
    # Wall-clock inclusive time cannot exceed the whole query's execution time.
    assert metrics[3].inclusive_time_ms is not None
    assert tree.execution_time_ms is not None
    assert metrics[3].inclusive_time_ms <= tree.execution_time_ms


def test_real_plain_explain_has_estimates_only() -> None:
    tree = parse_plan((FIXTURES / "pg17_canonical_plain.json").read_text())
    metrics = compute_metrics(tree)

    assert not tree.analyzed
    assert [n.node_type for n in tree.nodes] == ["Limit", "Gather Merge", "Sort", "Seq Scan"]
    assert all(m.self_time_ms is None for m in metrics)
    assert tree.root.total_cost is not None
