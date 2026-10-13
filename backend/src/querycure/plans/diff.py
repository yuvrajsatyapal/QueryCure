"""Plan diff (T4.3): structural alignment of two plan trees plus per-node metric deltas.

Deterministic and pure. Roots are always paired. Children are aligned by dynamic programming
over a similarity score: two nodes can pair when they read the same relation (a Seq Scan that
became an Index Scan on `orders` is a *change*), or when they have the same node type and do
not read different relations. Unpaired subtrees are `removed` (only in `from`) or `added` (only
in `to`). Output order is a merged preorder: a pair, then its aligned children; within a gap,
removals come before additions.

The Benchmark Auditor uses `summary.new_indexes_used` to check that a verified index candidate
actually changed the plan (AGENT_SYSTEM §2, `get_plan_diff`).
"""

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict

from querycure.plans.metrics import NodeMetrics, compute_metrics
from querycure.plans.models import PlanNode, PlanTree

DiffStatus = Literal["same", "changed", "added", "removed"]
_COMPARED = (
    "node_type",
    "relation_name",
    "index_name",
    "join_type",
    "index_cond",
    "filter",
    "sort_key",
    "sort_method",
)
_INDEX_SCANS = ("Index Scan", "Index Only Scan", "Bitmap Index Scan")


class MetricDelta(BaseModel):
    model_config = ConfigDict(frozen=True)

    from_value: float | None
    to_value: float | None
    ratio: float | None  # from / to, when both are positive (> 1 means `to` is smaller)


