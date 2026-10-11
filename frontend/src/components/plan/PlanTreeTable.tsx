"use client";

import { useMemo, useRef, useState, type KeyboardEvent } from "react";
import { formatMs, formatPct, formatRows } from "@/lib/format";
import type { NodeMetrics, PlanNode, PlanTree } from "@/lib/api/types";

interface Row {
  node: PlanNode;
  level: number;
  hasChildren: boolean;
}

const ESTIMATE_WARN = 10;

function visibleRows(root: PlanNode, collapsed: Set<number>): Row[] {
  const out: Row[] = [];
  const walk = (node: PlanNode, level: number) => {
    const children = node.children ?? [];
    out.push({ node, level, hasChildren: children.length > 0 });
    if (!collapsed.has(node.id)) children.forEach((c) => walk(c, level + 1));
  };
  walk(root, 1);
  return out;
}

function label(node: PlanNode): string {
  const target = node.relationName ?? node.indexName;
  return target ? ` on ${target}` : "";
}

export function PlanTreeTable({
  plan,
  metrics,
  onSelect,
  selectedId,
}: {
  plan: PlanTree;
  metrics: NodeMetrics[];
  onSelect?: (nodeId: number) => void;
  selectedId?: number | null;
}) {
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());
  const [focusId, setFocusId] = useState<number>(plan.root.id);
  const rowRefs = useRef(new Map<number, HTMLTableRowElement>());
  const byId = useMemo(() => new Map(metrics.map((m) => [m.nodeId, m])), [metrics]);
  const rows = useMemo(() => visibleRows(plan.root, collapsed), [plan.root, collapsed]);
  const parents = useMemo(() => new Map(plan.nodes.map((n) => [n.id, n.parentId ?? null])), [plan.nodes]);
  const hottestId = useMemo(() => {
    let best: NodeMetrics | null = null;
    for (const m of metrics) if (m.selfTimeMs != null && (best === null || m.selfTimeMs > (best.selfTimeMs ?? 0))) best = m;
    return best?.nodeId ?? null;
  }, [metrics]);

  const focusRow = (id: number) => {
    setFocusId(id);
    rowRefs.current.get(id)?.focus();
  };
  const toggle = (id: number, expand: boolean) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (expand) next.delete(id);
      else next.add(id);
      return next;
    });

  function onKeyDown(event: KeyboardEvent, row: Row, index: number) {
    const id = row.node.id;
    const isCollapsed = collapsed.has(id);
    const handled = ["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Home", "End", "Enter", " "];
    if (!handled.includes(event.key)) return;
    event.preventDefault();
    if (event.key === "ArrowDown" && rows[index + 1]) focusRow(rows[index + 1]!.node.id);
    else if (event.key === "ArrowUp" && rows[index - 1]) focusRow(rows[index - 1]!.node.id);
    else if (event.key === "Home") focusRow(rows[0]!.node.id);
    else if (event.key === "End") focusRow(rows[rows.length - 1]!.node.id);
    else if (event.key === "ArrowRight" && row.hasChildren) {
      if (isCollapsed) toggle(id, true);
      else if (rows[index + 1]) focusRow(rows[index + 1]!.node.id);
    } else if (event.key === "ArrowLeft") {
      if (row.hasChildren && !isCollapsed) toggle(id, false);
      else {
        const parent = parents.get(id);
        if (parent !== null && parent !== undefined) focusRow(parent);
      }
    } else if (event.key === "Enter" || event.key === " ") onSelect?.(id);
  }

  return (
    <div className="flex flex-col gap-2">
      {!plan.analyzed ? (
        <p className="rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-muted">
          Estimates only: this plan came from plain EXPLAIN, so actual rows and timings are unavailable.
        </p>
      ) : null}
      <div className="overflow-x-auto rounded-lg border border-border">
        <table role="treegrid" aria-label="Execution plan" className="w-full min-w-[720px] border-collapse text-sm">
          <thead className="bg-surface-2 text-left text-xs text-muted">
            <tr role="row">
              {["Node", "Est. rows / loop", "Actual rows / loop", "Estimate", "Self time", "Buffers read / hit"].map((h) => (
                <th key={h} role="columnheader" className="px-3 py-2 font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => {
              const m = byId.get(row.node.id);
              const hottest = row.node.id === hottestId;
              const selected = row.node.id === selectedId;
              const ratio = m?.estimateErrorRatio;
              return (
                <tr
                  key={row.node.id}
                  ref={(el) => {
                    if (el) rowRefs.current.set(row.node.id, el);
                    else rowRefs.current.delete(row.node.id);
                  }}
                  role="row"
                  aria-level={row.level}
                  aria-expanded={row.hasChildren ? !collapsed.has(row.node.id) : undefined}
                  aria-selected={selected}
                  tabIndex={row.node.id === focusId ? 0 : -1}
                  onKeyDown={(e) => onKeyDown(e, row, index)}
                  onFocus={() => setFocusId(row.node.id)}
                  onClick={() => onSelect?.(row.node.id)}
                  className={`cursor-pointer border-t border-border font-mono text-[13px] tabular-nums hover:bg-surface-2 ${
                    selected ? "bg-accent-tint" : ""
                  } ${hottest ? "shadow-[inset_3px_0_0_var(--accent)]" : ""}`}
                >
                  <td role="gridcell" className="px-3 py-2 font-sans" style={{ paddingLeft: `${12 + (row.level - 1) * 16}px` }}>
                    {row.hasChildren ? (
                      <span aria-hidden className="mr-1 inline-block w-3 text-muted">
                        {collapsed.has(row.node.id) ? "▸" : "▾"}
                      </span>
                    ) : (
                      <span aria-hidden className="mr-1 inline-block w-3" />
                    )}
                    <span className="font-medium">{row.node.nodeType}</span>
                    <span className="text-muted">{label(row.node)}</span>
                    {hottest ? (
                      <span className="ml-2 rounded-sm border border-accent px-1 font-mono text-[11px] uppercase tracking-wider text-accent">
                        hottest
                      </span>
                    ) : null}
                    {m?.sortSpilled ? (
                      <span className="ml-2 text-xs text-inconclusive">spilled to disk</span>
                    ) : null}
                  </td>
                  <td role="gridcell" className="px-3 py-2 text-right">{formatRows(row.node.planRows)}</td>
                  <td role="gridcell" className="px-3 py-2 text-right">{formatRows(row.node.actualRows)}</td>
                  <td role="gridcell" className={`px-3 py-2 ${ratio != null && ratio >= ESTIMATE_WARN ? "text-inconclusive" : "text-muted"}`}>
                    {ratio != null && m?.estimateDirection && m.estimateDirection !== "exact"
                      ? `${ratio.toFixed(ratio >= 10 ? 0 : 1)}× ${m.estimateDirection}`
                      : ratio != null
                        ? "exact"
                        : "—"}
                  </td>
                  <td role="gridcell" className="px-3 py-2">
                    {m?.selfTimeMs != null ? `${formatMs(m.selfTimeMs)} · ${formatPct(m.selfTimeShare)}` : "—"}
                  </td>
                  <td role="gridcell" className="px-3 py-2 text-muted">
                    {m?.selfSharedReadBlocks != null ? `${formatRows(m.selfSharedReadBlocks)} / ${formatRows(m.selfSharedHitBlocks)}` : "—"}
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
