import { expect, test } from "vitest";
import type { RunEvent } from "@/lib/api/types";
import { buildTrace } from "@/lib/events/trace";
import { axisBreaks, breakLabel, spacedTicks, compressAxis, eventPosition, longWaits, spanSegments, timeTicks, traceBounds, zoomWindow } from "../waterfall";

const T0 = Date.UTC(2026, 9, 24, 10, 0, 0);
let seq = 0;
function ev(type: string, payload: Record<string, unknown>, ms: number): RunEvent {
  seq += 1;
  return { runId: "r", seq, ts: new Date(T0 + ms).toISOString(), type, payload } as RunEvent;
}

function sample(active: boolean) {
  seq = 0;
  return buildTrace(
    [
      ev("run.status_changed", { from: "queued", to: "running" }, 0),
      ev("node.started", { node: "query_analyzer", agent: "query_analyzer", attempt: 1 }, 1000),
      ev("tool.started", { tool: "get_plan_node", agent: "query_analyzer" }, 2000),
      ev("tool.completed", { tool: "get_plan_node", agent: "query_analyzer", status: "ok", durationMs: 1000, evidenceIds: [] }, 3000),
      ev("node.completed", { node: "query_analyzer", agent: "query_analyzer", attempt: 1, durationMs: 4000 }, 5000),
      ev("node.started", { node: "approval_gate", agent: null, attempt: 1 }, 5000),
      ev("approval.requested", { status: "pending", round: 0 }, 6000),
      ...(active ? [] : [ev("approval.decided", { status: "approved", round: 0 }, 9000)]),
    ],
    { active },
  );
}

test("bounds run from the first event to the run's end, or to now while it is live", () => {
  const done = sample(false);
  expect(traceBounds(done, T0 + 99_000)).toEqual({ startMs: T0, endMs: T0 + 9000 });
  const live = sample(true);
  expect(traceBounds(live, T0 + 12_000)).toEqual({ startMs: T0, endMs: T0 + 12_000 });
  // A clock behind the last event never shrinks the window below what was recorded.
  expect(traceBounds(live, T0 + 1000)).toEqual({ startMs: T0, endMs: T0 + 6000 });
});

test("an agent node is one recorded bar with its tool calls overlaid at their own times", () => {
  const trace = sample(false);
  const win = traceBounds(trace, 0);
  const qa = trace.children.find((s) => s.name === "query_analyzer")!;
  const segs = spanSegments(qa, win, T0 + 9000);
  expect(segs.map((s) => [s.kind, Math.round(s.leftPct), Math.round(s.widthPct)])).toEqual([
    ["agent", 11, 44],
    ["tool", 22, 11],
  ]);
  // Nothing is drawn as a model call: LLM calls are not in the event stream.
  expect(segs.some((s) => (s.kind as string) === "model")).toBe(false);
});

test("an approval wait is its own hatched segment, open-ended to now while pending", () => {
  const done = sample(false);
  const gate = done.children.find((s) => s.name === "approval_gate")!;
  expect(spanSegments(gate, traceBounds(done, 0), T0 + 9000).map((s) => [s.kind, Math.round(s.leftPct), Math.round(s.widthPct)])).toEqual([
    ["step", 56, 44],
    ["wait", 67, 33],
  ]);
  const live = sample(true);
  const openGate = live.children.find((s) => s.name === "approval_gate")!;
  const segs = spanSegments(openGate, traceBounds(live, T0 + 10_000), T0 + 10_000);
  expect(segs.map((s) => s.kind)).toEqual(["step", "wait"]);
  expect(segs[1]).toMatchObject({ clipEnd: false });
  expect(Math.round(segs[1]!.leftPct + segs[1]!.widthPct)).toBe(100);
});

test("an open step of a live run is drawn live to now; one a finished run left open is marked unfinished", () => {
  seq = 0;
  const live = buildTrace([ev("node.started", { node: "collect_context", agent: null, attempt: 1 }, 0)], { active: true });
  expect(spanSegments(live.children[0]!, { startMs: T0, endMs: T0 + 4000 }, T0 + 4000).map((s) => s.kind)).toEqual(["live"]);
  seq = 0;
  const dead = buildTrace(
    [ev("node.started", { node: "collect_context", agent: null, attempt: 1 }, 0), ev("run.status_changed", { to: "failed" }, 2000)],
    { active: false },
  );
  expect(spanSegments(dead.children[0]!, traceBounds(dead, 0), T0 + 9000).map((s) => s.kind)).toEqual(["unfinished"]);
});

test("zooming narrows the window around the focus and clips bars that leave it", () => {
  const bounds = { startMs: 0, endMs: 100_000 };
  expect(zoomWindow(bounds, 1)).toEqual(bounds);
  expect(zoomWindow(bounds, 4, 50_000)).toEqual({ startMs: 37_500, endMs: 62_500 });
  // Clamped at the edges rather than showing time outside the run.
  expect(zoomWindow(bounds, 4, 1000)).toEqual({ startMs: 0, endMs: 25_000 });
  expect(zoomWindow(bounds, 4, 99_000)).toEqual({ startMs: 75_000, endMs: 100_000 });

  const trace = sample(false);
  const qa = trace.children.find((s) => s.name === "query_analyzer")!;
  const [bar] = spanSegments(qa, { startMs: T0 + 3000, endMs: T0 + 9000 }, T0 + 9000);
  expect(bar).toMatchObject({ kind: "agent", leftPct: 0, clipStart: true, clipEnd: false });
  expect(spanSegments(qa, { startMs: T0 + 6000, endMs: T0 + 9000 }, T0 + 9000)).toEqual([]);
});

