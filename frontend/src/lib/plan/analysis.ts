import type { NodeMetrics, PlanNode, PlanTree } from "@/lib/api/types";
import { formatRows } from "@/lib/format";
import { ESTIMATE_WARN } from "./estimate";
import { hottestNodeId } from "./hottest";

// Display thresholds only (UI_UX §3.16); no verdict reads them.
export const EXPENSIVE_SHARE = 0.2;
export const ESTIMATE_SEVERE = 100;
// Below this many rows on the larger side, summed over all loops, a ratio is not worth a flag.
export const ESTIMATE_MIN_ROWS = 100;

export type EstimateLevel = "unavailable" | "never_executed" | "stopped_early" | "ok" | "small" | "significant" | "severe";

export interface EstimateAssessment {
  level: EstimateLevel;
  ratio: number | null;
  direction: string | null;
}

// Nodes that read their whole input before emitting a row: a LIMIT above them cannot cut
// their input short. A sorted (streaming) aggregate is not one of them.
function consumesAllInput(node: PlanNode): boolean {
  if (node.nodeType === "Sort" || node.nodeType === "Hash") return true;
  return node.nodeType === "Aggregate" && (node.extra as Record<string, unknown> | undefined)?.Strategy !== "Sorted";
}

/** True when a LIMIT above can stop this node before it returns every row, so fewer actual
 * rows than estimated is expected rather than a planner error. */
export function stopsEarly(plan: PlanTree, id: number): boolean {
  const byId = new Map(plan.nodes.map((x) => [x.id, x]));
  for (let p = byId.get(id)?.parentId ?? null; p !== null; p = byId.get(p)?.parentId ?? null) {
    const parent = byId.get(p);
    if (!parent) return false;
    if (parent.nodeType === "Limit") return true;
    if (consumesAllInput(parent)) return false;
  }
  return false;
}

/** Judges the backend's per-loop error ratio; never recomputes it. */
export function estimateAssessment(
  node: PlanNode,
  m: NodeMetrics | undefined,
  context: { stoppedEarly?: boolean } = {},
): EstimateAssessment {
  const ratio = m?.estimateErrorRatio ?? null;
  const direction = m?.estimateDirection ?? null;
  if (node.actualLoops === 0) return { level: "never_executed", ratio, direction };
  if (ratio === null) return { level: "unavailable", ratio, direction };
  if (ratio < ESTIMATE_WARN) return { level: "ok", ratio, direction };
  if (context.stoppedEarly && direction === "over") return { level: "stopped_early", ratio, direction };
  const loops = node.actualLoops ?? 1;
  const larger = Math.max(node.planRows ?? 0, node.actualRows ?? 0) * loops;
  if (larger < ESTIMATE_MIN_ROWS) return { level: "small", ratio, direction };
  return { level: ratio >= ESTIMATE_SEVERE ? "severe" : "significant", ratio, direction };
}

export function isFlaggedEstimate(level: EstimateLevel): boolean {
  return level === "significant" || level === "severe";
}

export function estimateSentence(node: PlanNode, m: NodeMetrics | undefined, context: { stoppedEarly?: boolean } = {}): string {
  const expected = `${formatRows(node.planRows)} rows per loop`;
  const a = estimateAssessment(node, m, context);
  if (a.level === "never_executed") return `Never executed: the planner expected ${expected}.`;
  if (a.level === "unavailable") return `Planner expected ${expected}; actual rows not measured (plain EXPLAIN).`;
  const verdict = a.direction === "exact" || a.ratio === null ? "exact" : `${a.ratio.toFixed(a.ratio >= 10 ? 0 : 1)}× ${a.direction}`;
  const early = a.level === "stopped_early" ? ", expected below a LIMIT that stopped the node early" : "";
  return `Planner expected ${expected}; ${formatRows(node.actualRows)} returned: ${verdict}${early}.`;
}

export interface NodeFlags {
  hottest: boolean;
  expensive: boolean;
  estimate: EstimateAssessment;
}

export function nodeFlags(plan: PlanTree, metrics: NodeMetrics[]): Map<number, NodeFlags> {
  const byId = new Map(metrics.map((x) => [x.nodeId, x]));
  const hottest = hottestNodeId(metrics);
  return new Map(
    plan.nodes.map((node) => {
      const m = byId.get(node.id);
      const share = m?.selfTimeShare ?? null;
      const estimate = estimateAssessment(node, m, { stoppedEarly: stopsEarly(plan, node.id) });
      return [node.id, { hottest: node.id === hottest, expensive: share !== null && share >= EXPENSIVE_SHARE, estimate }];
    }),
  );
}

export interface PlanSummary {
  nodes: number;
  analyzed: boolean;
  hasTiming: boolean;
  hasBuffers: boolean;
  planningTimeMs: number | null;
  executionTimeMs: number | null;
  expensive: number;
  misestimates: number;
  hottestId: number | null;
}

export function planSummary(plan: PlanTree, metrics: NodeMetrics[]): PlanSummary {
  const flags = [...nodeFlags(plan, metrics).values()];
  return {
    nodes: plan.nodes.length,
    analyzed: plan.analyzed,
    hasTiming: plan.hasTiming,
    hasBuffers: plan.hasBuffers,
    planningTimeMs: plan.planningTimeMs ?? null,
    executionTimeMs: plan.executionTimeMs ?? null,
    expensive: flags.filter((f) => f.expensive).length,
    misestimates: flags.filter((f) => isFlaggedEstimate(f.estimate.level)).length,
    hottestId: hottestNodeId(metrics),
  };
}

/** Parents of a node from the root down: what must expand for it to be visible. */
export function ancestorIds(plan: PlanTree, id: number): number[] {
  const parent = new Map(plan.nodes.map((x) => [x.id, x.parentId ?? null]));
  if (!parent.has(id)) return [];
  const out: number[] = [];
  for (let p = parent.get(id) ?? null; p !== null; p = parent.get(p) ?? null) out.unshift(p);
  return out;
}

export function expandableIds(plan: PlanTree): number[] {
  return plan.nodes.filter((x) => (x.children ?? []).length > 0).map((x) => x.id);
}

/** Planner total cost relative to the costliest node. Total cost is cumulative, and a Limit
 * root can be cheaper than its child, so the root is not a usable denominator. */
export function costShare(plan: PlanTree, node: PlanNode): number | null {
  const max = Math.max(0, ...plan.nodes.map((x) => x.totalCost ?? 0));
  if (node.totalCost == null || max <= 0) return null;
  return node.totalCost / max;
}
