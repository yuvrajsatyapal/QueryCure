import type { PlanDiff, PlanNodeDiff } from "@/lib/api/types";

/** Where a figure comes from: EXPLAIN ANALYZE actuals are measured (one capture), planner
 * rows and cost are estimates. The plan diff never mixes the two under one label. */
export type Provenance = "measured" | "estimated";

type Delta = { fromValue: number | null; toValue: number | null; ratio: number | null };

/** The compared fields of `plans/diff.py` (`_COMPARED`), as the UI names them. */
const CHANGE_LABEL: Record<string, string> = {
  node_type: "node type",
  relation_name: "relation",
  index_name: "index",
  join_type: "join type",
  index_cond: "index condition",
  filter: "filter",
  sort_key: "sort key",
  sort_method: "sort method",
};

export function changeLabels(changes: string[]): string[] {
  return changes.map((c) => CHANGE_LABEL[c] ?? c);
}

export type MetricUnit = "ms" | "rows" | "count" | "cost" | "blocks";

/** Per-node metrics in the order the detail panel lists them (`_METRIC_NAMES`, camel-cased). */
const METRICS: { key: string; label: string; kind: Provenance; unit: MetricUnit }[] = [
  { key: "inclusiveTimeMs", label: "Inclusive time", kind: "measured", unit: "ms" },
  { key: "selfTimeMs", label: "Self time", kind: "measured", unit: "ms" },
  { key: "totalActualRows", label: "Actual rows (all loops)", kind: "measured", unit: "rows" },
  { key: "planRows", label: "Estimated rows", kind: "estimated", unit: "rows" },
  { key: "actualLoops", label: "Loops", kind: "measured", unit: "count" },
  { key: "totalCost", label: "Total cost", kind: "estimated", unit: "cost" },
  { key: "selfSharedBlocks", label: "Shared buffers, hit + read (self)", kind: "measured", unit: "blocks" },
  { key: "selfTempWrittenBlocks", label: "Temp blocks written (self)", kind: "measured", unit: "blocks" },
];

export interface MetricRow {
  key: string;
  label: string;
  kind: Provenance;
  unit: MetricUnit;
  from: number | null;
  to: number | null;
  ratio: number | null;
}

const metric = (n: PlanNodeDiff, key: string): Delta | undefined => (n.metrics as Record<string, Delta | undefined>)[key];

/** Recorded metrics of one node; a metric neither side recorded is left out. */
export function nodeMetricRows(n: PlanNodeDiff): MetricRow[] {
  return METRICS.flatMap((m) => {
    const d = metric(n, m.key);
    if (!d || (d.fromValue === null && d.toValue === null)) return [];
    return [{ ...m, from: d.fromValue, to: d.toValue, ratio: d.ratio }];
  });
}

export interface DiffSide {
  label: string;
  relation: string | null;
  index: string | null;
  /** Actual rows when EXPLAIN ANALYZE recorded them, else the planner estimate; null if neither. */
  rows: { value: number; kind: Provenance } | null;
  selfMs: number | null;
}

export interface DiffRow {
  key: string;
  status: PlanNodeDiff["status"];
  depth: number;
  label: string;
  typeChanged: boolean;
  changes: string[];
  from: DiffSide | null;
  to: DiffSide | null;
  node: PlanNodeDiff;
}

function side(n: PlanNodeDiff, which: "from" | "to"): DiffSide | null {
  const type = which === "from" ? n.nodeTypeFrom : n.nodeTypeTo;
  if (type === null) return null;
  const pick = (key: string) => {
    const d = metric(n, key);
    return (which === "from" ? d?.fromValue : d?.toValue) ?? null;
  };
  const actual = pick("totalActualRows");
  const planned = pick("planRows");
  return {
    label: type,
    relation: n.relation,
    index: which === "from" ? n.indexFrom : n.indexTo,
    rows: actual !== null ? { value: actual, kind: "measured" } : planned !== null ? { value: planned, kind: "estimated" } : null,
    selfMs: pick("selfTimeMs"),
  };
}

