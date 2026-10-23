"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { formatCost, formatMs, formatPct, formatRows } from "@/lib/format";
import { estimateLabel } from "@/lib/plan/estimate";
import { costShare, isFlaggedEstimate, nodeFlags, type EstimateAssessment } from "@/lib/plan/analysis";
import type { NodeMetrics, PlanNode, PlanTree } from "@/lib/api/types";
import { usePlanCollapse, type PlanCollapse } from "./usePlanCollapse";

interface Row {
  node: PlanNode;
  level: number;
  hasChildren: boolean;
}

function visibleRows(root: PlanNode, collapsed: ReadonlySet<number>): Row[] {
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

const tag = "ml-2 rounded-sm border px-1 font-mono text-[11px] uppercase tracking-wider whitespace-nowrap";

/** The estimate error with its severity in words (UI_UX §3.16). */
export function EstimateCell({ estimate, metrics }: { estimate: EstimateAssessment; metrics: NodeMetrics | undefined }) {
  if (estimate.level === "never_executed") return <span className="text-muted">never executed</span>;
  const flagged = isFlaggedEstimate(estimate.level);
  const tone = estimate.level === "severe" ? "text-rejected" : flagged ? "text-inconclusive" : "text-muted";
  return (
    <span className={tone}>
      <span>{estimateLabel(metrics)}</span>
      {flagged ? <span className="ml-1 font-sans text-[11px]">{estimate.level}</span> : null}
      {estimate.level === "small" ? <span className="ml-1 font-sans text-[11px]">small rows</span> : null}
      {estimate.level === "stopped_early" ? <span className="ml-1 font-sans text-[11px]">LIMIT above</span> : null}
    </span>
  );
}

export function PlanTreeTable({
  plan,
  metrics,
  onSelect,
  selectedId,
  citationCounts,
  collapse,
}: {
  plan: PlanTree;
  metrics: NodeMetrics[];
  onSelect?: (nodeId: number) => void;
  selectedId?: number | null;
  /** Findings + hypotheses citing each node (UI_UX §3.6); omitted when not computed. */
  citationCounts?: ReadonlyMap<number, number>;
  /** Collapse state owned by a parent (PlanExplorer); otherwise the table keeps its own. */
  collapse?: PlanCollapse;
}) {
  const own = usePlanCollapse(plan, selectedId);
  const { collapsed, toggle } = collapse ?? own;
  const [focusId, setFocusId] = useState<number>(plan.root.id);
  const [followed, setFollowed] = useState(selectedId);
  if (selectedId !== followed) {
    setFollowed(selectedId);
    if (selectedId != null) setFocusId(selectedId);
  }
  const rowRefs = useRef(new Map<number, HTMLTableRowElement>());
  const byId = useMemo(() => new Map(metrics.map((m) => [m.nodeId, m])), [metrics]);
  const flags = useMemo(() => nodeFlags(plan, metrics), [plan, metrics]);
  const rows = useMemo(() => visibleRows(plan.root, collapsed), [plan.root, collapsed]);
  const parents = useMemo(() => new Map(plan.nodes.map((n) => [n.id, n.parentId ?? null])), [plan.nodes]);
  const costed = useMemo(() => new Map(plan.nodes.map((n) => [n.id, costShare(plan, n)])), [plan]);
  const timed = plan.hasTiming;

  useEffect(() => {
    if (selectedId == null) return;
    rowRefs.current.get(selectedId)?.scrollIntoView?.({ block: "nearest" });
  }, [selectedId, rows]);

  const focusRow = (id: number) => {
    setFocusId(id);
    rowRefs.current.get(id)?.focus();
  };

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

  const headers = [
    "Node",
    "Est. rows / loop",
    "Actual rows / loop",
    "Loops",
    "Estimate",
    timed ? "Est. cost" : "Est. cost (cumulative)",
    "Time / loop",
    "Self time",
    "Buffers read / hit",
  ];

  return (
    <div className="flex flex-col gap-2">
      {!plan.analyzed ? (
        <p className="rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-muted">
          Estimates only: this plan came from plain EXPLAIN, so actual rows and timings are unavailable.
        </p>
      ) : null}
      <div className="overflow-x-auto rounded-lg border border-border">
        <table role="treegrid" aria-label="Execution plan" className="w-full min-w-[1040px] border-collapse text-sm">
          <thead className="bg-surface-2 text-left text-xs text-muted">
            <tr role="row">
              {headers.map((h) => (
                <th key={h} role="columnheader" className="px-3 py-2 font-medium whitespace-nowrap">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => {
              const node = row.node;
              const m = byId.get(node.id);
              const f = flags.get(node.id);
              const selected = node.id === selectedId;
              const share = costed.get(node.id) ?? null;
              return (
                <tr
                  key={node.id}
                  ref={(el) => {
                    if (el) rowRefs.current.set(node.id, el);
                    else rowRefs.current.delete(node.id);
                  }}
                  role="row"
                  aria-level={row.level}
                  aria-expanded={row.hasChildren ? !collapsed.has(node.id) : undefined}
                  aria-selected={selected}
                  data-node-id={node.id}
                  tabIndex={node.id === focusId ? 0 : -1}
                  onKeyDown={(e) => onKeyDown(e, row, index)}
                  onFocus={() => setFocusId(node.id)}
                  onClick={() => onSelect?.(node.id)}
                  className={`cursor-pointer border-t border-border font-mono text-[13px] tabular-nums hover:bg-surface-2 ${
                    selected ? "bg-accent-tint" : ""
                  } ${f?.hottest ? "shadow-[inset_3px_0_0_var(--accent)]" : ""}`}
                >
                  <td role="gridcell" className="px-3 py-2 font-sans" style={{ paddingLeft: `${12 + (row.level - 1) * 16}px` }}>
                    {row.hasChildren ? (
                      <button
                        type="button"
                        tabIndex={-1}
                        aria-label={collapsed.has(node.id) ? `Expand ${node.nodeType}` : `Collapse ${node.nodeType}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          toggle(node.id, collapsed.has(node.id));
                        }}
                        className="mr-1 inline-block w-3 text-muted hover:text-ink"
                      >
                        <span aria-hidden>{collapsed.has(node.id) ? "▸" : "▾"}</span>
                      </button>
                    ) : (
                      <span aria-hidden className="mr-1 inline-block w-3" />
                    )}
                    {node.parentRelationship && node.parentRelationship !== "Outer" && node.parentRelationship !== "Member" ? (
                      <span className="mr-1 text-[11px] text-muted">{node.subplanName ?? node.parentRelationship} ›</span>
                    ) : null}
                    <span className="font-medium">{node.nodeType}</span>
                    <span className="text-muted">{label(node)}</span>
                    {f?.hottest ? <span className={`${tag} border-accent text-accent`}>hottest</span> : null}
                    {f?.expensive ? <span className={`${tag} border-inconclusive/60 text-inconclusive`}>expensive</span> : null}
                    {citationCounts?.get(node.id) ? (
                      <span className="ml-2 rounded-full border border-border px-1.5 text-[11px] whitespace-nowrap text-muted">
                        cited by {citationCounts.get(node.id)}
                      </span>
                    ) : null}
                    {m?.sortSpilled ? <span className="ml-2 text-xs text-inconclusive">spilled to disk</span> : null}
                  </td>
                  <td role="gridcell" className="px-3 py-2 text-right">{formatRows(node.planRows)}</td>
                  <td role="gridcell" className="px-3 py-2 text-right">{formatRows(node.actualRows)}</td>
                  <td role="gridcell" className="px-3 py-2 text-right text-muted">{node.actualLoops != null ? formatRows(node.actualLoops) : "—"}</td>
                  <td role="gridcell" className="px-3 py-2 whitespace-nowrap">
                    {f ? <EstimateCell estimate={f.estimate} metrics={m} /> : "—"}
                  </td>
                  <td role="gridcell" className="px-3 py-2 whitespace-nowrap text-muted">
                    {node.totalCost != null ? `${formatCost(node.startupCost)}..${formatCost(node.totalCost)}` : "—"}
                    {!timed && share !== null ? (
                      <span aria-hidden className="mt-1 block h-1 w-24 rounded-sm bg-surface-2">
                        <span className="block h-full rounded-sm bg-border-strong" style={{ width: `${Math.round(share * 100)}%` }} />
                      </span>
                    ) : null}
                  </td>
                  <td role="gridcell" className="px-3 py-2 whitespace-nowrap text-muted">
                    {node.actualTotalTimeMs != null ? formatMs(node.actualTotalTimeMs) : "—"}
                  </td>
                  <td role="gridcell" className="px-3 py-2 whitespace-nowrap">
                    {m?.selfTimeMs != null ? `${formatMs(m.selfTimeMs)} · ${formatPct(m.selfTimeShare)}` : "—"}
                  </td>
                  <td role="gridcell" className="px-3 py-2 whitespace-nowrap text-muted">
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
