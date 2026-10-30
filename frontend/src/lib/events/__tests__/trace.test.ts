import { expect, test } from "vitest";
import type { RunEvent } from "@/lib/api/types";
import { buildTrace, flattenTrace } from "../trace";

let seq = 0;
function ev(type: string, payload: Record<string, unknown>, second = seq): RunEvent {
  seq += 1;
  return { runId: "run-1", seq, ts: new Date(Date.UTC(2026, 9, 12, 10, 0, second)).toISOString(), type, payload } as RunEvent;
}

test("nodes nest under the run, tools nest under the node of their agent", () => {
  seq = 0;
  const trace = buildTrace(
    [
      ev("run.status_changed", { from: "queued", to: "running" }),
      ev("node.started", { node: "intake", agent: null, attempt: 1 }),
      ev("node.completed", { node: "intake", agent: null, attempt: 1, durationMs: 12 }),
      ev("node.started", { node: "query_analyzer", agent: "query_analyzer", attempt: 1 }),
      ev("node.started", { node: "index_strategist", agent: "index_strategist", attempt: 1 }),
      ev("tool.started", { tool: "get_plan_node", agent: "query_analyzer" }),
      ev("tool.started", { tool: "list_indexes", agent: "index_strategist" }),
      ev("tool.completed", { tool: "list_indexes", agent: "index_strategist", status: "ok", durationMs: 40, evidenceIds: ["ev_1", "ev_2"] }),
      ev("tool.completed", { tool: "get_plan_node", agent: "query_analyzer", status: "error", durationMs: 9, evidenceIds: [] }),
      ev("agent.summary", { agent: "query_analyzer", text: "Seq Scan dominates." }),
      ev("node.completed", { node: "query_analyzer", agent: "query_analyzer", attempt: 1, durationMs: 900 }),
    ],
    { active: true },
  );

  expect(trace.kind).toBe("run");
  // run.status_changed stays on the run; three nodes follow it.
  expect(trace.children.map((c) => c.name)).toEqual(["Run running", "intake", "query_analyzer", "index_strategist"]);
  const [, intake, qa, idx] = trace.children;
  expect(intake).toMatchObject({ status: "ok", durationMs: 12 });
  expect(qa!.children.map((c) => [c.kind, c.name])).toEqual([
    ["tool", "get_plan_node"],
    ["event", "query_analyzer: Seq Scan dominates."],
  ]);
  expect(qa!.children[0]).toMatchObject({ status: "error", durationMs: 9 });
  expect(idx!.children[0]).toMatchObject({ kind: "tool", status: "ok", evidenceIds: ["ev_1", "ev_2"] });
  // index_strategist never completed and the run is still active.
  expect(idx!.status).toBe("running");
});

test("an error closes its node as failed and a pending approval marks the open node", () => {
  seq = 0;
  const trace = buildTrace(
    [
      ev("node.started", { node: "index_strategist", agent: "index_strategist", attempt: 1 }),
      ev("error", { node: "index_strategist", code: "AGENT_FAILED", message: "no output" }),
      ev("node.started", { node: "approval_gate", agent: null, attempt: 1 }),
      ev("approval.requested", { status: "pending", round: 0 }),
    ],
    { active: true },
  );

  const [strategist, gate] = trace.children;
  expect(strategist).toMatchObject({ status: "error" });
  expect(strategist!.endTs).toBeDefined();
  expect(strategist!.children[0]).toMatchObject({ kind: "event", status: "error" });
  expect(gate).toMatchObject({ status: "approval" });
});

test("spans left open by a finished run are marked unfinished, not running", () => {
  seq = 0;
  const trace = buildTrace([ev("node.started", { node: "collect_context", agent: null, attempt: 1 })], { active: false });
  expect(trace.children[0]!.status).toBe("unfinished");
});

test("flattenTrace lists visible rows with depth and skips collapsed children", () => {
  seq = 0;
  const trace = buildTrace(
    [
      ev("node.started", { node: "query_analyzer", agent: "query_analyzer", attempt: 1 }),
      ev("tool.started", { tool: "get_plan_node", agent: "query_analyzer" }),
    ],
    { active: true },
  );
  const node = trace.children[0]!;
  expect(flattenTrace(trace, new Set()).map((r) => [r.span.name, r.depth])).toEqual([
    ["query_analyzer", 0],
    ["get_plan_node", 1],
  ]);
  expect(flattenTrace(trace, new Set([node.id])).map((r) => r.span.name)).toEqual(["query_analyzer"]);
});

