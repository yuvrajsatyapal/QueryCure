import { formatMs, formatRows } from "@/lib/format";
import type { NodeMetrics, PlanNode } from "@/lib/api/types";

function Row({ label, value }: { label: string; value: string | null | undefined }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="grid grid-cols-[160px_1fr] gap-2 border-t border-border py-1.5 text-sm">
      <dt className="text-muted">{label}</dt>
      <dd className="break-words font-mono text-[13px]">{value}</dd>
    </div>
  );
}

export function NodeDetails({ node, metrics }: { node: PlanNode; metrics: NodeMetrics | undefined }) {
  const extra = Object.entries(node.extra ?? {}).filter(([, v]) => v !== null && typeof v !== "object");
  return (
    <section aria-label="Plan node details" className="qc-panel p-4">
      <h3 className="text-sm font-semibold">
        {node.nodeType}
        <span className="ml-2 font-mono text-xs text-muted">{node.locator}</span>
      </h3>
      <dl className="mt-2">
        <Row label="Relation" value={node.relationName} />
        <Row label="Index" value={node.indexName} />
        <Row label="Filter" value={node.filter} />
        <Row label="Index condition" value={node.indexCond} />
        <Row label="Sort key" value={node.sortKey?.join(", ")} />
        <Row label="Sort method" value={node.sortMethod} />
        <Row label="Inclusive time" value={metrics?.inclusiveTimeMs != null ? formatMs(metrics.inclusiveTimeMs) : null} />
        <Row label="Loops" value={node.actualLoops != null ? String(node.actualLoops) : null} />
        <Row label="Actual rows, all loops" value={metrics?.totalActualRows != null ? formatRows(metrics.totalActualRows) : null} />
        <Row
          label="Rows removed by filter"
          value={metrics?.rowsRemovedByFilterTotal != null ? formatRows(metrics.rowsRemovedByFilterTotal) : null}
        />
        <Row label="Total cost" value={node.totalCost != null ? String(node.totalCost) : null} />
        {extra.map(([k, v]) => (
          <Row key={k} label={k} value={String(v)} />
        ))}
      </dl>
    </section>
  );
}