test("ticks use round steps and are labelled from the run's start", () => {
  expect(timeTicks({ startMs: 0, endMs: 165_000 }, 0).map((t) => t.label)).toEqual(["0s", "30s", "1m", "1m 30s", "2m", "2m 30s"]);
  expect(timeTicks({ startMs: 0, endMs: 2400 }, 0).map((t) => t.label)).toEqual(["0s", "0.5s", "1s", "1.5s", "2s"]);
  const zoomed = timeTicks({ startMs: 10_000, endMs: 20_000 }, 0);
  expect(zoomed[0]).toEqual({ pct: 0, label: "10s" });
  expect(zoomed.every((t) => t.pct >= 0 && t.pct <= 100)).toBe(true);
});

// Compressed time (UI_UX §3.6a): an approval wait that dominates the run is drawn at a fixed
// width so the short agent steps stay inspectable. The linear axis stays the default.
test("only waits that dominate the run are compressed, and a run without one has none", () => {
  const done = sample(false);
  const bounds = traceBounds(done, 0);
  expect(longWaits(done, bounds, T0 + 9000)).toEqual([{ startMs: T0 + 6000, endMs: T0 + 9000 }]);
  // A wait under a quarter of the run is left at its real length.
  expect(longWaits(done, bounds, T0 + 9000, 0.5)).toEqual([]);
  // A pending wait runs to now.
  const live = sample(true);
  expect(longWaits(live, traceBounds(live, T0 + 20_000), T0 + 20_000)).toEqual([{ startMs: T0 + 6000, endMs: T0 + 20_000 }]);
});

test("a compressed wait takes a fixed share of the axis; the rest keeps its proportions", () => {
  const done = sample(false);
  const bounds = traceBounds(done, 0);
  const win = compressAxis(bounds, longWaits(done, bounds, T0 + 9000), 0.06);
  const gate = done.children.find((s) => s.name === "approval_gate")!;
  const wait = spanSegments(gate, win, T0 + 9000).find((s) => s.kind === "wait")!;
  expect(wait.widthPct).toBeCloseTo(6, 5);
  expect(wait.leftPct + wait.widthPct).toBeCloseTo(100, 5);
  const qa = done.children.find((s) => s.name === "query_analyzer")!;
  const [bar, tool] = spanSegments(qa, win, T0 + 9000);
  // 1 s → 5 s of 6 s linear time on 94% of the axis.
  expect(bar!.leftPct).toBeCloseTo((1000 / 6000) * 94, 5);
  expect(bar!.widthPct).toBeCloseTo((4000 / 6000) * 94, 5);
  expect(tool!.widthPct / bar!.widthPct).toBeCloseTo(0.25, 5);
  // The break is reported with its real length, for its label.
  expect(axisBreaks(win)).toEqual([{ startPct: expect.closeTo(94, 5), endPct: expect.closeTo(100, 5), ms: 3000 }]);
  // No tick claims a time inside the compressed wait.
  expect(timeTicks(win, bounds.startMs, 7).map((t) => t.label)).toEqual(["0s", "1s", "2s", "3s", "4s", "5s"]);
  expect(timeTicks(win, bounds.startMs).map((t) => t.label)).toEqual(["0s", "2s", "4s"]);
});

test("zoom works on the drawn axis, and nothing is compressed when no wait qualifies", () => {
  const done = sample(false);
  const bounds = traceBounds(done, 0);
  const win = compressAxis(bounds, longWaits(done, bounds, T0 + 9000), 0.06);
  const zoomed = zoomWindow(win, 2, T0 + 3000);
  expect(zoomed.axis).toBe(win.axis);
  // Half the drawn axis (6383 ms-equivalents), centred on 3 s: 1.40 s to 4.60 s, all linear.
  expect(zoomed.startMs).toBeCloseTo(T0 + 3000 - 6383 / 4, -1);
  expect(zoomed.endMs).toBeCloseTo(T0 + 3000 + 6383 / 4, -1);
  const qa = done.children.find((s) => s.name === "query_analyzer")!;
  expect(eventPosition(qa, zoomed)).toBeNull();
  expect(eventPosition(qa, zoomWindow(win, 2, T0 + 1000))).not.toBeNull();
  expect(compressAxis(bounds, [])).toEqual(bounds);
  // A wait no longer than its compressed width stays linear.
  expect(compressAxis({ startMs: 0, endMs: 1000 }, [{ startMs: 990, endMs: 1000 }]).axis).toBeUndefined();
});

test("axis labels never collide: ticks that would overlap a break label or each other are dropped", () => {
  const ticks = [0, 20, 23, 50, 80, 97].map((pct) => ({ pct, label: `${pct}s` }));
  // On a 600px axis a 3-character label is about 5% wide; "≈ 9h 11m" about 10%.
  expect(spacedTicks(ticks, [], 600).map((t) => t.pct)).toEqual([0, 20, 50, 80, 97]);
  const nineHours = { startPct: 92, endPct: 100, ms: 9 * 3_600_000 + 11 * 60_000 };
  expect(spacedTicks(ticks, [nineHours], 600).map((t) => t.pct)).toEqual([0, 20, 50, 80]);
  // A narrow axis keeps fewer labels.
  expect(spacedTicks(ticks, [nineHours], 200).map((t) => t.pct)).toEqual([0, 20, 50]);
  expect(spacedTicks(ticks, [], 0)).toEqual([]);
});

test("break labels give the real length briefly", () => {
  expect([45_000, 12 * 60_000, 9 * 3_600_000 + 11 * 60_000, 3 * 3_600_000].map(breakLabel)).toEqual(["≈ 45s", "≈ 12m", "≈ 9h 11m", "≈ 3h"]);
});
