"use client";

import "@xyflow/react/dist/style.css";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { useMemo } from "react";
import type { NodeMetrics, PlanNode, PlanTree } from "@/lib/api/types";
import { formatMs, formatPct, formatRows } from "@/lib/format";
import { estimateLabel, isMisestimate } from "@/lib/plan/estimate";
import { hottestNodeId } from "@/lib/plan/hottest";
import { NODE_HEIGHT, NODE_WIDTH, layoutPlan } from "@/lib/plan/layout";

interface CardData extends Record<string, unknown> {
  node: PlanNode;
  metrics: NodeMetrics | undefined;
  hottest: boolean;
  selected: boolean;
}
type CardNode = Node<CardData, "plan">;

function PlanNodeCard({ data }: NodeProps<CardNode>) {
  const { node, metrics: m, hottest, selected } = data;
  const target = node.relationName ?? node.indexName;
  const share = m?.selfTimeShare ?? null;
  return (
    <div
      data-testid="plan-node"
      data-node-id={node.id}
      data-hottest={hottest}
      className={`flex flex-col justify-between overflow-hidden rounded-md px-3 py-2 text-left ${
        hottest ? "border-2 border-accent" : "border border-border-strong"
      } ${selected ? "bg-surface shadow-[inset_0_0_0_999px_var(--accent-tint)] ring-2 ring-accent/40" : "bg-surface"}`}
      style={{ width: NODE_WIDTH, height: NODE_HEIGHT }}
    >
      <Handle type="target" position={Position.Top} className="!opacity-0" isConnectable={false} />
      <div className="flex items-center justify-between gap-2">
        <span className="truncate font-mono text-[13px] font-medium text-ink">{node.nodeType}</span>
        {hottest ? (
          <span className="rounded-sm border border-accent px-1 font-mono text-[10px] uppercase tracking-wider text-accent">
            hottest
          </span>
        ) : null}
      </div>
      <span className="truncate text-xs text-muted">{target ? `on ${target}` : " "}</span>
      <div className="flex items-center justify-between gap-2 font-mono text-[11px] tabular-nums">
        <span className="truncate text-muted">
          est {formatRows(node.planRows)} · act {formatRows(node.actualRows)}
        </span>
        <span className={`shrink-0 ${isMisestimate(m) ? "text-inconclusive" : "text-muted"}`}>{estimateLabel(m)}</span>
      </div>
      <div className="flex items-center gap-2 font-mono text-[11px] tabular-nums text-muted">
        <span aria-hidden className="h-1.5 flex-1 rounded-sm bg-surface-2">
          <span
            className={`block h-full rounded-sm ${hottest ? "bg-accent" : "bg-border-strong"}`}
            style={{ width: `${Math.round((share ?? 0) * 100)}%` }}
          />
        </span>
        <span>{m?.selfTimeMs != null ? `${formatMs(m.selfTimeMs)} · ${formatPct(share)}` : "no timing"}</span>
      </div>
      <Handle type="source" position={Position.Bottom} className="!opacity-0" isConnectable={false} />
    </div>
  );
}

const nodeTypes = { plan: PlanNodeCard };

export function PlanGraph({
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
  const layout = useMemo(() => layoutPlan(plan), [plan]);
  const hottestId = useMemo(() => hottestNodeId(metrics), [metrics]);

  const nodes = useMemo<CardNode[]>(() => {
    const byId = new Map(plan.nodes.map((n) => [n.id, n]));
    const metricsById = new Map(metrics.map((m) => [m.nodeId, m]));
    return layout.nodes.flatMap((pos) => {
      const node = byId.get(pos.id);
      if (!node) return [];
      return [
        {
          id: String(pos.id),
          type: "plan" as const,
          position: { x: pos.x, y: pos.y },
          width: NODE_WIDTH,
          height: NODE_HEIGHT,
          draggable: false,
          connectable: false,
          data: { node, metrics: metricsById.get(pos.id), hottest: pos.id === hottestId, selected: pos.id === selectedId },
        },
      ];
    });
  }, [layout, plan.nodes, metrics, hottestId, selectedId]);

  const edges = useMemo<Edge[]>(
    () =>
      layout.edges.map((e) => ({
        id: e.id,
        source: String(e.source),
        target: String(e.target),
        label: e.rows != null ? `${formatRows(e.rows)} rows${e.estimated ? " (est.)" : ""}` : undefined,
        labelStyle: { fontFamily: "var(--font-mono)", fontSize: 11 },
        style: { strokeWidth: e.width },
        selectable: false,
      })),
    [layout],
  );

  return (
    <figure aria-label="Plan graph" className="flex flex-col gap-2">
      <div className="qd-plan-graph h-[360px] overflow-hidden rounded-lg border border-border md:h-[480px]">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodeClick={(_, n) => onSelect?.(Number(n.id))}
          nodesDraggable={false}
          nodesConnectable={false}
          fitView
          minZoom={0.2}
        >
          <Background variant={BackgroundVariant.Dots} gap={16} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <figcaption className="text-xs text-muted">
        Row counts on cards are per loop; edges show rows across all loops, with width on a log scale.
        The tree view shows the same nodes and is fully keyboard accessible.
      </figcaption>
    </figure>
  );
}
