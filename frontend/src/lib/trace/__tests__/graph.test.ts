import { expect, test } from "vitest";
import type { RunEvent } from "@/lib/api/types";
import { buildTrace } from "@/lib/events/trace";
import { CANVAS, END, GRAPH_LAYOUT, NODE_H, START, TOPOLOGY, edgePath, graphRun, nodeWidth } from "../graph";

let seq = 0;
let clock = 0;
function ev(type: string, payload: Record<string, unknown>, step = 10): RunEvent {
  seq += 1;
  clock += step;
  return { runId: "r", seq, ts: new Date(Date.UTC(2026, 9, 24, 10) + clock).toISOString(), type, payload } as RunEvent;
}
const node = (n: string, agent: string | null = null) => [ev("node.started", { node: n, agent, attempt: 1 }), ev("node.completed", { node: n, agent, attempt: 1, durationMs: 10 })];

// The order recorded from a local sandbox run (stub model), approval interrupt included.
function sandboxRun() {
  seq = 0;
  clock = 0;
  const events = [
    ...node("intake"),
    ...node("collect_context"),
    ...node("supervisor_plan", "supervisor"),
    ev("node.started", { node: "query_analyzer", agent: "query_analyzer", attempt: 1 }),
    ev("node.started", { node: "index_strategist", agent: "index_strategist", attempt: 1 }, 0),
    ev("node.completed", { node: "query_analyzer", agent: "query_analyzer", attempt: 1, durationMs: 30 }),
    ev("node.completed", { node: "index_strategist", agent: "index_strategist", attempt: 1, durationMs: 32 }),
    ...node("synthesize_hypotheses", "supervisor"),
    ...node("optimization_engineer", "optimization_engineer"),
    ev("node.started", { node: "approval_gate", agent: null, attempt: 1 }),
    ev("approval.requested", { status: "pending", round: 0 }),
    ev("approval.decided", { status: "approved", round: 0 }, 500),
    ...node("approval_gate"),
    ...node("run_experiment"),
    ...node("benchmark_auditor", "benchmark_auditor"),
    ev("node.started", { node: "write_report", agent: null, attempt: 1 }),
    ev("run.concluded", { outcome: "verified_recommendation" }),
  ];
  return buildTrace(events, { active: false });
}

test("the topology is the compiled graph's and every node has a place on the canvas", () => {
  expect(TOPOLOGY.nodes).toContain("next_round");
  expect(TOPOLOGY.edges).toContainEqual({ source: "supervisor_plan", target: "workload_investigator", conditional: true });
  for (const n of TOPOLOGY.nodes) expect(GRAPH_LAYOUT[n], n).toBeDefined();
});

test("node states and taken edges come from the recorded steps, fan-out and fan-in included", () => {
  const g = graphRun(sandboxRun());
  expect(g.nodes.get("query_analyzer")).toMatchObject({ state: "done" });
  expect(g.nodes.get("workload_investigator")).toMatchObject({ state: "not_reached", visits: [] });
  expect(g.nodes.get("next_round")!.state).toBe("not_reached");
  // The gate ran twice (interrupt, then resume); both executions are visits, the first one waited.
  expect(g.nodes.get("approval_gate")!.visits).toHaveLength(2);
  expect(g.nodes.get("approval_gate")!.waitMs).toBe(500);
  expect([...g.taken].sort()).toEqual(
    [
      "__start__->intake",
      "intake->collect_context",
      "collect_context->supervisor_plan",
      "supervisor_plan->query_analyzer",
      "supervisor_plan->index_strategist",
      "query_analyzer->synthesize_hypotheses",
      "index_strategist->synthesize_hypotheses",
      "synthesize_hypotheses->optimization_engineer",
      "optimization_engineer->approval_gate",
      "approval_gate->run_experiment",
      "run_experiment->benchmark_auditor",
      "benchmark_auditor->write_report",
      "write_report->__end__",
    ].sort(),
  );
  // No self-edge for the resumed gate, and nothing the topology does not have.
  expect(g.taken.has("approval_gate->approval_gate")).toBe(false);
});

test("an offline run exits to write_report after synthesis; a live step is running and nothing after it is reached", () => {
  seq = 0;
  clock = 0;
  const offline = buildTrace(
    [...node("intake"), ...node("collect_context"), ...node("supervisor_plan", "supervisor"), ...node("query_analyzer", "query_analyzer"), ...node("synthesize_hypotheses", "supervisor"), ev("node.started", { node: "write_report", agent: null, attempt: 1 })],
    { active: true },
  );
  const g = graphRun(offline);
  expect(g.taken.has("synthesize_hypotheses->write_report")).toBe(true);
  expect(g.taken.has("write_report->__end__")).toBe(false);
  expect(g.nodes.get("write_report")!.state).toBe("running");
  expect(g.nodes.get("optimization_engineer")!.state).toBe("not_reached");
});

