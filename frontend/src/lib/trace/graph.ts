import type { Span } from "@/lib/events/trace";
import { evidenceIdsOfSpan } from "@/lib/investigation/links";
import topology from "./langgraph-topology.json";

/* The graph view (UI_UX §3.6): the compiled LangGraph topology (a JSON copy kept identical by a
 * backend contract test), with each node's state and each taken edge derived from the run's
 * recorded node spans. A node with no events is "not reached"; nothing is inferred beyond that. */

export interface TopologyEdge {
  source: string;
  target: string;
  conditional: boolean;
}

export const TOPOLOGY: { nodes: string[]; edges: TopologyEdge[] } = topology;
export const START = "__start__";
export const END = "__end__";
export const REPORT = "write_report";

export type NodeState = "done" | "running" | "approval" | "failed" | "unfinished" | "not_reached";

export interface GraphNode {
  state: NodeState;
  visits: Span[];
  /** Sum of the recorded durations of finished visits. */
  durationMs: number;
  toolCalls: number;
  evidence: number;
  /** Recorded time spent waiting for a human decision. */
  waitMs: number;
}

const edgeKey = (a: string, b: string) => `${a}->${b}`;
const known = new Set(TOPOLOGY.edges.map((e) => edgeKey(e.source, e.target)));

function stateOf(visits: Span[]): NodeState {
  if (!visits.length) return "not_reached";
  if (visits.some((v) => v.status === "approval" && !v.endTs)) return "approval";
  if (visits.some((v) => v.status === "running")) return "running";
  if (visits.some((v) => v.status === "error")) return "failed";
  if (visits.some((v) => v.status === "unfinished")) return "unfinished";
  return "done";
}

/** Groups node spans into LangGraph steps: spans that started before any span of the current
 * step finished ran in the same step (the analysts' fan-out). A span resumed after an approval
 * interrupt continues its step rather than starting a new one. */
function steps(nodes: Span[]): Span[][] {
  const out: Span[][] = [];
  for (const s of nodes) {
    if (s.resumed) continue;
    const current = out.at(-1);
    const start = Date.parse(s.startTs);
    const firstEnd = current ? Math.min(...current.map((c) => (c.endTs ? Date.parse(c.endTs) : Infinity))) : -Infinity;
    if (current && start < firstEnd) current.push(s);
    else out.push([s]);
  }
  return out;
}

export function graphRun(trace: Span): { nodes: Map<string, GraphNode>; taken: Set<string> } {
  const spans = trace.children.filter((c) => c.kind === "node");
  const nodes = new Map<string, GraphNode>();
  for (const name of TOPOLOGY.nodes) {
    if (name === START || name === END) continue;
    const visits = spans.filter((s) => s.name === name);
    const evidence = new Set(visits.flatMap((v) => [...evidenceIdsOfSpan(v), ...v.children.flatMap(evidenceIdsOfSpan)]));
    nodes.set(name, {
      state: stateOf(visits),
      visits,
      durationMs: visits.reduce((t, v) => t + (v.endTs ? (v.durationMs ?? 0) : 0), 0),
      toolCalls: visits.reduce((t, v) => t + v.children.filter((c) => c.kind === "tool").length, 0),
      evidence: evidence.size,
      waitMs: visits.reduce((t, v) => t + (v.wait?.endTs ? Date.parse(v.wait.endTs) - Date.parse(v.wait.startTs) : 0), 0),
    });
  }

  const taken = new Set<string>();
  const grouped = steps(spans);
  if (grouped[0]?.some((s) => known.has(edgeKey(START, s.name)))) taken.add(edgeKey(START, grouped[0][0]!.name));
  for (let i = 1; i < grouped.length; i += 1) {
    for (const a of grouped[i - 1]!) for (const b of grouped[i]!) if (known.has(edgeKey(a.name, b.name))) taken.add(edgeKey(a.name, b.name));
  }
  if (trace.endTs && nodes.get(REPORT)?.state === "done") taken.add(edgeKey(REPORT, END));
  return { nodes, taken };
}

/** Canvas positions (px) for the graph view: three columns read top-down — the analysis chain,
 * the analysts' fan-out side by side, synthesis, the Mode C optimisation loop — and write_report,
 * the terminal every stop routes to, on its own row at the bottom. Narrow enough to draw at about
 * 1:1 in the trace pane beside the inspector; exits to write_report run down a right-hand bus. */
