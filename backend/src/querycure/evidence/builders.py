"""Deterministic evidence from plans, schema snapshots, uploaded DDL and query metadata.

Summaries are generated from the numbers, never by an LLM, and every number in a summary
is also in `data`. Untrusted names pass through `quote_ident` / `clean_text`.
"""

import uuid
from collections.abc import Sequence
from typing import Literal

from querycure.connectors.models import SchemaSnapshot, TableStats
from querycure.domain.investigation import Evidence, EvidenceKind, JsonScalar, Provenance
from querycure.evidence.ids import evidence_id
from querycure.evidence.sanitize import clean_text, qualified, quote_ident
from querycure.plans.metrics import NodeMetrics
from querycure.plans.models import PlanNode, PlanTree
from querycure.sql.ddl import DeclaredSchema
from querycure.sql.validator import ValidatedQuery

MAX_SUMMARY = 300
DEFAULT_CONTEXT_CHARS = 16_000  # ≈ 4k tokens (AGENT_SYSTEM §4 context_summary)
_KIND_ORDER: dict[str, int] = {
    "query_fact": 0,
    "plan_summary": 1,
    "plan_node": 2,
    "table_stat": 3,
    "index_def": 4,
    "column_stat": 5,
    "schema_fact": 6,
    "workload_stat": 7,
    "lock_sample": 8,
    "tool_error": 9,
    "user_input": 10,
}


def _ev(
    run_id: uuid.UUID,
    kind: EvidenceKind,
    artifact_sha256: str | None,
    locator: str,
    summary: str,
    data: dict[str, JsonScalar],
    provenance: Provenance,
) -> Evidence:
    if len(summary) > MAX_SUMMARY:
        summary = summary[: MAX_SUMMARY - 1] + "…"
    return Evidence(
        id=evidence_id(run_id, kind, artifact_sha256, locator),
        kind=kind,
        artifact_sha256=artifact_sha256,
        locator=locator,
        summary=summary,
        data=data,
        provenance=provenance,
    )


