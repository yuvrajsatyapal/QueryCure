"""Per-arm execution against one sandbox clone (BENCHMARK_ENGINE §4). Synchronous psycopg:
the engine runs every arm from one worker thread so the event loop never adds timing jitter.

- One dedicated qc_bench connection per arm; no prepared statements (plan caching stays
  consistent across arms).
- Timing = wall clock (`perf_counter_ns`) around execute + fetching every row, streamed in
  chunks of 1,000 (libpq chunked-rows mode) into the fingerprint hasher. Fetch cost counts:
  the user pays it too. Streaming replaced the planned server-side cursor: same bounded
  memory, but one network round trip instead of DECLARE + FETCH per batch, which on the
  local Docker relay roughly halved the per-sample harness floor.
- Queries run inside a READ ONLY transaction: defense in depth behind the SELECT validator.
- `cancel()` may be called from another thread; it cancels the in-flight statement.
"""

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import psycopg
from psycopg.postgres import types as pg_types
from psycopg.types.string import TextLoader

from querycure.benchmark.correctness import KIND_BY_OID, Fingerprint, Fingerprinter, kinds_for_oids
from querycure.domain.benchmark import BuildResult
from querycure.sql.ddl_allowlist import AllowedDdl

FETCH_BATCH = 1_000
Failure = Literal["timeout", "error", "cancelled"]


@dataclass(frozen=True)
class Sample:
    latency_ns: int | None
    failure: Failure | None
    fingerprint: Fingerprint | None
    error_code: str | None = None  # SQLSTATE, never the message


def _text_loaders(conn: psycopg.Connection[Any]) -> None:
    """Types outside qc-row-v1's typed set load as their PostgreSQL text form (`other`);
    json/jsonb load as text and are canonicalized by the profile."""
    oids: set[int] = set()
    for info in pg_types:
        oids.update(o for o in (info.oid, info.array_oid) if o)
    for oid in oids:
        if KIND_BY_OID.get(oid, "other") in ("other", "json"):
            conn.adapters.register_loader(oid, TextLoader)


def _kinds(cur: psycopg.RawCursor[Any]) -> list[str]:
    return kinds_for_oids(c.type_code for c in cur.description or [])


