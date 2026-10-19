import { formatMs, formatRows } from "@/lib/format";
import type { NodeMetrics, PlanNode } from "@/lib/api/types";
import type { Citation } from "@/lib/investigation/links";

export interface NodeCitations {
  citation: Citation | undefined;
  /** Claim key → its title or statement, for display. */
  labels: ReadonlyMap<string, string>;
  pending: number;
  failed: number;
  onClaim?: (key: string) => void;
}

/** Findings and hypotheses whose evidence resolves to this node (UI_UX §3.6). */
function CitedBy({ c }: { c: NodeCitations }) {
  const keys = [...(c.citation?.findings ?? []), ...(c.citation?.hypotheses ?? [])];
  return (
    <section aria-label="Cited by" className="mt-4 flex flex-col gap-1.5 border-t border-border pt-3">
      <h4 className="qc-eyebrow">Cited by ({keys.length})</h4>
      {keys.length ? (
        <ul className="flex flex-col gap-1">
          {keys.map((key) => (
            <li key={key} className="flex items-baseline gap-2 text-sm">
              <span className="shrink-0 font-mono text-[11px] text-muted">{key}</span>
              {c.onClaim ? (
                <button type="button" onClick={() => c.onClaim?.(key)} className="min-w-0 text-left text-link hover:underline">
                  {c.labels.get(key) ?? key}
                </button>
              ) : (
                <span className="min-w-0">{c.labels.get(key) ?? key}</span>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted">No finding or hypothesis cites this node{c.pending ? " so far" : ""}.</p>
      )}
      {c.pending ? <p className="text-xs text-muted">Resolving {c.pending} cited evidence item{c.pending === 1 ? "" : "s"}…</p> : null}
      {c.failed ? (
        <p className="text-xs text-rejected">
          {c.failed} cited evidence item{c.failed === 1 ? "" : "s"} could not be loaded, so this list may be incomplete.
        </p>
      ) : null}
    </section>
  );
}

function Row({ label, value }: { label: string; value: string | null | undefined }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="grid grid-cols-[160px_1fr] gap-2 border-t border-border py-1.5 text-sm">
      <dt className="text-muted">{label}</dt>
      <dd className="break-words font-mono text-[13px]">{value}</dd>
    </div>
  );
}

export function NodeDetails({ node, metrics, citations }: { node: PlanNode; metrics: NodeMetrics | undefined; citations?: NodeCitations }) {
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
      {citations ? <CitedBy c={citations} /> : null}
    </section>
  );
}