def _r(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


def _count(value: float | None) -> str:
    return "?" if value is None else f"{value:,.0f}"


def _node_head(node: PlanNode) -> str:
    head = node.node_type
    if node.relation_name:
        head += f" on {qualified(None, node.relation_name)}"
    if node.index_name:
        head += f" using {quote_ident(node.index_name)}"
    return head


def _node_summary(node: PlanNode, m: NodeMetrics, tree: PlanTree, hottest: bool) -> str:
    parts = [_node_head(node)]
    if tree.analyzed and m.self_time_ms is not None and m.self_time_share is not None:
        parts.append(f"{m.self_time_ms:.1f} ms self ({m.self_time_share:.1%} of runtime)")
    if tree.analyzed and node.actual_rows is not None:
        rows = f"est {_count(node.plan_rows)} vs actual {_count(node.actual_rows)} rows/loop"
        if (node.actual_loops or 1) > 1:
            rows += f" x {node.actual_loops} loops"
        if m.estimate_error_ratio is not None and m.estimate_direction in ("under", "over"):
            rows += f" ({m.estimate_error_ratio:.1f}x {m.estimate_direction}estimate)"
        parts.append(rows)
    else:
        parts.append(f"est {_count(node.plan_rows)} rows, cost {node.total_cost or 0:,.1f}")
    if node.filter:
        parts.append(f"filter {clean_text(node.filter, 80)}")
    if node.index_cond:
        parts.append(f"index cond {clean_text(node.index_cond, 80)}")
    if m.rows_removed_by_filter_total:
        parts.append(f"{m.rows_removed_by_filter_total:,.0f} rows removed by filter")
    if node.sort_key:
        method = f" ({node.sort_method})" if node.sort_method else ""
        parts.append(f"sort by {clean_text(', '.join(node.sort_key), 80)}{method}")
    if m.sort_spilled:
        parts.append("spilled to disk")
    if hottest:
        parts.append("hottest node")
    return "; ".join(parts)


def plan_evidence(
    run_id: uuid.UUID,
    artifact_sha256: str,
    tree: PlanTree,
    metrics: Sequence[NodeMetrics],
    *,
    provenance: Provenance,
) -> list[Evidence]:
    by_id = {m.node_id: m for m in metrics}
    timed = [m for m in metrics if m.self_time_ms is not None]
    hottest_id = max(timed, key=lambda m: m.self_time_ms or 0.0).node_id if timed else None
    hottest = tree.nodes[hottest_id] if hottest_id is not None else None

    if tree.analyzed:
        overview = (
            f"Plan with {len(tree.nodes)} nodes; execution "
            f"{tree.execution_time_ms or 0:.1f} ms, planning {tree.planning_time_ms or 0:.1f} ms"
        )
        if hottest is not None:
            overview += f"; hottest: {_node_head(hottest)}"
    else:
        overview = (
            f"Plain EXPLAIN (estimates only): {len(tree.nodes)} nodes, "
            f"total cost {tree.root.total_cost or 0:,.1f}"
        )
    items = [
        _ev(
            run_id,
            "plan_summary",
            artifact_sha256,
            "/0",
            overview,
            {
                "analyzed": tree.analyzed,
                "has_buffers": tree.has_buffers,
                "node_count": len(tree.nodes),
                "execution_time_ms": _r(tree.execution_time_ms),
                "planning_time_ms": _r(tree.planning_time_ms),
                "root_total_cost": _r(tree.root.total_cost),
                "hottest_node_id": hottest_id,
            },
            provenance,
        )
    ]
    for node in tree.nodes:
        m = by_id[node.id]
        data: dict[str, JsonScalar] = {
            "node_id": node.id,
            "node_type": node.node_type,
            "relation": node.relation_name,
            "index": node.index_name,
            "join_type": node.join_type,
            "plan_rows": node.plan_rows,
            "actual_rows": node.actual_rows,
            "loops": node.actual_loops,
            "total_cost": _r(node.total_cost),
            "self_time_ms": _r(m.self_time_ms),
            "self_time_share": _r(m.self_time_share, 4),
            "inclusive_time_ms": _r(m.inclusive_time_ms),
            "estimate_error_ratio": _r(m.estimate_error_ratio, 2),
            "estimate_direction": m.estimate_direction,
            "rows_removed_by_filter_total": m.rows_removed_by_filter_total,
            "filter": clean_text(node.filter) if node.filter else None,
            "index_cond": clean_text(node.index_cond) if node.index_cond else None,
            "sort_key": clean_text(", ".join(node.sort_key)) if node.sort_key else None,
            "sort_method": node.sort_method,
            "sort_spilled": m.sort_spilled,
            "self_shared_read_blocks": m.self_shared_read_blocks,
            "hottest": node.id == hottest_id,
        }
        items.append(
            _ev(
                run_id,
                "plan_node",
                artifact_sha256,
                node.locator,
                _node_summary(node, m, tree, node.id == hottest_id),
                data,
                provenance,
            )
        )
    return items


def query_evidence(
    run_id: uuid.UUID, artifact_sha256: str, validated: ValidatedQuery
) -> list[Evidence]:
    meta = validated.metadata
    facts: list[tuple[str, str, JsonScalar]] = [
        (
            "#tables",
            "Query reads table(s): "
            + ", ".join(qualified(t.schema_name, t.name) for t in meta.tables),
            ", ".join(qualified(t.schema_name, t.name) for t in meta.tables),
        ),
        (
            "#columns",
            "Query references column(s): "
            + ", ".join(sorted(quote_ident(c.name) for c in meta.columns)),
            ", ".join(sorted(quote_ident(c.name) for c in meta.columns)),
        ),
        (
            "#parameters",
            f"Query has {meta.parameter_count} bind parameter(s)",
            meta.parameter_count,
        ),
    ]
    if meta.order_by:
        order = clean_text(", ".join(meta.order_by))
        facts.append(("#order_by", f"Query orders by {order}", order))
    if meta.limit is not None:
        facts.append(("#limit", f"Query returns at most {meta.limit} rows (LIMIT)", meta.limit))
    return [
        _ev(run_id, "query_fact", artifact_sha256, locator, summary, {"value": value}, "derived")
        for locator, summary, value in facts
    ]


def _size(total_bytes: int) -> str:
    return f"{total_bytes / (1024 * 1024):,.1f} MiB"


StatsOrigin = Literal["live", "sandbox_clone"]
# PostgreSQL's autovacuum analyze trigger with default settings (50 rows + 10% of the table):
# beyond it the planner statistics lag the data.
ANALYZE_BASE_THRESHOLD = 50
ANALYZE_SCALE_FACTOR = 0.1


def _freshness(t: TableStats, analyzed_columns: int, counters: str) -> str:
    """never_analyzed / stale / not_stale / unknown, from planner stats and live counters only.

    `pg_stats` rows exist only after ANALYZE, so their absence means never analyzed. Usage
    counters (`pg_stat_*`) are reset by cloning or `pg_stat_reset()`: without a recorded
    analyze time they cannot tell how fresh the statistics are."""
    if analyzed_columns == 0:
        return "never_analyzed"
    if counters != "live" or (t.last_analyze or t.last_autoanalyze) is None:
        return "unknown"
    if t.n_mod_since_analyze is None:
        return "unknown"
    rows = max(t.estimated_rows or 0.0, float(t.n_live_tup or 0))
    limit = ANALYZE_BASE_THRESHOLD + ANALYZE_SCALE_FACTOR * rows
    return "stale" if t.n_mod_since_analyze > limit else "not_stale"


def _table_summary(t: TableStats, analyzed_columns: int, counters: str, freshness: str) -> str:
    head = f"Table {qualified(t.schema_name, t.name)}: ~{_count(t.estimated_rows)} rows, "
    head += _size(t.total_bytes)
    planner = (
        f"planner statistics present ({analyzed_columns} columns)"
        if analyzed_columns
        else "never analyzed: no planner column statistics"
    )
    if counters == "reset_by_clone":
        return (
            f"{head}; {planner}; usage counters (scans, last analyze, row changes) were reset "
            "when the sandbox clone was created and are not evidence"
        )
    scans = (
        f"{t.seq_scan if t.seq_scan is not None else '?'} seq scans / "
        f"{t.idx_scan if t.idx_scan is not None else '?'} index scans"
    )
    analyzed = t.last_analyze or t.last_autoanalyze
    if analyzed is not None:
        text = f"{head}, {scans}; last analyzed {analyzed.date().isoformat()}"
        if freshness == "stale":
            text += f"; {t.n_mod_since_analyze:,} rows changed since, statistics behind the data"
        return text
    if analyzed_columns:
        return (
            f"{head}, {scans}; no analyze recorded in cumulative statistics (counters may have "
            f"been reset); {planner}"
        )
    return f"{head}, {scans}; {planner}"


def schema_evidence(
    run_id: uuid.UUID,
    artifact_sha256: str,
    snapshot: SchemaSnapshot,
    *,
    origin: StatsOrigin = "live",
) -> list[Evidence]:
    """`origin="sandbox_clone"`: planner statistics were copied from the template, cumulative
    counters were reset by CREATE DATABASE ... TEMPLATE (E2E audit O3)."""
    items: list[Evidence] = []
    analyzed_by_table: dict[tuple[str, str], int] = {}
    for c in snapshot.columns:
        key = (c.schema_name, c.table_name)
        analyzed_by_table[key] = analyzed_by_table.get(key, 0) + (c.null_frac is not None)
    for i, t in enumerate(snapshot.tables):
        analyzed = t.last_analyze or t.last_autoanalyze
        analyzed_columns = analyzed_by_table.get((t.schema_name, t.name), 0)
        live_counters = any(
            v is not None for v in (t.seq_scan, t.idx_scan, t.n_live_tup, t.n_mod_since_analyze)
        )
        counters = (
            "reset_by_clone"
            if origin == "sandbox_clone"
            else ("live" if live_counters else "unavailable")
        )
        freshness = _freshness(t, analyzed_columns, counters)
        if analyzed_columns:
            planner_stats = "present"
        else:
            planner_stats = "row_estimate_only" if t.estimated_rows is not None else "absent"
        items.append(
            _ev(
                run_id,
                "table_stat",
                artifact_sha256,
                f"/tables/{i}",
                _table_summary(t, analyzed_columns, counters, freshness),
                {
                    "table": qualified(t.schema_name, t.name),
                    "estimated_rows": t.estimated_rows,
                    "total_bytes": t.total_bytes,
                    "n_live_tup": t.n_live_tup,
                    "n_dead_tup": t.n_dead_tup,
                    "n_mod_since_analyze": t.n_mod_since_analyze,
                    "seq_scan": t.seq_scan,
                    "idx_scan": t.idx_scan,
                    "last_analyze": analyzed.isoformat() if analyzed else None,
                    "stats_origin": origin,
                    "planner_stats": planner_stats,
                    "analyzed_columns": analyzed_columns,
                    "counters": counters,
                    "freshness": freshness,
                },
                "measured",
            )
        )
    for i, c in enumerate(snapshot.columns):
        if c.n_distinct is None:
            distinct = "n_distinct unknown"
        elif c.n_distinct < 0:
            distinct = f"~{-c.n_distinct:.0%} of rows distinct"
        else:
            distinct = f"n_distinct {c.n_distinct:,.0f}"
        items.append(
            _ev(
                run_id,
                "column_stat",
                artifact_sha256,
                f"/columns/{i}",
                f"Column {quote_ident(c.table_name)}.{quote_ident(c.name)} "
                f"({clean_text(c.data_type, 40)}{', NOT NULL' if c.not_null else ''}): "
                f"{distinct}, null_frac {c.null_frac if c.null_frac is not None else '?'}, "
                f"correlation {c.correlation if c.correlation is not None else '?'}",
                {
                    "table": qualified(c.schema_name, c.table_name),
                    "column": quote_ident(c.name),
                    "data_type": clean_text(c.data_type, 40),
                    "not_null": c.not_null,
                    "null_frac": c.null_frac,
                    "n_distinct": c.n_distinct,
                    "avg_width": c.avg_width,
                    "correlation": c.correlation,
                },
                "measured",
            )
        )
    for i, ix in enumerate(snapshot.indexes):
        definition = clean_text(ix.definition, 240)
        items.append(
            _ev(
                run_id,
                "index_def",
                artifact_sha256,
                f"/indexes/{i}",
                f"Index {quote_ident(ix.name)} on {qualified(ix.schema_name, ix.table_name)}: "
                f"{definition}{'' if ix.is_valid else ' (INVALID)'}",
                {
                    "table": qualified(ix.schema_name, ix.table_name),
                    "name": quote_ident(ix.name),
                    "definition": definition,
                    "is_unique": ix.is_unique,
                    "is_primary": ix.is_primary,
                    "is_valid": ix.is_valid,
                    "size_bytes": ix.size_bytes,
                    "idx_scan": ix.idx_scan,
                },
                "measured",
            )
        )
    return items


def declared_schema_evidence(
    run_id: uuid.UUID, artifact_sha256: str, schema: DeclaredSchema
) -> list[Evidence]:
    items: list[Evidence] = []
    for i, t in enumerate(schema.tables):
        name = qualified(t.schema_name, t.name)
        pk = ", ".join(quote_ident(c) for c in t.primary_key)
        items.append(
            _ev(
                run_id,
                "schema_fact",
                artifact_sha256,
                f"/tables/{i}",
                f"Declared table {name} ({len(t.columns)} columns"
                + (f"; primary key {pk}" if pk else "; no primary key")
                + ")",
                {
                    "table": name,
                    "columns": ", ".join(quote_ident(c.name) for c in t.columns),
                    "not_null": ", ".join(quote_ident(c.name) for c in t.columns if c.not_null),
                    "primary_key": pk or None,
                },
                "imported",
            )
        )
    for i, ix in enumerate(schema.indexes):
        cols = ", ".join(clean_text(c, 63) for c in ix.columns)
        items.append(
            _ev(
                run_id,
                "index_def",
                artifact_sha256,
                f"/indexes/{i}",
                f"Declared {'unique ' if ix.unique else ''}index {quote_ident(ix.name)} on "
                f"{quote_ident(ix.table)} ({cols})"
                + (f" USING {clean_text(ix.method, 20)}" if ix.method else "")
                + (f" WHERE {clean_text(ix.predicate, 80)}" if ix.predicate else ""),
                {
                    "table": quote_ident(ix.table),
                    "name": quote_ident(ix.name),
                    "columns": cols,
                    "unique": ix.unique,
                    "method": ix.method,
                    "predicate": clean_text(ix.predicate) if ix.predicate else None,
                },
                "imported",
            )
        )
    return items


def context_summary(evidence: Sequence[Evidence], *, max_chars: int = DEFAULT_CONTEXT_CHARS) -> str:
    """Deterministic, bounded text listing evidence for prompts. Same input set, same text."""
    unique = {e.id: e for e in evidence}.values()
    ordered = sorted(unique, key=lambda e: (_KIND_ORDER.get(e.kind, 99), e.locator, e.id))
    lines: list[str] = []
    used = 0
    for i, e in enumerate(ordered):
        line = f"[{e.id}] ({e.kind}) {e.summary}"
        remaining = len(ordered) - i
        tail = f"... {remaining} more evidence items omitted"
        if used + len(line) + 1 + len(tail) > max_chars and remaining > 1:
            lines.append(tail)
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)[:max_chars]
