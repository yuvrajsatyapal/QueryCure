/* The Query X-Ray's numbers: a recorded PostgreSQL EXPLAIN ANALYZE run, not a model.
 * `xray_pg_result.json` is written by docs/design/prototypes/landing/xray_pg_check.py (a synthetic 2,000,000-row
 * orders table in temporary tables, rolled back). Every figure the card shows is derived here, and the tests pin
 * the file to the recorded copy and the run count to the script. Server-side Execution Time only, with
 * TIMING OFF, so no network or client time is included. */

import recorded from "./xray_pg_result.json";

type PlanNode = { node: string; actual_rows: number; removed_by_filter: number | null };

/** The check script's RUNS constant; the test reads it from the script so the two cannot drift. */
const RUNS = 30;

const node = (nodes: readonly PlanNode[], prefix: string): PlanNode => {
  const found = nodes.find((n) => n.node.startsWith(prefix));
  if (!found) throw new Error(`xray_pg_result.json has no "${prefix}" node`);
  return found;
};

const seq = node(recorded.before.nodes, "Seq Scan");
const sort = node(recorded.before.nodes, "Sort");
const limit = node(recorded.before.nodes, "Limit");
const idx = node(recorded.after.nodes, "Index Scan");
const discarded = seq.removed_by_filter ?? 0;

export const MEASURED = {
  /** "PostgreSQL 17.11 (Debian …)" reduced to the product and version. */
  engine: recorded.postgres.replace(/\s*\(.*$/, ""),
  tableRows: recorded.rows,
  runs: RUNS,
  limit: limit.actual_rows,
  before: {
    medianMs: recorded.before.median_exec_ms,
    minMs: recorded.before.min_ms,
    maxMs: recorded.before.max_ms,
    kept: seq.actual_rows,
    discarded,
    examined: seq.actual_rows + discarded,
    sortIn: seq.actual_rows,
    sortOut: sort.actual_rows,
  },
  after: {
    medianMs: recorded.after.median_exec_ms,
    minMs: recorded.after.min_ms,
    maxMs: recorded.after.max_ms,
    rows: idx.actual_rows,
  },
  /** Ratio of the two recorded medians. */
  ratio: recorded.before.median_exec_ms / recorded.after.median_exec_ms,
  /** After's share of Before's time, for the linear race lane. */
  afterLane: recorded.after.median_exec_ms / recorded.before.median_exec_ms,
} as const;

export const formatMs = (ms: number): string => (ms >= 1 ? ms.toFixed(1) : ms.toFixed(3));

/** Sub-millisecond medians read better in whole microseconds: 0.006 ms → "6 µs". */
export const formatMicros = (ms: number): string => `${Math.round(ms * 1000)} µs`;

/** A row count on a log axis from 1 row (0%) to the whole table (100%). */
export const logRowsPct = (rows: number): number => (Math.log10(Math.max(1, rows)) / Math.log10(MEASURED.tableRows)) * 100;
