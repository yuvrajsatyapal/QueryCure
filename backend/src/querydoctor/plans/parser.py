import json
from typing import Any

from querydoctor.core.errors import InvalidPlanFormatError, PayloadTooLargeError
from querydoctor.plans.models import PlanNode, PlanTree

MAX_PLAN_BYTES = 5 * 1024 * 1024
# Deep join trees nest two JSON levels per plan node, so this is looser than the general 64 limit.
MAX_JSON_DEPTH = 256

# PostgreSQL key -> (field, type). Everything else lands in PlanNode.extra.
_FIELDS: dict[str, tuple[str, type | tuple[type, ...]]] = {
    "Parent Relationship": ("parent_relationship", str),
    "Subplan Name": ("subplan_name", str),
    "Relation Name": ("relation_name", str),
    "Schema": ("schema_name", str),
    "Alias": ("alias", str),
    "Index Name": ("index_name", str),
    "Join Type": ("join_type", str),
    "Parallel Aware": ("parallel_aware", bool),
    "Workers Planned": ("workers_planned", int),
    "Workers Launched": ("workers_launched", int),
    "Startup Cost": ("startup_cost", (int, float)),
    "Total Cost": ("total_cost", (int, float)),
    "Plan Rows": ("plan_rows", (int, float)),
    "Plan Width": ("plan_width", int),
    "Actual Startup Time": ("actual_startup_time_ms", (int, float)),
    "Actual Total Time": ("actual_total_time_ms", (int, float)),
    "Actual Rows": ("actual_rows", (int, float)),
    "Actual Loops": ("actual_loops", int),
    "Filter": ("filter", str),
    "Index Cond": ("index_cond", str),
    "Rows Removed by Filter": ("rows_removed_by_filter", (int, float)),
    "Sort Method": ("sort_method", str),
    "Sort Space Used": ("sort_space_used_kb", int),
    "Sort Space Type": ("sort_space_type", str),
    "Shared Hit Blocks": ("shared_hit_blocks", int),
    "Shared Read Blocks": ("shared_read_blocks", int),
    "Shared Dirtied Blocks": ("shared_dirtied_blocks", int),
    "Shared Written Blocks": ("shared_written_blocks", int),
    "Temp Read Blocks": ("temp_read_blocks", int),
    "Temp Written Blocks": ("temp_written_blocks", int),
}


def _invalid(message: str) -> InvalidPlanFormatError:
    return InvalidPlanFormatError(message, details=[{"field": "plan", "message": message}])


def _json_depth(value: Any) -> int:
    deepest, stack = 0, [(value, 1)]
    while stack:
        item, depth = stack.pop()
        deepest = max(deepest, depth)
        if depth > MAX_JSON_DEPTH:
            return depth
        if isinstance(item, dict):
            stack.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            stack.extend((v, depth + 1) for v in item)
    return deepest


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    # Stdlib json silently keeps the last duplicate; uploads must be unambiguous (REPLAY §2.1).
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise _invalid(f'Duplicate key "{key[:60]}" in plan JSON.')
        obj[key] = value
    return obj


def load_plan_document(raw: str | bytes) -> Any:
    """Decode an uploaded plan with size, depth and duplicate-key checks."""
    data = raw.encode() if isinstance(raw, str) else raw
    if len(data) > MAX_PLAN_BYTES:
        raise PayloadTooLargeError("Plan upload is larger than 5 MB.")
    try:
        document = json.loads(data, object_pairs_hook=_reject_duplicates)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise _invalid("Plan is not valid JSON.") from exc
    except RecursionError as exc:
        raise _invalid("Plan is nested too deep.") from exc
    if _json_depth(document) > MAX_JSON_DEPTH:
        raise _invalid("Plan is nested too deep.")
    return document


def _load(document: str | bytes | list[Any] | dict[str, Any]) -> tuple[dict[str, Any], str]:
    if isinstance(document, str | bytes):
        document = load_plan_document(document)
    if _json_depth(document) > MAX_JSON_DEPTH:
        raise _invalid("Plan is nested too deep.")
    if isinstance(document, list):
        if len(document) != 1 or not isinstance(document[0], dict):
            raise _invalid("Expected EXPLAIN (FORMAT JSON) output for exactly one statement.")
        top, prefix = document[0], "/0"
    elif isinstance(document, dict):
        top, prefix = document, ""
    else:
        raise _invalid("Expected EXPLAIN (FORMAT JSON) output.")
    if not isinstance(top.get("Plan"), dict):
        raise _invalid('Missing "Plan" object.')
    return top, prefix


def _number(top: dict[str, Any], key: str) -> float | None:
    value = top.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _invalid(f'"{key}" must be a number.')
    return float(value)


def _build(
    raw: dict[str, Any], locator: str, parent_id: int | None, out: list[PlanNode]
) -> PlanNode:
    node_type = raw.get("Node Type")
    if not isinstance(node_type, str) or not node_type:
        raise _invalid(f'Plan node at {locator} has no "Node Type".')
    fields: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    for key, value in raw.items():
        if key in ("Node Type", "Plans"):
            continue
        if key == "Sort Key":
            if not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
                raise _invalid(f'"Sort Key" at {locator} must be a list of strings.')
            fields["sort_key"] = value
        elif key in _FIELDS:
            name, expected = _FIELDS[key]
            is_bool_mismatch = isinstance(value, bool) and expected is not bool
            if value is not None and (is_bool_mismatch or not isinstance(value, expected)):
                raise _invalid(f'"{key}" at {locator} has the wrong type.')
            fields[name] = value
        else:
            extra[key] = value
    node_id = len(out)
    out.append(PlanNode(id=node_id, parent_id=parent_id, locator=locator, node_type=node_type))
    raw_children = raw.get("Plans", [])
    if not isinstance(raw_children, list) or not all(isinstance(c, dict) for c in raw_children):
        raise _invalid(f'"Plans" at {locator} must be a list of plan nodes.')
    children = [
        _build(child, f"{locator}/Plans/{i}", node_id, out) for i, child in enumerate(raw_children)
    ]
    node = PlanNode(
        id=node_id,
        parent_id=parent_id,
        locator=locator,
        node_type=node_type,
        extra=extra,
        children=children,
        **fields,
    )
    out[node_id] = node
    return node


def parse_plan(document: str | bytes | list[Any] | dict[str, Any]) -> PlanTree:
    top, prefix = _load(document)
    nodes: list[PlanNode] = []
    root = _build(top["Plan"], f"{prefix}/Plan", None, nodes)
    return PlanTree(
        root=root,
        nodes=nodes,
        analyzed=any(n.actual_loops is not None for n in nodes),
        has_timing=any(n.actual_total_time_ms is not None for n in nodes),
        has_buffers=any(n.shared_hit_blocks is not None for n in nodes),
        planning_time_ms=_number(top, "Planning Time"),
        execution_time_ms=_number(top, "Execution Time"),
    )