export function diffRows(diff: PlanDiff): DiffRow[] {
  return diff.nodes.map((n, i) => {
    const typeChanged = n.status === "changed" && n.nodeTypeFrom !== n.nodeTypeTo;
    return {
      key: `${i}:${n.fromLocator ?? ""}:${n.toLocator ?? ""}`,
      status: n.status,
      depth: n.depth,
      label: typeChanged ? `${n.nodeTypeFrom} → ${n.nodeTypeTo}` : (n.nodeTypeTo ?? n.nodeTypeFrom ?? "?"),
      typeChanged,
      changes: changeLabels(n.changes),
      from: side(n, "from"),
      to: side(n, "to"),
      node: n,
    };
  });
}

/** Whether each plan carries EXPLAIN ANALYZE actuals; a plain EXPLAIN (Mode B) has estimates only. */
export function recordedActuals(diff: PlanDiff): { from: boolean; to: boolean } {
  const has = (which: "from" | "to") =>
    diff.nodes.some((n) => ["totalActualRows", "inclusiveTimeMs"].some((k) => (which === "from" ? metric(n, k)?.fromValue : metric(n, k)?.toValue) != null));
  return { from: has("from"), to: has("to") };
}

export interface SummaryFigure {
  key: "executionTimeMs" | "planningTimeMs" | "rootTotalCost" | "sharedBlocks";
  label: string;
  kind: Provenance;
  unit: MetricUnit;
  from: number | null;
  to: number | null;
  ratio: number | null;
  source: string;
}

const ratio = (a: number | null, b: number | null) => (a !== null && b !== null && a > 0 && b > 0 ? a / b : null);

/** Whole-plan figures from the diff summary, each with its source. Shared buffers are the sum of
 * the per-node self counts each plan recorded. Figures neither plan recorded are left out. */
export function summaryFigures(diff: PlanDiff): SummaryFigure[] {
  const s = diff.summary;
  const sum = (which: "from" | "to") => {
    const v = diff.nodes.map((n) => (which === "from" ? metric(n, "selfSharedBlocks")?.fromValue : metric(n, "selfSharedBlocks")?.toValue) ?? null);
    return v.some((x) => x !== null) ? v.reduce<number>((a, x) => a + (x ?? 0), 0) : null;
  };
  const blocksFrom = sum("from");
  const blocksTo = sum("to");
  const figures: SummaryFigure[] = [
    { key: "executionTimeMs", label: "Execution time", kind: "measured", unit: "ms", ...flat(s.executionTimeMs), source: "One EXPLAIN ANALYZE capture after timing" },
    { key: "planningTimeMs", label: "Planning time", kind: "measured", unit: "ms", ...flat(s.planningTimeMs), source: "Same capture" },
    { key: "rootTotalCost", label: "Root cost", kind: "estimated", unit: "cost", ...flat(s.rootTotalCost), source: "Planner estimate, cost units" },
    { key: "sharedBlocks", label: "Shared buffers", kind: "measured", unit: "blocks", from: blocksFrom, to: blocksTo, ratio: ratio(blocksFrom, blocksTo), source: "Hit + read, summed over plan nodes" },
  ];
  return figures.filter((f) => f.from !== null || f.to !== null);
}

const flat = (d: Delta) => ({ from: d.fromValue, to: d.toValue, ratio: d.ratio });

/** `ratio` is from / to, so above 1 the candidate's figure is lower. Deliberately not "faster":
 * one plan capture is not the benchmark. */
export function ratioText(r: number | null): string | null {
  if (r === null || !Number.isFinite(r) || r <= 0) return null;
  if (Math.abs(r - 1) < 0.005) return "unchanged";
  return r > 1 ? `${r.toFixed(2)}× lower` : `${(1 / r).toFixed(2)}× higher`;
}

/** One-line summary in the style of UI_UX §3.5: "Seq Scan → Index Scan on orders; Sort removed". */
export function diffSummary(diff: PlanDiff): string {
  const parts = diff.nodes
    .filter((n) => n.status === "changed" && n.nodeTypeFrom !== n.nodeTypeTo)
    .map((n) => `${n.nodeTypeFrom} → ${n.nodeTypeTo}${n.relation ? ` on ${n.relation}` : ""}`);
  if (diff.summary.removedNodeTypes.length) parts.push(`${diff.summary.removedNodeTypes.join(", ")} removed`);
  if (diff.summary.addedNodeTypes.length) parts.push(`${diff.summary.addedNodeTypes.join(", ")} added`);
  if (diff.summary.newIndexesUsed.length) parts.push(`new index used: ${diff.summary.newIndexesUsed.join(", ")}`);
  return parts.length ? parts.join("; ") : "No structural change";
}