test("write_report, which never emits node.completed, is closed by the run's conclusion events", () => {
  seq = 0;
  const trace = buildTrace(
    [
      ev("node.started", { node: "write_report", agent: null, attempt: 1 }, 1),
      ev("run.concluded", { finalStatus: "completed", outcome: "verified_recommendation" }, 2),
      ev("report.ready", {}, 3),
    ],
    { active: false },
  );
  const report = trace.children.find((c) => c.name === "write_report")!;
  expect(report).toMatchObject({ status: "ok", durationMs: 1000 });
  expect(report.endTs).toBe(new Date(Date.UTC(2026, 9, 12, 10, 0, 2)).toISOString());
});

test("an approval interrupt closes the gate at the decision and records the wait; the resumed gate is its own span", () => {
  seq = 0;
  // Shape recorded from a local sandbox run: the gate starts, interrupts, and starts again on resume.
  const trace = buildTrace(
    [
      ev("node.started", { node: "approval_gate", agent: null, attempt: 1 }, 10),
      ev("approval.requested", { status: "pending", round: 0 }, 10),
      ev("run.status_changed", { from: "running", to: "awaiting_approval" }, 10),
      ev("approval.decided", { status: "approved", round: 0 }, 45),
      ev("run.status_changed", { from: "awaiting_approval", to: "queued" }, 45),
      ev("node.started", { node: "approval_gate", agent: null, attempt: 1 }, 46),
      ev("node.completed", { node: "approval_gate", agent: null, attempt: 1, durationMs: 15 }, 46),
    ],
    { active: false },
  );
  const gates = trace.children.filter((c) => c.kind === "node");
  expect(gates).toHaveLength(2);
  expect(gates[0]).toMatchObject({ status: "ok", durationMs: 35_000 });
  expect(gates[0]!.resumed).toBeUndefined();
  expect(gates[0]!.wait).toEqual({ startTs: gates[0]!.startTs, endTs: gates[0]!.endTs, decision: "approved" });
  expect(gates[1]).toMatchObject({ status: "ok", durationMs: 15, resumed: true });
});

test("an approval still pending keeps the gate open in the approval state", () => {
  seq = 0;
  const trace = buildTrace(
    [ev("node.started", { node: "approval_gate", agent: null, attempt: 1 }, 1), ev("approval.requested", { status: "pending", round: 1 }, 2)],
    { active: true },
  );
  expect(trace.children[0]).toMatchObject({ status: "approval" });
  expect(trace.children[0]!.endTs).toBeUndefined();
  expect(trace.children[0]!.wait).toEqual({ startTs: trace.children[0]!.children[0]!.startTs });
});

test("on an experiment replay run, the event log never prints the bare stored outcome (REPLAY_OUTCOME_AUDIT §18.1)", () => {
  const texts = (events: RunEvent[]) => flattenTrace(buildTrace(events, { active: false }), new Set()).map((r) => r.span.name);
  const replay = [
    ev("replay.status_changed", { from: null, to: "queued" }, 1),
    ev("run.status_changed", { from: "running", to: "completed", outcome: "verified_recommendation" }, 2),
    ev("run.concluded", { finalStatus: "completed", outcome: "verified_recommendation" }, 3),
  ];
  const lines = texts(replay).join("\n");
  expect(lines).toContain("Run completed");
  expect(lines).not.toMatch(/Run completed · verified recommendation/);
  expect(lines).toContain("Concluded: completed · stored outcome: verified recommendation (legacy replay classification)");
  // a sealed basis still names itself
  const basis = [
    ev("replay.status_changed", { from: null, to: "queued" }, 1),
    ev("run.concluded", { finalStatus: "completed", outcome: "inconclusive", replayBasis: { code: "comparison_reproduced_with_drift" } }, 2),
  ];
  expect(texts(basis).join("\n")).toContain("Concluded: completed · replay basis: comparison reproduced with drift");
  // ordinary runs are unchanged
  const ordinary = [ev("run.status_changed", { from: "running", to: "completed", outcome: "verified_recommendation" }, 1)];
  expect(texts(ordinary).join("\n")).toContain("Run completed · verified recommendation");
});