test("a failed step is failed, and a step a finished run left open is unfinished", () => {
  seq = 0;
  clock = 0;
  const failed = buildTrace(
    [
      ...node("intake"),
      ev("node.started", { node: "collect_context", agent: null, attempt: 1 }),
      ev("error", { node: "collect_context", code: "TARGET_UNAVAILABLE", message: "x" }),
      ev("node.started", { node: "write_report", agent: null, attempt: 1 }),
    ],
    { active: false },
  );
  const g = graphRun(failed);
  expect(g.nodes.get("collect_context")!.state).toBe("failed");
  expect(g.nodes.get("write_report")!.state).toBe("unfinished");
  expect(g.taken.has("collect_context->write_report")).toBe(true);
});

// Canvas geometry (UI_UX §3.6a): narrow enough to read at about 1:1 beside the inspector.
const boxes = TOPOLOGY.nodes
  .filter((n) => n !== START && n !== END)
  .map((n) => ({ n, x: GRAPH_LAYOUT[n]!.x, y: GRAPH_LAYOUT[n]!.y, w: nodeWidth(n), h: NODE_H }));

/** Points along an SVG path made of M, L, Q and C commands with absolute coordinates. */
function samplePath(d: string): { x: number; y: number }[] {
  const tokens = d.match(/[MLQC]|-?\d+(?:\.\d+)?/g) ?? [];
  const pts: { x: number; y: number }[] = [];
  let cur = { x: 0, y: 0 };
  let i = 0;
  const num = () => Number(tokens[i++]);
  while (i < tokens.length) {
    const cmd = tokens[i++];
    if (cmd === "M" || cmd === "L") {
      const next = { x: num(), y: num() };
      if (cmd === "L") for (let k = 1; k <= 20; k += 1) pts.push({ x: cur.x + ((next.x - cur.x) * k) / 20, y: cur.y + ((next.y - cur.y) * k) / 20 });
      cur = next;
    } else if (cmd === "Q" || cmd === "C") {
      const c = cmd === "Q" ? [{ x: num(), y: num() }] : [{ x: num(), y: num() }, { x: num(), y: num() }];
      const end = { x: num(), y: num() };
      const p = [cur, ...c, end];
      for (let k = 1; k <= 20; k += 1) {
        const t = k / 20;
        let q = p;
        while (q.length > 1) q = q.slice(1).map((b, j) => ({ x: q[j]!.x + (b.x - q[j]!.x) * t, y: q[j]!.y + (b.y - q[j]!.y) * t }));
        pts.push(q[0]!);
      }
      cur = end;
    } else throw new Error(`unexpected path command ${cmd}`);
  }
  return pts;
}

test("nodes stay on the canvas, never overlap, and every name fits its box at 12px mono", () => {
  expect(CANVAS.width).toBeLessThanOrEqual(660);
  for (const a of boxes) {
    expect(a.x, a.n).toBeGreaterThanOrEqual(0);
    expect(a.y + a.h, a.n).toBeLessThanOrEqual(CANVAS.height);
    expect(a.x + a.w, a.n).toBeLessThanOrEqual(CANVAS.width);
    // JetBrains Mono advances 0.6em; 26px of horizontal padding.
    expect(a.n.length * 12 * 0.6 + 26, a.n).toBeLessThanOrEqual(a.w);
    for (const b of boxes) {
      if (a === b) continue;
      const apart = a.x + a.w <= b.x || b.x + b.w <= a.x || a.y + a.h <= b.y || b.y + b.h <= a.y;
      expect(apart, `${a.n} overlaps ${b.n}`).toBe(true);
    }
  }
});

test("no edge runs behind a node it does not connect", () => {
  for (const e of TOPOLOGY.edges) {
    const pts = samplePath(edgePath(e.source, e.target));
    for (const b of boxes) {
      if (b.n === e.source || b.n === e.target) continue;
      const hit = pts.find((p) => p.x > b.x + 1 && p.x < b.x + b.w - 1 && p.y > b.y + 1 && p.y < b.y + b.h - 1);
      expect(hit, `${e.source} -> ${e.target} passes behind ${b.n}`).toBeUndefined();
    }
  }
});
