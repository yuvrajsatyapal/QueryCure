"""Tools for the Query Analyzer and Index Strategist: lookups over the run's evidence.

In Mode B a table that has no statistics yet is fetched through the gateway (redacted,
numeric-only snapshot), stored as an artifact and recorded as evidence before answering.
"""

import math
from typing import Any

from pydantic import Field

from querycure.agents.tools.base import Tool, ToolContext, ToolInput, ToolOutput
from querycure.domain.investigation import Evidence, JsonScalar
from querycure.evidence.builders import schema_evidence
from querycure.evidence.ids import evidence_id
from querycure.evidence.sanitize import clean_text
from querycure.evidence.store import list_evidence, record_evidence
from querycure.replay.artifact_store import link, store_json
from querycure.sql.validator import TableRef

PAGE_BYTES = 8192
BTREE_FILLFACTOR = 0.9
INDEX_TUPLE_HEADER_BYTES = 8  # IndexTupleData
LINE_POINTER_BYTES = 4
MAXALIGN = 8


class NodeInput(ToolInput):
    node_id: int = Field(ge=0, le=10_000, description="plan node id (node_id in evidence data)")


class TableInput(ToolInput):
    table: str = Field(min_length=1, max_length=130, description="table name, optionally schema.")


class ColumnInput(TableInput):
    column: str = Field(min_length=1, max_length=63)


class ObjectInput(ToolInput):
    name: str = Field(min_length=1, max_length=130, description="index or table name")


class IndexSizeInput(TableInput):
    columns: list[str] = Field(min_length=1, max_length=8)


def _bare(name: str) -> str:
    return name.strip().strip('"').lower()


def _table_ref(name: str) -> TableRef:
    parts = [_bare(p) for p in name.split(".", 1)]
    if len(parts) == 2:
        return TableRef(schema_name=parts[0], name=parts[1])
    return TableRef(schema_name=None, name=parts[0])


def _same_table(recorded: JsonScalar, wanted: str) -> bool:
    if not isinstance(recorded, str):
        return False
    have, want = _bare(recorded), _bare(wanted)
    return have == want or have.endswith("." + want) or want.endswith("." + have)


def _details(e: Evidence) -> str:
    shown = ", ".join(f"{k}={v}" for k, v in e.data.items() if v is not None and v != "")
    return f"details of {e.id}: {clean_text(shown, 600)}"


async def _evidence(tctx: ToolContext) -> list[Evidence]:
    async with tctx.run.db().connect() as conn:
        return await list_evidence(conn, tctx.run.run_id)


async def _with_table(tctx: ToolContext, table: str, kind: str) -> list[Evidence]:
    """Evidence of `kind` for `table`, fetching a snapshot in Mode B if none is recorded yet."""
    found = [
        e
        for e in await _evidence(tctx)
        if e.kind == kind and _same_table(e.data.get("table"), table)
    ]
    if found or tctx.inspector is None:
        return found
    snapshot = await tctx.inspector.schema_snapshot([_table_ref(table)])
    async with tctx.run.db().begin() as conn:
        artifact = await store_json(
            conn, kind="schema_snapshot", value=snapshot.model_dump(mode="json")
        )
        await link(
            conn,
            run_id=tctx.run.run_id,
            artifact_id=artifact.id,
            role="context.schema_snapshot",
            produced_by="tool",
        )
    fetched = schema_evidence(tctx.run.run_id, artifact.sha256, snapshot)
    await record_evidence(tctx.run.db(), tctx.run.run_id, fetched)
    return [e for e in fetched if e.kind == kind and _same_table(e.data.get("table"), table)]


def _none(what: str, tctx: ToolContext) -> ToolOutput:
    where = "" if tctx.inspector is not None else " (offline investigation: no live statistics)"
    return ToolOutput(note=f"No {what} recorded{where}.")


async def get_plan_node(tctx: ToolContext, args: NodeInput) -> ToolOutput:
    nodes = [
        e
        for e in await _evidence(tctx)
        if e.kind == "plan_node" and e.data.get("node_id") == args.node_id
    ]
    if not nodes:
        return ToolOutput(note=f"No plan node {args.node_id} in the recorded plans.")
    return ToolOutput(evidence=nodes, note="\n".join(_details(e) for e in nodes))


async def get_table_stats(tctx: ToolContext, args: TableInput) -> ToolOutput:
    found = await _with_table(tctx, args.table, "table_stat")
    return ToolOutput(evidence=found) if found else _none(f"statistics for {args.table}", tctx)


