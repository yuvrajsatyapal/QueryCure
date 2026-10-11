import dagre from "@dagrejs/dagre";
import type { PlanNode, PlanTree } from "@/lib/api/types";

export const NODE_WIDTH = 240;
export const NODE_HEIGHT = 96;
export const EDGE_MIN_WIDTH = 1;
export const EDGE_MAX_WIDTH = 10;
// log10 of the row count that saturates the edge width (100M rows).
const EDGE_LOG_CEILING = 8;

export interface LaidOutNode {
  id: number;
  x: number;
  y: number;
}

export interface LaidOutEdge {
  id: string;
  source: number;
  target: number;
  rows: number | null;
  estimated: boolean;
  width: number;
}

export function edgeWidth(rows: number | null): number {
  if (rows == null || rows <= 0) return EDGE_MIN_WIDTH;
  const t = Math.min(Math.log10(rows + 1) / EDGE_LOG_CEILING, 1);
  return EDGE_MIN_WIDTH + t * (EDGE_MAX_WIDTH - EDGE_MIN_WIDTH);
}

// Rows flowing out of a child into its parent: actual rows across all loops when the plan was
// analyzed, otherwise the planner's per-loop estimate (flagged so the UI can say so).
function flowRows(node: PlanNode): { rows: number | null; estimated: boolean } {
  if (node.actualRows != null) return { rows: node.actualRows * (node.actualLoops ?? 1), estimated: false };
  return { rows: node.planRows ?? null, estimated: true };
}

export function layoutPlan(plan: PlanTree): { nodes: LaidOutNode[]; edges: LaidOutEdge[] } {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "TB", nodesep: 32, ranksep: 56 });
  g.setDefaultEdgeLabel(() => ({}));

  for (const node of plan.nodes) g.setNode(String(node.id), { width: NODE_WIDTH, height: NODE_HEIGHT });
  const edges: LaidOutEdge[] = [];
  for (const node of plan.nodes) {
    if (node.parentId == null) continue;
    g.setEdge(String(node.parentId), String(node.id));
    const { rows, estimated } = flowRows(node);
    edges.push({ id: `${node.parentId}-${node.id}`, source: node.parentId, target: node.id, rows, estimated, width: edgeWidth(rows) });
  }

  dagre.layout(g);

  const nodes = plan.nodes.map((node) => {
    const pos = g.node(String(node.id));
    // dagre reports centres; React Flow positions by the top-left corner.
    return { id: node.id, x: pos.x - NODE_WIDTH / 2, y: pos.y - NODE_HEIGHT / 2 };
  });
  return { nodes, edges };
}