class ArmRunner:
    def __init__(self, conninfo: dict[str, Any], *, row_cap: int) -> None:
        self.conn: psycopg.Connection[Any] = psycopg.connect(
            **conninfo, autocommit=True, prepare_threshold=None
        )
        _text_loaders(self.conn)
        self._row_cap = row_cap
        self._cancelled = False

    def close(self) -> None:
        self.conn.close()

    def cancel(self) -> None:
        self._cancelled = True
        if not self.conn.closed:
            self.conn.cancel_safe(timeout=2.0)

    def round_trips(self, count: int) -> list[int]:
        """`count` timed `SELECT 1` round trips on this connection: the transport and harness
        part of every sample (BENCHMARK_ENGINE §4 step 7). Never mixed into samples."""
        out: list[int] = []
        for _ in range(count):
            start = time.perf_counter_ns()
            self.conn.execute("SELECT 1").fetchone()
            out.append(time.perf_counter_ns() - start)
        return out

    def unique_keys(self) -> dict[str, list[list[str]]]:
        """Unique/primary key columns per public table, for ORDER BY totality."""
        rows = self.conn.execute(
            """
            SELECT c.relname, array_agg(a.attname ORDER BY k.ord)
            FROM pg_index i
            JOIN pg_class c ON c.oid = i.indrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
            CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS k(attnum, ord)
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = k.attnum
            WHERE i.indisunique AND i.indpred IS NULL AND i.indexprs IS NULL
            GROUP BY c.relname, i.indexrelid
            """
        ).fetchall()
        keys: dict[str, list[list[str]]] = {}
        for table, columns in rows:
            keys.setdefault(table, []).append(list(columns))
        return keys

    def _index_sizes(self) -> dict[int, int]:
        rows = self.conn.execute(
            "SELECT i.indexrelid::bigint, pg_relation_size(i.indexrelid) FROM pg_index i "
            "JOIN pg_class c ON c.oid = i.indrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'"
        ).fetchall()
        return {int(oid): int(size) for oid, size in rows}

    def apply_ddl(
        self,
        arm: str,
        statements: Sequence[AllowedDdl],
        *,
        max_build_ms: int | None,
        max_index_bytes: int | None,
    ) -> BuildResult:
        """Run approved DDL in order. Never an implicit ANALYZE (BENCHMARK_ENGINE §4.1)."""
        before = self._index_sizes()
        timeout = max_build_ms or 0  # 0 = no statement timeout
        total_ns = 0
        try:
            self.conn.execute(f"SET statement_timeout = {int(timeout)}")
            for ddl in statements:
                start = time.perf_counter_ns()
                self.conn.execute(ddl.statement.encode())  # approved text, verbatim
                total_ns += time.perf_counter_ns() - start
        except psycopg.errors.QueryCanceled:
            if self._cancelled:
                raise
            return BuildResult(
                arm=arm,
                ok=False,
                reason="constraint_violation",
                detail=f"build exceeded max_build_ms={max_build_ms}",
                build_ns=total_ns,
            )
        except psycopg.Error as exc:
            return BuildResult(
                arm=arm, ok=False, reason="ddl_failed", detail=f"SQLSTATE {exc.sqlstate}"
            )
        finally:
            if not self.conn.closed:
                self.conn.execute("RESET statement_timeout")
        after = self._index_sizes()
        index_bytes = sum(size for oid, size in after.items() if oid not in before)
        if max_index_bytes is not None and index_bytes > max_index_bytes:
            return BuildResult(
                arm=arm,
                ok=False,
                reason="constraint_violation",
                detail=f"index size {index_bytes} B > max_index_bytes={max_index_bytes}",
                index_size_bytes=index_bytes,
                build_ns=total_ns,
            )
        return BuildResult(arm=arm, ok=True, index_size_bytes=index_bytes, build_ns=total_ns)

    def execute(
        self,
        query: str,
        params: Sequence[Any],
        *,
        noise: Callable[[], None] | None = None,
    ) -> Sample:
        conn = self.conn
        error: psycopg.Error | None = None
        fingerprint: Fingerprint | None = None
        latency: int | None = None
        try:
            conn.autocommit = False
            conn.read_only = True
            # Open the READ ONLY transaction outside the timed region: BEGIN is harness
            # overhead (a round trip through the sandbox network), not query cost.
            conn.execute("SELECT 1")
            cur = psycopg.RawCursor(conn)
            hasher: Fingerprinter | None = None
            start = time.perf_counter_ns()
            if noise is not None:
                noise()  # test seam: injected latency (TESTING_STRATEGY §6 noisy case)
            # One round trip; rows arrive in chunks of FETCH_BATCH, so memory stays bounded
            # and every row's fetch cost is inside the measurement.
            for row in cur.stream(query.encode(), list(params), size=FETCH_BATCH):
                if hasher is None:
                    hasher = Fingerprinter(_kinds(cur), cap=self._row_cap)
                hasher.add(row)
            latency = time.perf_counter_ns() - start
            if hasher is None:
                hasher = Fingerprinter(_kinds(cur), cap=self._row_cap)
            fingerprint = hasher.result()
        except psycopg.Error as exc:
            error = exc
        finally:
            if not conn.closed:
                conn.rollback()
                conn.read_only = False
                conn.autocommit = True
        if error is None:
            return Sample(latency_ns=latency, failure=None, fingerprint=fingerprint)
        if isinstance(error, psycopg.errors.QueryCanceled):
            failure: Failure = "cancelled" if self._cancelled else "timeout"
            return Sample(None, failure, None, error.sqlstate)
        return Sample(None, "error", None, error.sqlstate)

    def explain_analyze(self, query: str, params: Sequence[Any]) -> dict[str, Any] | None:
        """One EXPLAIN (ANALYZE, BUFFERS) after timing; its overhead never touches samples."""
        conn = self.conn
        try:
            conn.autocommit = False
            conn.read_only = True
            with psycopg.RawCursor(conn) as cur:
                cur.execute(
                    b"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query.encode(), list(params)
                )
                row = cur.fetchone()
        except psycopg.Error:
            return None
        finally:
            if not conn.closed:
                conn.rollback()
                conn.read_only = False
                conn.autocommit = True
        if row is None:
            return None
        value = row[0]
        plan = json.loads(value) if isinstance(value, str) else value
        return plan[0] if isinstance(plan, list) and plan else None


def buffers_of(plan: dict[str, Any] | None) -> dict[str, int] | None:
    if plan is None:
        return None
    top = plan.get("Plan", {})
    keys = ("Shared Hit Blocks", "Shared Read Blocks", "Temp Read Blocks", "Temp Written Blocks")
    return {k.lower().replace(" ", "_"): int(top.get(k, 0)) for k in keys}
