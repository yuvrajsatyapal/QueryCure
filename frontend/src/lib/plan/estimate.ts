import type { NodeMetrics } from "@/lib/api/types";

// Misestimates at or beyond this factor are highlighted (DESIGN_SYSTEM PlanNode).
export const ESTIMATE_WARN = 10;

export function estimateLabel(m: NodeMetrics | undefined): string {
  const ratio = m?.estimateErrorRatio;
  if (ratio == null) return "—";
  if (!m?.estimateDirection || m.estimateDirection === "exact") return "exact";
  return `${ratio.toFixed(ratio >= 10 ? 0 : 1)}× ${m.estimateDirection}`;
}

export function isMisestimate(m: NodeMetrics | undefined): boolean {
  return m?.estimateErrorRatio != null && m.estimateErrorRatio >= ESTIMATE_WARN;
}
