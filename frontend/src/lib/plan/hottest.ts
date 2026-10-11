import type { NodeMetrics } from "@/lib/api/types";

// One hottest node by self time; null when the plan has no timing (plain EXPLAIN).
export function hottestNodeId(metrics: NodeMetrics[]): number | null {
  let best: NodeMetrics | null = null;
  for (const m of metrics) {
    if (m.selfTimeMs != null && (best === null || m.selfTimeMs > (best.selfTimeMs ?? 0))) best = m;
  }
  return best?.nodeId ?? null;
}
