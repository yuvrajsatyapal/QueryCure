import { expect, test } from "vitest";
import type { RunEvent } from "@/lib/api/types";
import {
  MAX_RECONNECTS,
  isTerminal,
  mergeEvents,
  parseEvent,
  reconnectDelayMs,
  runEventsUrl,
  runRefetchInterval,
} from "../runEvents";

const ev = (seq: number, type = "node.started", payload: Record<string, unknown> = {}): RunEvent =>
  ({ runId: "r", seq, ts: "2026-10-12T00:00:00.000Z", type, payload }) as RunEvent;

test("wire JSON is parsed and camelCased", () => {
  const parsed = parseEvent(
    '{"run_id":"r","seq":3,"ts":"t","type":"tool.completed","payload":{"duration_ms":5,"evidence_ids":["ev_1"]}}',
  );

  expect(parsed?.runId).toBe("r");
  expect(parsed?.payload).toEqual({ durationMs: 5, evidenceIds: ["ev_1"] });
});

test("malformed data is ignored", () => {
  expect(parseEvent("not json")).toBeNull();
  expect(parseEvent('{"type":"x"}')).toBeNull();
});

test("merging dedupes by seq and restores order", () => {
  const merged = mergeEvents([ev(1), ev(3)], [ev(2), ev(3), ev(4)]);

  expect(merged.map((e) => e.seq)).toEqual([1, 2, 3, 4]);
});

test("only terminal status changes close the stream", () => {
  expect(isTerminal(ev(9, "run.status_changed", { to: "completed" }))).toBe(true);
  expect(isTerminal(ev(9, "run.status_changed", { to: "cancelling" }))).toBe(false);
  expect(isTerminal(ev(9, "node.completed", { to: "completed" }))).toBe(false);
});

test("an active run's usage is polled; a finished or unknown run is not", () => {
  // No event marks individual LLM calls, so a long agent node (with retries) would otherwise
  // leave the budget meters frozen until the node completes.
  for (const status of ["queued", "running", "awaiting_approval", "cancelling"]) {
    expect(runRefetchInterval(status)).toBe(5000);
  }
  for (const status of ["completed", "failed", "cancelled", undefined]) {
    expect(runRefetchInterval(status)).toBe(false);
  }
});

test("a manual reconnect resumes after the last delivered seq", () => {
  expect(runEventsUrl("https://api.example", "r1", null)).toBe("https://api.example/api/v1/runs/r1/events");
  expect(runEventsUrl("https://api.example", "r1", 0)).toBe(
    "https://api.example/api/v1/runs/r1/events?after_seq=0",
  );
  expect(runEventsUrl("https://api.example", "r 1", 41)).toBe(
    "https://api.example/api/v1/runs/r%201/events?after_seq=41",
  );
});

test("reconnect delays back off exponentially, are capped, and stop after the limit", () => {
  expect(reconnectDelayMs(0)).toBe(1000);
  expect(reconnectDelayMs(1)).toBe(2000);
  expect(reconnectDelayMs(3)).toBe(8000);
  expect(reconnectDelayMs(MAX_RECONNECTS - 1)).toBeLessThanOrEqual(30_000);
  expect(reconnectDelayMs(MAX_RECONNECTS)).toBeNull();
});
