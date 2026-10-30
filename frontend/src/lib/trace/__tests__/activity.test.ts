import { expect, test } from "vitest";
import type { RunEvent } from "@/lib/api/types";
import { buildTrace } from "@/lib/events/trace";
import { activityOf, type StreamState } from "../activity";

let seq = 0;
function ev(type: string, payload: Record<string, unknown>): RunEvent {
  seq += 1;
  return { runId: "r", seq, ts: new Date(Date.UTC(2026, 9, 24, 10, 0, seq)).toISOString(), type, payload } as RunEvent;
}
function act(status: string, events: RunEvent[], stream: StreamState = "live", extra: { outcome?: string | null; errorMessage?: string | null } = {}) {
  const active = !["completed", "failed", "cancelled"].includes(status);
  return activityOf({ status, events, trace: buildTrace(events, { active }), stream, outcome: extra.outcome ?? null, errorMessage: extra.errorMessage ?? null });
}

test("a queued run says so and does not animate", () => {
  seq = 0;
  expect(act("queued", [ev("run.status_changed", { to: "queued" })])).toMatchObject({ label: "Queued", tone: "neutral", animate: false });
});

test("the open step names what the run is doing, and only a live running step animates", () => {
  seq = 0;
  const events = [ev("node.started", { node: "collect_context", agent: null, attempt: 1 })];
  expect(act("running", events)).toMatchObject({ label: "Collecting plan and schema context", tone: "running", animate: true, node: "collect_context" });
  expect(act("running", events, "reconnecting")).toMatchObject({ label: "Reconnecting…", animate: false });
  expect(act("running", events, "offline")).toMatchObject({ label: "Live updates stopped", animate: false });
});

test("parallel analysts are counted and named", () => {
  seq = 0;
  const events = [
    ev("node.started", { node: "query_analyzer", agent: "query_analyzer", attempt: 1 }),
    ev("node.started", { node: "index_strategist", agent: "index_strategist", attempt: 1 }),
  ];
  expect(act("running", events)).toMatchObject({ label: "2 analysts inspecting the plan", detail: "query_analyzer and index_strategist in parallel." });
});

test("an experiment reports its latest recorded benchmark state", () => {
  seq = 0;
  const events = [
    ev("node.started", { node: "run_experiment", agent: null, attempt: 1 }),
    ev("benchmark.progress", { state: "provisioning" }),
    ev("benchmark.progress", { state: "measuring", block: 7, blocksTotal: 12, paramSet: "hot_customer" }),
  ];
  expect(act("running", events)).toMatchObject({ label: "Measuring · block 7 of 12", detail: "Timed blocks in a disposable sandbox · param set hot_customer." });
  seq = 0;
  expect(act("running", [ev("node.started", { node: "run_experiment", agent: null, attempt: 1 })])).toMatchObject({ label: "Starting the experiment" });
});

test("waiting on approval, cancelling and the end states are still and say why", () => {
  seq = 0;
  const waiting = [ev("node.started", { node: "approval_gate", agent: null, attempt: 1 }), ev("approval.requested", { status: "pending", round: 1, candidates: [{}, {}] })];
  expect(act("awaiting_approval", waiting)).toMatchObject({ label: "Waiting on you", tone: "approval", animate: false, detail: "Review 2 candidates for round 2. The run is paused until you decide." });
  expect(act("cancelling", waiting)).toMatchObject({ label: "Cancelling", animate: false });
  expect(act("completed", [], "closed", { outcome: "verified_recommendation" })).toMatchObject({ label: "Verified recommendation", tone: "success", animate: false });
  expect(act("completed", [], "closed", { outcome: "inconclusive" })).toMatchObject({ label: "Inconclusive", tone: "warning" });
  expect(act("failed", [], "closed", { errorMessage: "The model was unavailable." })).toMatchObject({ label: "Failed", tone: "failed", detail: "The model was unavailable." });
});

test("a running run between steps does not invent a step", () => {
  seq = 0;
  const events = [ev("node.started", { node: "intake", agent: null, attempt: 1 }), ev("node.completed", { node: "intake", agent: null, attempt: 1, durationMs: 4 })];
  expect(act("running", events)).toMatchObject({ label: "Running", detail: "Waiting for the next step to start.", animate: false, node: null });
});

test("a completed run's label can come from the shared outcome classification (experiment replays)", () => {
  const a = activityOf({
    status: "completed",
    outcome: "verified_recommendation",
    outcomeLabel: { label: "Replay completed", tone: "neutral" },
    errorMessage: null,
    events: [],
    trace: buildTrace([], { active: false }),
    stream: "closed",
  });
  expect(a).toMatchObject({ label: "Replay completed", tone: "neutral", animate: false });
  // without one, the stored outcome is used as before
  expect(act("completed", [], "closed", { outcome: "verified_recommendation" })).toMatchObject({ label: "Verified recommendation", tone: "success" });
});
