"""Tools for the Workload Investigator (Mode B only): fixed catalog templates via the gateway.

Every call stores its result as a `workload_snapshot` artifact, so evidence points at exactly
what was observed. Statement texts from pg_stat_statements belong to other users: they are
already normalised by PostgreSQL, truncated, cleaned, and only ever reach prompts fenced.
"""

from typing import Any

from pydantic import Field

from querycure.agents.services import Inspector
from querycure.agents.tools.base import Tool, ToolContext, ToolInput, ToolOutput
from querycure.agents.tools.evidence_tools import TableInput, _table_ref
from querycure.core.errors import TargetQueryError
from querycure.domain.investigation import Evidence, EvidenceKind, JsonScalar
from querycure.evidence.ids import evidence_id
from querycure.evidence.sanitize import clean_text, qualified
from querycure.replay.artifact_store import link, store_json


class LimitInput(ToolInput):
    limit: int = Field(default=10, ge=1, le=20)


class NoInput(ToolInput):
    pass


async def _snapshot(tctx: ToolContext, key: str, rows: list[dict[str, Any]]) -> str:
    async with tctx.run.db().begin() as conn:
        artifact = await store_json(conn, kind="workload_snapshot", value={key: rows})
        await link(
            conn,
            run_id=tctx.run.run_id,
            artifact_id=artifact.id,
            role="context.workload",
            produced_by="workload_investigator",
        )
    return artifact.sha256


def _ev(
    tctx: ToolContext,
    kind: EvidenceKind,
    sha: str,
    locator: str,
    summary: str,
    data: dict[str, JsonScalar],
) -> Evidence:
    return Evidence(
        id=evidence_id(tctx.run.run_id, kind, sha, locator),
        kind=kind,
        artifact_sha256=sha,
        locator=locator,
        summary=summary[:299] + "…" if len(summary) > 300 else summary,
        data=data,
        provenance="measured",
    )


def _inspector(tctx: ToolContext) -> Inspector:
    if tctx.inspector is None:
        raise TargetQueryError("Workload statistics need a live connection.")
    return tctx.inspector


async def get_statement_stats(tctx: ToolContext, args: LimitInput) -> ToolOutput:
    stats = await _inspector(tctx).statement_stats(limit=args.limit)
    sha = await _snapshot(tctx, "statement_stats", [s.model_dump() for s in stats])
    return ToolOutput(
        evidence=[
            _ev(
                tctx,
                "workload_stat",
                sha,
                f"/statement_stats/{i}",
                f"Statement {s.queryid}: {s.calls:,} calls, mean {s.mean_exec_time_ms:.2f} ms, "
                f"total {s.total_exec_time_ms:,.0f} ms, {s.temp_blks_written:,} temp blocks "
                f"written; text: {clean_text(s.query, 120)}",
                {
                    "queryid": s.queryid,
                    "calls": s.calls,
                    "mean_exec_time_ms": round(s.mean_exec_time_ms, 3),
                    "total_exec_time_ms": round(s.total_exec_time_ms, 3),
                    "rows": s.rows,
                    "shared_blks_hit": s.shared_blks_hit,
                    "shared_blks_read": s.shared_blks_read,
                    "temp_blks_written": s.temp_blks_written,
                    "query": clean_text(s.query, 300),
                },
            )
            for i, s in enumerate(stats)
        ]
    )


async def get_activity_snapshot(tctx: ToolContext, args: NoInput) -> ToolOutput:
    buckets = await _inspector(tctx).activity_summary()
    sha = await _snapshot(tctx, "activity", [b.model_dump() for b in buckets])
    evidence = [
        _ev(
            tctx,
            "workload_stat",
            sha,
            f"/activity/{i}",
            f"{b.sessions} other session(s) {clean_text(b.state, 40)}, waiting on "
            f"{clean_text(b.wait_event_type, 40)}; longest open transaction "
            f"{b.longest_xact_seconds:,.1f} s",
            b.model_dump(),
        )
        for i, b in enumerate(buckets)
    ]
    return ToolOutput(evidence=evidence, note=None if evidence else "No other client sessions.")


async def get_lock_snapshot(tctx: ToolContext, args: NoInput) -> ToolOutput:
    locks = await _inspector(tctx).lock_summary()
    sha = await _snapshot(tctx, "locks", [b.model_dump() for b in locks])
    evidence = [
        _ev(
            tctx,
            "lock_sample",
            sha,
            f"/locks/{i}",
            f"{b.waiting} waiting / {b.granted} granted {clean_text(b.mode, 40)} "
            f"({clean_text(b.locktype, 20)}) locks"
            + (f" on {clean_text(b.relation, 130)}" if b.relation else ""),
            b.model_dump(),
        )
        for i, b in enumerate(locks)
    ]
    return ToolOutput(evidence=evidence, note=None if evidence else "No locks held by others.")


async def get_table_io_stats(tctx: ToolContext, args: TableInput) -> ToolOutput:
    rows = await _inspector(tctx).table_io([_table_ref(args.table)])
    sha = await _snapshot(tctx, "table_io", [r.model_dump() for r in rows])
    evidence = []
    for i, r in enumerate(rows):
        hit, read = r.heap_blks_hit or 0, r.heap_blks_read or 0
        ratio = f"{hit / (hit + read):.1%}" if hit + read else "n/a"
        evidence.append(
            _ev(
                tctx,
                "workload_stat",
                sha,
                f"/table_io/{i}",
                f"Table {qualified(r.schema_name, r.name)} I/O since stats reset: heap blocks "
                f"{hit:,} hit / {read:,} read (cache hit {ratio}); index blocks "
                f"{r.idx_blks_hit or 0:,} hit / {r.idx_blks_read or 0:,} read",
                {**r.model_dump(), "table": qualified(r.schema_name, r.name)},
            )
        )
    return ToolOutput(evidence=evidence, note=None if evidence else "Table not found.")


GET_STATEMENT_STATS = Tool(
    "get_statement_stats",
    "Top statements by total execution time from pg_stat_statements (normalised text).",
    LimitInput,
    get_statement_stats,
)
GET_ACTIVITY_SNAPSHOT = Tool(
    "get_activity_snapshot",
    "Other sessions grouped by state and wait event type, with the longest open transaction.",
    NoInput,
    get_activity_snapshot,
)
GET_LOCK_SNAPSHOT = Tool(
    "get_lock_snapshot",
    "Locks held and awaited by other sessions, grouped by mode and relation.",
    NoInput,
    get_lock_snapshot,
)
GET_TABLE_IO_STATS = Tool(
    "get_table_io_stats",
    "Buffer cache hits and disk reads for a table and its indexes since statistics reset.",
    TableInput,
    get_table_io_stats,
)