export const NODE_W = 180;
export const NODE_H = 54;
const COL = [20, 220, 420];
const ROW = { chain: 20, analysts: 116, synth: 224, loop: 320, audit: 416, report: 508 };
/** The right-hand bus the exits to write_report run down, clear of every column. */
const BUS_X = COL[2]! + NODE_W + 20;
export const CANVAS = { width: BUS_X + 16, height: ROW.report + NODE_H + 40 };
export const ANALYST_GROUP = { x: 8, y: ROW.analysts - 26, width: COL[2]! + NODE_W + 12 - 8, height: NODE_H + 26 + 24 };
export const GRAPH_LAYOUT: Record<string, { x: number; y: number; w?: number }> = {
  [START]: { x: 8, y: ROW.chain + NODE_H / 2 },
  intake: { x: COL[0]!, y: ROW.chain },
  collect_context: { x: COL[1]!, y: ROW.chain },
  supervisor_plan: { x: COL[2]!, y: ROW.chain },
  query_analyzer: { x: COL[0]!, y: ROW.analysts },
  index_strategist: { x: COL[1]!, y: ROW.analysts },
  workload_investigator: { x: COL[2]!, y: ROW.analysts },
  synthesize_hypotheses: { x: COL[1]!, y: ROW.synth },
  optimization_engineer: { x: COL[0]!, y: ROW.loop },
  approval_gate: { x: COL[1]!, y: ROW.loop },
  run_experiment: { x: COL[2]!, y: ROW.loop },
  next_round: { x: COL[1]!, y: ROW.audit },
  benchmark_auditor: { x: COL[2]!, y: ROW.audit },
  write_report: { x: COL[2]!, y: ROW.report },
  [END]: { x: COL[2]! + NODE_W / 2, y: ROW.report + NODE_H + 24 },
};

export const nodeWidth = (name: string) => GRAPH_LAYOUT[name]?.w ?? NODE_W;

type Side = "left" | "right" | "top" | "bottom";
function anchor(name: string, side: Side): { x: number; y: number } {
  const p = GRAPH_LAYOUT[name]!;
  if (name === START || name === END) return { x: p.x, y: p.y };
  const w = nodeWidth(name);
  if (side === "left") return { x: p.x, y: p.y + NODE_H / 2 };
  if (side === "right") return { x: p.x + w, y: p.y + NODE_H / 2 };
  if (side === "top") return { x: p.x + w / 2, y: p.y };
  return { x: p.x + w / 2, y: p.y + NODE_H };
}

/** An orthogonal path through `pts` with rounded corners. */
function polyline(pts: { x: number; y: number }[], r = 6): string {
  let d = `M${pts[0]!.x} ${pts[0]!.y}`;
  for (let i = 1; i < pts.length - 1; i += 1) {
    const [a, b, c] = [pts[i - 1]!, pts[i]!, pts[i + 1]!];
    const k1 = Math.min(r, Math.hypot(b.x - a.x, b.y - a.y) / 2);
    const k2 = Math.min(r, Math.hypot(c.x - b.x, c.y - b.y) / 2);
    const u = { x: Math.sign(b.x - a.x), y: Math.sign(b.y - a.y) };
    const v = { x: Math.sign(c.x - b.x), y: Math.sign(c.y - b.y) };
    d += ` L${b.x - u.x * k1} ${b.y - u.y * k1} Q ${b.x} ${b.y}, ${b.x + v.x * k2} ${b.y + v.y * k2}`;
  }
  const last = pts.at(-1)!;
  return `${d} L${last.x} ${last.y}`;
}

/** An exit to write_report: straight down from the node above it; from the row above, along the
 * gap to its top; from anywhere else, out through the gap under the source row and down the bus. */
function reportPath(source: string): string {
  const s = anchor(source, "bottom");
  const t = anchor(REPORT, "top");
  const above = GRAPH_LAYOUT[source]!.y === ROW.audit;
  if (above && Math.abs(s.x - t.x) < 1) return `M${s.x} ${s.y} L${t.x} ${t.y}`;
  const entryX = t.x + NODE_W / 4;
  const entryY = t.y - 14;
  if (above) return polyline([s, { x: s.x, y: entryY }, { x: entryX, y: entryY }, { x: entryX, y: t.y }]);
  const gapY = s.y + 8;
  return polyline([s, { x: s.x, y: gapY }, { x: BUS_X, y: gapY }, { x: BUS_X, y: entryY }, { x: entryX, y: entryY }, { x: entryX, y: t.y }]);
}

/** An SVG path between two nodes, routed by their relative position: sideways on one row,
 * down to a lower row, back up for the round loop, and down the bus to write_report. */
export function edgePath(source: string, target: string): string {
  if (target === REPORT) return reportPath(source);
  const a = GRAPH_LAYOUT[source]!;
  const b = GRAPH_LAYOUT[target]!;
  const sameRow = source !== START && target !== END && Math.abs(a.y - b.y) < NODE_H / 2;
  if (sameRow || source === START) {
    const rightward = b.x > a.x;
    const s = anchor(source, rightward ? "right" : "left");
    const t = anchor(target, rightward ? "left" : "right");
    const mid = (s.x + t.x) / 2;
    return `M${s.x} ${s.y} C ${mid} ${s.y}, ${mid} ${t.y}, ${t.x} ${t.y}`;
  }
  const down = b.y > a.y;
  const s = anchor(source, down ? "bottom" : "top");
  const t = anchor(target, down ? "top" : "bottom");
  const mid = (s.y + t.y) / 2;
  return `M${s.x} ${s.y} C ${s.x} ${mid}, ${t.x} ${mid}, ${t.x} ${t.y}`;
}
