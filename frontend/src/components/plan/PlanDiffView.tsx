"use client";

import { useQuery } from "@tanstack/react-query";
import { ErrorNotice } from "@/components/common/ErrorNotice";
import { getPlanDiff, reportKeys } from "@/lib/api/reports";
import type { PlanDiff, PlanNodeDiff } from "@/lib/api/types";
import { formatMs } from "@/lib/format";

const STATUS: Record<string, { label: string; className: string }> = {
  same: { label: "same", className: "text-muted" },
  changed: { label: "changed", className: "text-inconclusive" },
  added: { label: "added", className: "text-verified" },
  removed: { label: "removed", className: "text-rejected" },
};

function nodeLabel(n: PlanNodeDiff): string {
  if (n.status === "changed" && n.nodeTypeFrom !== n.nodeTypeTo) return `${n.nodeTypeFrom} → ${n.nodeTypeTo}`;
  return n.nodeTypeTo ?? n.nodeTypeFrom ?? "?";
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

export function PlanDiffTable({ diff }: { diff: PlanDiff }) {
  const exec = diff.summary.executionTimeMs;
  return (
    <div className="flex flex-col gap-2">
      <p className="text-sm font-medium">{diffSummary(diff)}</p>
      {exec.fromValue !== null && exec.toValue !== null ? (
        <p className="text-xs text-muted">
          Execution time in the captured EXPLAIN ANALYZE: {formatMs(exec.fromValue)} → {formatMs(exec.toValue)} (one capture, measured; the benchmark
          table is the measurement that decides)
        </p>
      ) : null}
      {/* Scrolls sideways in narrow panes (the inspector), so it is a tab stop for keyboard users. */}
      <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Node changes, baseline versus candidate">
        <table className="w-full min-w-[520px] text-left text-sm">
          <caption className="sr-only">Plan nodes, baseline versus candidate</caption>
          <thead className="font-mono text-[11px] uppercase text-muted">
            <tr>
              <th className="py-1 pr-2">Node</th>
              <th className="py-1 pr-2">Change</th>
              <th className="py-1 pr-2">Relation / index</th>
              <th className="py-1">Inclusive time</th>
            </tr>
          </thead>
          <tbody>
            {diff.nodes.map((n, i) => {
              const t = n.metrics.inclusiveTimeMs;
              const s = STATUS[n.status] ?? { label: n.status, className: "text-muted" };
              return (
                <tr key={i} className="border-t border-border">
                  <td className="py-1 pr-2" style={{ paddingLeft: `${n.depth * 12}px` }}>
                    {nodeLabel(n)}
                  </td>
                  <td className={`py-1 pr-2 font-mono text-xs ${s.className}`}>
                    {s.label}
                    {n.changes.length ? ` (${n.changes.join(", ")})` : ""}
                  </td>
                  <td className="py-1 pr-2 font-mono text-xs">
                    {n.relation ?? ""}
                    {n.indexTo || n.indexFrom ? ` · ${n.indexTo ?? n.indexFrom}` : ""}
                  </td>
                  <td className="py-1 font-mono text-xs">
                    {t ? `${formatMs(t.fromValue)} → ${formatMs(t.toValue)}` : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function PlanDiffView({ runId, from, to }: { runId: string; from: string; to: string }) {
  const diff = useQuery({
    queryKey: reportKeys.planDiff(runId, from, to),
    queryFn: ({ signal }) => getPlanDiff(runId, from, to, signal),
  });
  if (diff.error) return <ErrorNotice error={diff.error} />;
  if (!diff.data) return <p className="text-sm text-muted">Comparing plans…</p>;
  return <PlanDiffTable diff={diff.data.diff} />;
}