class PlanNodeDiff(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: DiffStatus
    from_id: int | None
    to_id: int | None
    from_locator: str | None
    to_locator: str | None
    node_type_from: str | None
    node_type_to: str | None
    relation: str | None
    index_from: str | None
    index_to: str | None
    depth: int
    changes: list[str]
    metrics: dict[str, MetricDelta]


class PlanDiffSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    same: int
    changed: int
    added: int
    removed: int
    added_node_types: list[str]
    removed_node_types: list[str]
    indexes_used_from: list[str]
    indexes_used_to: list[str]
    new_indexes_used: list[str]
    execution_time_ms: MetricDelta
    planning_time_ms: MetricDelta
    root_total_cost: MetricDelta


class PlanDiff(BaseModel):
    model_config = ConfigDict(frozen=True)

    summary: PlanDiffSummary
    nodes: list[PlanNodeDiff]


def _delta(a: float | None, b: float | None) -> MetricDelta:
    ratio = a / b if a is not None and b is not None and a > 0 and b > 0 else None
    return MetricDelta(from_value=a, to_value=b, ratio=ratio)


def _values(node: PlanNode | None, m: NodeMetrics | None) -> dict[str, float | None]:
    if node is None or m is None:
        return dict.fromkeys(_METRIC_NAMES)
    blocks = (
        None
        if m.self_shared_hit_blocks is None
        else float(m.self_shared_hit_blocks + (m.self_shared_read_blocks or 0))
    )
    return {
        "inclusive_time_ms": m.inclusive_time_ms,
        "self_time_ms": m.self_time_ms,
        "total_actual_rows": m.total_actual_rows,
        "plan_rows": node.plan_rows,
        "actual_loops": None if node.actual_loops is None else float(node.actual_loops),
        "total_cost": node.total_cost,
        "self_shared_blocks": blocks,
        "self_temp_written_blocks": None
        if m.self_temp_written_blocks is None
        else float(m.self_temp_written_blocks),
    }


_METRIC_NAMES = (
    "inclusive_time_ms",
    "self_time_ms",
    "total_actual_rows",
    "plan_rows",
    "actual_loops",
    "total_cost",
    "self_shared_blocks",
    "self_temp_written_blocks",
)


def _score(a: PlanNode, b: PlanNode) -> int:
    """0 = cannot pair. Same relation outranks same node type."""
    if a.relation_name and b.relation_name:
        return 3 + (a.node_type == b.node_type) if a.relation_name == b.relation_name else 0
    if a.relation_name or b.relation_name:
        return 0
    return 2 if a.node_type == b.node_type else 0


def _align(
    left: list[PlanNode], right: list[PlanNode]
) -> list[tuple[PlanNode | None, PlanNode | None]]:
    """Maximum-score order-preserving pairing (LCS with weights)."""
    n, m = len(left), len(right)
    best = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            s = _score(left[i], right[j])
            best[i][j] = max(best[i + 1][j], best[i][j + 1], best[i + 1][j + 1] + s if s else 0)
    out: list[tuple[PlanNode | None, PlanNode | None]] = []
    removed: list[PlanNode] = []
    added: list[PlanNode] = []

    def flush() -> None:
        out.extend((r, None) for r in removed)
        out.extend((None, a) for a in added)
        removed.clear()
        added.clear()

    i = j = 0
    while i < n or j < m:
        if i < n and j < m:
            s = _score(left[i], right[j])
            if s and best[i][j] == best[i + 1][j + 1] + s:
                flush()
                out.append((left[i], right[j]))
                i, j = i + 1, j + 1
                continue
        if i < n and (j >= m or best[i][j] == best[i + 1][j]):
            removed.append(left[i])
            i += 1
        else:
            added.append(right[j])
            j += 1
    flush()
    return out


def diff_plans(before: PlanTree, after: PlanTree) -> PlanDiff:
    m_from = {m.node_id: m for m in compute_metrics(before)}
    m_to = {m.node_id: m for m in compute_metrics(after)}
    nodes: list[PlanNodeDiff] = []

    def emit(a: PlanNode | None, b: PlanNode | None, depth: int, status: DiffStatus) -> None:
        va = _values(a, m_from.get(a.id) if a else None)
        vb = _values(b, m_to.get(b.id) if b else None)
        changes = [f for f in _COMPARED if getattr(a, f) != getattr(b, f)] if a and b else []
        if status == "same" and changes:
            status = "changed"
        nodes.append(
            PlanNodeDiff(
                status=status,
                from_id=a.id if a else None,
                to_id=b.id if b else None,
                from_locator=a.locator if a else None,
                to_locator=b.locator if b else None,
                node_type_from=a.node_type if a else None,
                node_type_to=b.node_type if b else None,
                relation=(a.relation_name if a else None) or (b.relation_name if b else None),
                index_from=a.index_name if a else None,
                index_to=b.index_name if b else None,
                depth=depth,
                changes=changes,
                metrics={k: _delta(va[k], vb[k]) for k in _METRIC_NAMES},
            )
        )

    def subtree(node: PlanNode, depth: int, side: Literal["from", "to"]) -> None:
        if side == "from":
            emit(node, None, depth, "removed")
        else:
            emit(None, node, depth, "added")
        for child in node.children:
            subtree(child, depth + 1, side)

    def walk(a: PlanNode, b: PlanNode, depth: int) -> None:
        emit(a, b, depth, "same")
        for x, y in _align(list(a.children), list(b.children)):
            if x is not None and y is not None:
                walk(x, y, depth + 1)
            elif x is not None:
                subtree(x, depth + 1, "from")
            elif y is not None:
                subtree(y, depth + 1, "to")

    walk(before.root, after.root, 0)

    def types(pick: Callable[[PlanNodeDiff], str | None], status: DiffStatus) -> list[str]:
        return sorted({t for n in nodes if n.status == status and (t := pick(n)) is not None})

    def indexes(tree: PlanTree) -> list[str]:
        return sorted(
            {n.index_name for n in tree.nodes if n.index_name and n.node_type in _INDEX_SCANS}
        )

    used_from, used_to = indexes(before), indexes(after)
    count = {
        s: sum(1 for n in nodes if n.status == s) for s in ("same", "changed", "added", "removed")
    }
    return PlanDiff(
        summary=PlanDiffSummary(
            same=count["same"],
            changed=count["changed"],
            added=count["added"],
            removed=count["removed"],
            added_node_types=types(lambda n: n.node_type_to, "added"),
            removed_node_types=types(lambda n: n.node_type_from, "removed"),
            indexes_used_from=used_from,
            indexes_used_to=used_to,
            new_indexes_used=sorted(set(used_to) - set(used_from)),
            execution_time_ms=_delta(before.execution_time_ms, after.execution_time_ms),
            planning_time_ms=_delta(before.planning_time_ms, after.planning_time_ms),
            root_total_cost=_delta(before.root.total_cost, after.root.total_cost),
        ),
        nodes=nodes,
    )
