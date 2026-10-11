from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PlanNode(BaseModel):
    """A node of an `EXPLAIN (FORMAT JSON)` plan. Times are per loop, as PostgreSQL reports."""

    model_config = ConfigDict(frozen=True)

    id: int
    parent_id: int | None
    locator: str  # JSON pointer into the uploaded document, cited by evidence
    node_type: str
    parent_relationship: str | None = None
    subplan_name: str | None = None
    relation_name: str | None = None
    schema_name: str | None = None
    alias: str | None = None
    index_name: str | None = None
    join_type: str | None = None
    parallel_aware: bool | None = None
    workers_planned: int | None = None
    workers_launched: int | None = None
    startup_cost: float | None = None
    total_cost: float | None = None
    plan_rows: float | None = None
    plan_width: int | None = None
    actual_startup_time_ms: float | None = None
    actual_total_time_ms: float | None = None
    actual_rows: float | None = None
    actual_loops: int | None = None
    filter: str | None = None
    index_cond: str | None = None
    rows_removed_by_filter: float | None = None
    sort_key: list[str] | None = None
    sort_method: str | None = None
    sort_space_used_kb: int | None = None
    sort_space_type: str | None = None
    shared_hit_blocks: int | None = None
    shared_read_blocks: int | None = None
    shared_dirtied_blocks: int | None = None
    shared_written_blocks: int | None = None
    temp_read_blocks: int | None = None
    temp_written_blocks: int | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
    children: list["PlanNode"] = Field(default_factory=list)


class PlanTree(BaseModel):
    model_config = ConfigDict(frozen=True)

    root: PlanNode
    nodes: list[PlanNode]  # preorder; nodes[i].id == i
    analyzed: bool
    has_timing: bool
    has_buffers: bool
    planning_time_ms: float | None = None
    execution_time_ms: float | None = None
