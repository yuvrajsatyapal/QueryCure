from pathlib import Path

import pytest

from querydoctor.plans.metrics import compute_metrics
from querydoctor.plans.parser import parse_plan

FIXTURES = Path(__file__).parents[2] / "fixtures" / "plans"


def metrics(name: str):  # type: ignore[no-untyped-def]
    return compute_metrics(parse_plan((FIXTURES / name).read_text()))


def test_self_time_subtracts_children_inclusive_time() -> None:
    m = metrics("synthetic_canonical_seqscan_sort.json")

    # Seq Scan 100 x 1; Sort 120 - 100; Limit 120.5 - 120
    assert m[2].inclusive_time_ms == pytest.approx(100.0)
    assert m[1].self_time_ms == pytest.approx(20.0)
    assert m[0].self_time_ms == pytest.approx(0.5)
    assert m[2].self_time_ms == pytest.approx(100.0)


def test_self_time_share_of_root() -> None:
    m = metrics("synthetic_canonical_seqscan_sort.json")

    assert m[2].self_time_share == pytest.approx(100.0 / 120.5)


def test_loops_multiply_inner_side_of_nested_loop() -> None:
    m = metrics("synthetic_nested_loop.json")

    # inner index scan: 0.15 ms x 100 loops; nested loop self = 20 - (2 + 15)
    assert m[2].inclusive_time_ms == pytest.approx(15.0)
    assert m[0].self_time_ms == pytest.approx(3.0)
    assert m[2].total_actual_rows == 1000


def test_parallel_nodes_divide_loops_by_process_count() -> None:
    m = metrics("synthetic_parallel_gather.json")

    # 2 workers + leader = 3 processes; 3 loops -> one loop per process -> 50 ms wall time
    assert m[1].inclusive_time_ms == pytest.approx(50.0)
    assert m[0].self_time_ms == pytest.approx(10.0)
    assert m[1].total_actual_rows == 3000


def test_estimate_error_is_per_loop_with_direction() -> None:
    canonical = metrics("synthetic_canonical_seqscan_sort.json")
    nested = metrics("synthetic_nested_loop.json")

    assert canonical[2].estimate_error_ratio == pytest.approx(10.0)
    assert canonical[2].estimate_direction == "under"
    assert nested[2].estimate_error_ratio == pytest.approx(10.0)
    assert nested[2].estimate_direction == "under"


def test_overestimate_direction() -> None:
    m = metrics("synthetic_canonical_seqscan_sort.json")

    # Sort: planned 500, actual 20
    assert m[1].estimate_error_ratio == pytest.approx(25.0)
    assert m[1].estimate_direction == "over"


def test_rows_removed_by_filter_total_and_sort_spill() -> None:
    m = metrics("synthetic_canonical_seqscan_sort.json")

    assert m[2].rows_removed_by_filter_total == 995000
    assert m[1].sort_spilled is True
    assert m[2].sort_spilled is False


def test_self_buffers_subtract_children() -> None:
    m = metrics("synthetic_canonical_seqscan_sort.json")

    assert (m[2].self_shared_hit_blocks, m[2].self_shared_read_blocks) == (100, 900)
    assert (m[1].self_shared_hit_blocks, m[1].self_shared_read_blocks) == (0, 0)
    assert (m[1].self_temp_read_blocks, m[1].self_temp_written_blocks) == (50, 50)
    assert m[0].self_temp_written_blocks == 0


def test_plain_explain_metrics_are_unknown_not_zero() -> None:
    m = metrics("synthetic_plain_explain.json")

    assert m[0].inclusive_time_ms is None
    assert m[0].self_time_ms is None
    assert m[0].estimate_error_ratio is None
    assert m[0].self_shared_read_blocks is None


def test_timing_off_still_reports_row_estimates() -> None:
    m = metrics("synthetic_subplan_timing_off.json")

    assert m[0].self_time_ms is None
    assert m[0].estimate_error_ratio == pytest.approx(100.0)


def test_hottest_node_by_self_time() -> None:
    tree = parse_plan((FIXTURES / "synthetic_canonical_seqscan_sort.json").read_text())

    assert max(compute_metrics(tree), key=lambda x: x.self_time_ms or 0).node_id == 2
