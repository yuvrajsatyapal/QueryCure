"""Plan diff (T4.3): structural alignment plus metric deltas, deterministic."""

from pathlib import Path
from typing import Any

import pytest

from querycure.plans.diff import diff_plans
from querycure.plans.parser import parse_plan

FIXTURES = Path(__file__).parents[2] / "fixtures" / "plans"


def node(node_type: str, *children: dict[str, Any], **fields: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"Node Type": node_type, **fields}
    if children:
        out["Plans"] = [{"Parent Relationship": "Outer", **c} for c in children]
    return out


def analyzed(root: dict[str, Any], execution_ms: float = 10.0) -> list[dict[str, Any]]:
    return [{"Plan": root, "Planning Time": 0.1, "Execution Time": execution_ms}]


def timed(total: float, rows: float = 1, loops: int = 1) -> dict[str, Any]:
    return {
        "Actual Startup Time": 0.0,
        "Actual Total Time": total,
        "Actual Rows": rows,
        "Actual Loops": loops,
        "Plan Rows": rows,
        "Total Cost": 10.0,
    }


def rel(name: str, index: str | None = None) -> dict[str, Any]:
    return {"Relation Name": name, **({"Index Name": index} if index else {})}


SEQ_SORT = analyzed(
    node(
        "Limit",
        node("Sort", node("Seq Scan", **timed(100.0, 5000), **rel("orders")), **timed(120.0, 20)),
        **timed(120.5, 20),
    ),
    execution_ms=121.0,
)
INDEX = analyzed(
    node(
        "Limit",
        node("Index Scan", **timed(0.2, 20), **rel("orders", "orders_customer_id_created_at_idx")),
        **timed(0.3, 20),
    ),
    execution_ms=0.4,
)


def test_identical_plans_are_all_same() -> None:
    plan = parse_plan((FIXTURES / "synthetic_canonical_seqscan_sort.json").read_text())

    diff = diff_plans(plan, plan)

    assert [n.status for n in diff.nodes] == ["same", "same", "same"]
    assert (diff.summary.added, diff.summary.removed, diff.summary.changed) == (0, 0, 0)
    assert diff.summary.new_indexes_used == []
    assert diff.nodes[2].metrics["inclusive_time_ms"].from_value == pytest.approx(100.0)
    assert diff.nodes[2].metrics["inclusive_time_ms"].to_value == pytest.approx(100.0)


def test_sort_and_seq_scan_replaced_by_an_index_scan() -> None:
    diff = diff_plans(parse_plan(SEQ_SORT), parse_plan(INDEX))

    assert [(n.status, n.node_type_from, n.node_type_to) for n in diff.nodes] == [
        ("same", "Limit", "Limit"),
        ("removed", "Sort", None),
        ("removed", "Seq Scan", None),
        ("added", None, "Index Scan"),
    ]
    assert diff.summary.new_indexes_used == ["orders_customer_id_created_at_idx"]
    assert diff.summary.removed_node_types == ["Seq Scan", "Sort"]
    assert diff.summary.added_node_types == ["Index Scan"]
    assert diff.summary.execution_time_ms.from_value == pytest.approx(121.0)
    assert diff.summary.execution_time_ms.to_value == pytest.approx(0.4)


def test_scan_on_the_same_relation_is_a_change_not_a_replacement() -> None:
    before = analyzed(node("Limit", node("Seq Scan", **timed(5.0), **rel("t")), **timed(5.1)))
    after = analyzed(
        node("Limit", node("Index Scan", **timed(0.1), **rel("t", "t_idx")), **timed(0.2))
    )

    diff = diff_plans(parse_plan(before), parse_plan(after))

    scan = diff.nodes[1]
    assert scan.status == "changed"
    assert scan.changes == ["node_type", "index_name"]
    assert scan.relation == "t"
    assert scan.metrics["inclusive_time_ms"].ratio == pytest.approx(50.0)
    assert diff.summary.new_indexes_used == ["t_idx"]


def test_index_already_in_the_baseline_is_not_new() -> None:
    plan = analyzed(node("Index Scan", **timed(1.0), **rel("t", "t_pk")))

    diff = diff_plans(parse_plan(plan), parse_plan(plan))

    assert diff.summary.new_indexes_used == []
    assert diff.summary.indexes_used_to == ["t_pk"]


def test_children_are_aligned_by_type_and_relation() -> None:
    before = analyzed(
        node(
            "Hash Join",
            node("Seq Scan", **timed(1.0), **rel("a")),
            node("Hash", node("Seq Scan", **timed(1.0), **rel("b")), **timed(2.0)),
            **timed(4.0),
        )
    )
    after = analyzed(
        node(
            "Hash Join",
            node("Seq Scan", **timed(1.0), **rel("a")),
            node("Hash", node("Index Scan", **timed(0.5), **rel("b", "b_idx")), **timed(1.0)),
            **timed(3.0),
        )
    )

    diff = diff_plans(parse_plan(before), parse_plan(after))

    assert [(n.status, n.node_type_from, n.node_type_to) for n in diff.nodes] == [
        ("same", "Hash Join", "Hash Join"),
        ("same", "Seq Scan", "Seq Scan"),
        ("same", "Hash", "Hash"),
        ("changed", "Seq Scan", "Index Scan"),
    ]
    assert diff.nodes[3].from_locator is not None
    assert diff.nodes[3].to_locator is not None


def test_plain_plans_diff_structurally_without_timing() -> None:
    plain = parse_plan((FIXTURES / "synthetic_plain_explain.json").read_text())

    diff = diff_plans(plain, plain)

    assert all(n.status == "same" for n in diff.nodes)
    assert all(n.metrics["inclusive_time_ms"].from_value is None for n in diff.nodes)
    assert diff.summary.execution_time_ms.from_value is None


def test_diff_is_deterministic() -> None:
    a, b = parse_plan(SEQ_SORT), parse_plan(INDEX)

    assert diff_plans(a, b).model_dump() == diff_plans(a, b).model_dump()