async def get_column_stats(tctx: ToolContext, args: ColumnInput) -> ToolOutput:
    found = [
        e
        for e in await _with_table(tctx, args.table, "column_stat")
        if _bare(str(e.data.get("column", ""))) == _bare(args.column)
    ]
    if not found:
        return _none(f"statistics for column {args.table}.{args.column}", tctx)
    return ToolOutput(evidence=found)


async def get_schema_object(tctx: ToolContext, args: ObjectInput) -> ToolOutput:
    wanted = _bare(args.name)
    found = [
        e
        for e in await _evidence(tctx)
        if e.kind in ("index_def", "schema_fact")
        and (
            _bare(str(e.data.get("name", ""))) == wanted
            or _same_table(e.data.get("table"), args.name)
        )
    ]
    if not found:
        return ToolOutput(note=f"No index or table named {clean_text(args.name, 63)} recorded.")
    return ToolOutput(evidence=found, note="\n".join(_details(e) for e in found))


async def list_indexes(tctx: ToolContext, args: TableInput) -> ToolOutput:
    found = await _with_table(tctx, args.table, "index_def")
    if not found:
        return _none(f"indexes for {args.table}", tctx)
    return ToolOutput(evidence=found, note="\n".join(_details(e) for e in found))


def _align(n: float) -> int:
    return int(math.ceil(n / MAXALIGN) * MAXALIGN)


async def estimate_index_size(tctx: ToolContext, args: IndexSizeInput) -> ToolOutput:
    """btree leaf-level approximation: rows x (header + aligned key width + line pointer),
    packed at fillfactor 90; internal pages ignored (< ~1% for these widths)."""
    tables = await _with_table(tctx, args.table, "table_stat")
    columns = await _with_table(tctx, args.table, "column_stat")
    rows = next((t.data.get("estimated_rows") for t in tables), None)
    widths: list[int] = []
    for col in args.columns:
        width = next(
            (
                c.data.get("avg_width")
                for c in columns
                if _bare(str(c.data.get("column", ""))) == _bare(col)
            ),
            None,
        )
        if not isinstance(width, int):
            return ToolOutput(note=f"Width of column {clean_text(col, 63)} is unknown.")
        widths.append(width)
    if not isinstance(rows, int | float) or rows <= 0:
        return ToolOutput(note=f"Row count of {clean_text(args.table, 130)} is unknown.")
    tuple_bytes = INDEX_TUPLE_HEADER_BYTES + _align(sum(widths)) + LINE_POINTER_BYTES
    pages = math.ceil(rows * tuple_bytes / (PAGE_BYTES * BTREE_FILLFACTOR))
    size = pages * PAGE_BYTES
    cols = ", ".join(_bare(c) for c in args.columns)
    table = clean_text(args.table, 130)
    data: dict[str, Any] = {
        "table": table,
        "columns": cols,
        "estimated_rows": rows,
        "tuple_bytes": tuple_bytes,
        "estimated_bytes": size,
        "method": "btree leaf approximation, fillfactor 90",
    }
    locator = f"#index_size/{table}({cols})"
    evidence = Evidence(
        id=evidence_id(tctx.run.run_id, "schema_fact", None, locator),
        kind="schema_fact",
        artifact_sha256=None,
        locator=locator,
        summary=(
            f"Estimated size of a btree index on {table} ({cols}): ~{size / 2**20:,.1f} MiB "
            f"({rows:,.0f} rows x {tuple_bytes} bytes per entry; derived, not measured)"
        ),
        data=data,
        provenance="derived",
    )
    return ToolOutput(evidence=[evidence])


def _tool(name: str, description: str, input_model: type[ToolInput], fn: Any) -> Tool:
    return Tool(name=name, description=description, input_model=input_model, run=fn)


GET_PLAN_NODE = _tool(
    "get_plan_node",
    "All recorded facts about one plan node (filter, index condition, sort keys, buffers).",
    NodeInput,
    get_plan_node,
)
GET_TABLE_STATS = _tool(
    "get_table_stats",
    "Row estimate, size, scan counts and last ANALYZE time for a table.",
    TableInput,
    get_table_stats,
)
GET_COLUMN_STATS = _tool(
    "get_column_stats",
    "n_distinct, null fraction, average width and correlation for one column.",
    ColumnInput,
    get_column_stats,
)
GET_SCHEMA_OBJECT = _tool(
    "get_schema_object",
    "Definition of an index or declared table by name.",
    ObjectInput,
    get_schema_object,
)
LIST_INDEXES = _tool(
    "list_indexes",
    "Every index on a table with its definition, size and scan count.",
    TableInput,
    list_indexes,
)
ESTIMATE_INDEX_SIZE = _tool(
    "estimate_index_size",
    "Approximate size of a btree index on the given columns, from row count and widths.",
    IndexSizeInput,
    estimate_index_size,
)
