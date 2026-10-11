from typing import Literal

from pydantic import BaseModel, ConfigDict

from querycure.plans.models import PlanNode, PlanTree

_GATHER = ("Gather", "Gather Merge")


class NodeMetrics(BaseModel):
    """Derived, deterministic numbers. None means "not measurable from this plan", never zero."""

    model_config = ConfigDict(frozen=True)

    node_id: int
    inclusive_time_ms: float | None
    self_time_ms: float | None
    self_time_share: float | None
    total_actual_rows: float | None
    estimate_error_ratio: float | None
    estimate_direction: Literal["under", "over", "exact"] | None
    rows_removed_by_filter_total: float | None
    sort_spilled: bool
    self_shared_hit_blocks: int | None
    self_shared_read_blocks: int | None
    self_temp_read_blocks: int | None
    self_temp_written_blocks: int | None


def _process_counts(tree: PlanTree) -> dict[int, int]:
    """Processes executing each node: workers + leader below a Gather, otherwise 1."""
    counts: dict[int, int] = {}

    def visit(node: PlanNode, processes: int) -> None:
        counts[node.id] = processes
        below = processes
        if node.node_type in _GATHER and node.workers_launched is not None:
            below = node.workers_launched + 1
        for child in node.children:
            visit(child, below)

    visit(tree.root, 1)
    return counts


def _inclusive_time(node: PlanNode, processes: int) -> float | None:
    if node.actual_total_time_ms is None or node.actual_loops is None:
        return None
    # Below a Gather, PostgreSQL averages time over all processes and counts each one as a loop,
    # so dividing the loops by the process count gives wall-clock time rather than CPU sum.
    return node.actual_total_time_ms * node.actual_loops / processes


def _estimate(node: PlanNode) -> tuple[float | None, Literal["under", "over", "exact"] | None]:
    if node.actual_rows is None or node.plan_rows is None:
        return None, None
    actual, planned = node.actual_rows, node.plan_rows
    ratio = max(actual, planned) / max(min(actual, planned), 1.0)
    direction: Literal["under", "over", "exact"] = (
        "under" if actual > planned else "over" if actual < planned else "exact"
    )
    return ratio, direction


def _self_buffer(tree: PlanTree, node: PlanNode, field: str) -> int | None:
    if not tree.has_buffers:
        return None
    own = getattr(node, field) or 0
    children = sum(getattr(child, field) or 0 for child in node.children)
    return max(own - children, 0)


def compute_metrics(tree: PlanTree) -> list[NodeMetrics]:
    processes = _process_counts(tree)
    inclusive = {n.id: _inclusive_time(n, processes[n.id]) for n in tree.nodes}
    root_time = inclusive[tree.root.id]
    result: list[NodeMetrics] = []
    for node in tree.nodes:
        own = inclusive[node.id]
        child_times = [inclusive[c.id] for c in node.children]
        self_time: float | None = None
        if own is not None and all(t is not None for t in child_times):
            self_time = max(own - sum(t for t in child_times if t is not None), 0.0)
        ratio, direction = _estimate(node)
        loops = node.actual_loops
        result.append(
            NodeMetrics(
                node_id=node.id,
                inclusive_time_ms=own,
                self_time_ms=self_time,
                self_time_share=self_time / root_time
                if self_time is not None and root_time
                else None,
                total_actual_rows=node.actual_rows * loops
                if node.actual_rows is not None and loops is not None
                else None,
                estimate_error_ratio=ratio,
                estimate_direction=direction,
                rows_removed_by_filter_total=node.rows_removed_by_filter * loops
                if node.rows_removed_by_filter is not None and loops is not None
                else None,
                sort_spilled=node.sort_space_type == "Disk"
                or "external" in (node.sort_method or "").lower(),
                self_shared_hit_blocks=_self_buffer(tree, node, "shared_hit_blocks"),
                self_shared_read_blocks=_self_buffer(tree, node, "shared_read_blocks"),
                self_temp_read_blocks=_self_buffer(tree, node, "temp_read_blocks"),
                self_temp_written_blocks=_self_buffer(tree, node, "temp_written_blocks"),
            )
        )
    return result
