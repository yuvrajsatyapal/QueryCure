import json
from pathlib import Path

import pytest

from querydoctor.core.errors import InvalidPlanFormatError, PayloadTooLargeError
from querydoctor.plans.parser import parse_plan

FIXTURES = Path(__file__).parents[2] / "fixtures" / "plans"


def load(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_parses_tree_shape_and_preorder_ids() -> None:
    tree = parse_plan(load("synthetic_canonical_seqscan_sort.json"))

    assert [n.node_type for n in tree.nodes] == ["Limit", "Sort", "Seq Scan"]
    assert [n.id for n in tree.nodes] == [0, 1, 2]
    assert tree.root.children[0].children[0].relation_name == "orders"
    assert tree.nodes[2].parent_id == 1


def test_locators_are_json_pointers_into_the_upload() -> None:
    tree = parse_plan(load("synthetic_canonical_seqscan_sort.json"))

    assert [n.locator for n in tree.nodes] == [
        "/0/Plan",
        "/0/Plan/Plans/0",
        "/0/Plan/Plans/0/Plans/0",
    ]


def test_reads_top_level_timings_and_flags() -> None:
    tree = parse_plan(load("synthetic_canonical_seqscan_sort.json"))

    assert tree.analyzed is True
    assert tree.has_timing is True
    assert tree.has_buffers is True
    assert tree.planning_time_ms == 0.25
    assert tree.execution_time_ms == 121.0


def test_node_fields() -> None:
    seq = parse_plan(load("synthetic_canonical_seqscan_sort.json")).nodes[2]

    assert seq.schema_name == "public"
    assert seq.filter == "(customer_id = 1024)"
    assert seq.plan_rows == 500
    assert seq.actual_rows == 5000
    assert seq.actual_loops == 1
    assert seq.total_cost == 900.0


def test_plain_explain_has_no_actuals() -> None:
    tree = parse_plan(load("synthetic_plain_explain.json"))

    assert tree.analyzed is False
    assert tree.has_timing is False
    assert tree.root.actual_rows is None
    assert tree.root.index_name == "orders_pkey"
    assert tree.execution_time_ms is None


def test_timing_off_keeps_rows_but_not_times() -> None:
    tree = parse_plan(load("synthetic_subplan_timing_off.json"))

    assert tree.analyzed is True
    assert tree.has_timing is False
    assert tree.root.actual_total_time_ms is None
    assert tree.nodes[1].parent_relationship == "SubPlan"
    assert tree.nodes[1].subplan_name == "SubPlan 1"


def test_unknown_keys_are_preserved() -> None:
    tree = parse_plan(load("synthetic_plain_explain.json"))

    assert tree.root.extra["Scan Direction"] == "Forward"


def test_accepts_bare_object_and_parsed_json() -> None:
    doc = json.loads(load("synthetic_nested_loop.json"))

    assert parse_plan(doc[0]).root.node_type == "Nested Loop"
    assert parse_plan(doc).root.node_type == "Nested Loop"


@pytest.mark.parametrize(
    "bad",
    [
        "not json",
        "[]",
        "[1, 2]",
        '{"Planning Time": 1}',
        '[{"Plan": {"Total Cost": 1}}]',
        '[{"Plan": {"Node Type": "Seq Scan", "Actual Rows": "many"}}]',
        '[{"Plan": {"Node Type": "Seq Scan", "Plans": {"Node Type": "x"}}}]',
        '[{"Plan": {"Node Type": "Seq Scan"}}, {"Plan": {"Node Type": "Seq Scan"}}]',
    ],
)
def test_malformed_plans_are_rejected(bad: str) -> None:
    with pytest.raises(InvalidPlanFormatError):
        parse_plan(bad)


def test_oversize_upload_is_rejected() -> None:
    padding = " " * (5 * 1024 * 1024)

    with pytest.raises(PayloadTooLargeError):
        parse_plan(load("synthetic_plain_explain.json") + padding)


def test_absurd_nesting_is_rejected() -> None:
    node: dict[str, object] = {"Node Type": "Result"}
    for _ in range(300):
        node = {"Node Type": "Result", "Plans": [node]}

    with pytest.raises(InvalidPlanFormatError, match="deep"):
        parse_plan([{"Plan": node}])


def test_duplicate_keys_are_rejected() -> None:
    doc = '[{"Plan": {"Node Type": "Seq Scan", "Node Type": "Index Scan"}}]'

    with pytest.raises(InvalidPlanFormatError, match="Duplicate"):
        parse_plan(doc)
