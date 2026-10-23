import { toCamel } from "@/lib/api/case";
import type { RunEvent } from "@/lib/api/types";

/** Every event type the API can send (API_DESIGN §3). EventSource only delivers named events
 * to listeners registered for that name, so the hook subscribes to each one. */
export const EVENT_TYPES = [
  "run.status_changed",
  "node.started",
  "node.completed",
  "agent.summary",
  "tool.started",
  "tool.completed",
  "evidence.created",
  "finding.created",
  "hypothesis.created",
  "hypothesis.updated",
  "budget.warning",
  "error",
  "candidate.created",
  "approval.requested",
  "approval.decided",
  "benchmark.progress",
  "verification.completed",
  "run.concluded",
  "report.ready",
  "replay.status_changed",
  "replay.compared",
] as const;

export const TERMINAL = new Set(["completed", "failed", "cancelled"]);

/** Wire `data:` JSON → camelCase event; null for anything malformed. */
export function parseEvent(data: string): RunEvent | null {
  try {
    const parsed = toCamel(JSON.parse(data)) as RunEvent;
    return typeof parsed.seq === "number" && typeof parsed.type === "string" ? parsed : null;
  } catch {
    return null;
  }
}

/** Merge by seq: a reconnect may resend nothing (Last-Event-ID) but a refetch of history can
 * overlap the stream, so duplicates are dropped and order is restored. */
export function mergeEvents(current: RunEvent[], incoming: RunEvent[]): RunEvent[] {
  const bySeq = new Map(current.map((e) => [e.seq, e]));
  for (const e of incoming) bySeq.set(e.seq, e);
  return [...bySeq.values()].sort((a, b) => a.seq - b.seq);
}

export function isTerminal(event: RunEvent): boolean {
  const to = (event.payload as { to?: unknown }).to;
  return event.type === "run.status_changed" && typeof to === "string" && TERMINAL.has(to);
}

const POLLED = new Set(["queued", "running", "awaiting_approval", "cancelling"]);
const RUN_POLL_MS = 5000;

/** Refetch interval for a run's detail. LLM calls emit no event, so usage meters would sit
 * frozen through a long agent node; poll while the run is active. */
export function runRefetchInterval(status: string | undefined): number | false {
  return status !== undefined && POLLED.has(status) ? RUN_POLL_MS : false;
}

/** The browser resumes a dropped stream on its own (with Last-Event-ID), but an HTTP error on
 * a reconnect (a 5xx, or 503 during a database outage) closes the EventSource for good. The
 * hook then reconnects itself, resuming with `after_seq` because a new EventSource sends no
 * Last-Event-ID. */
export const MAX_RECONNECTS = 6;

export function runEventsUrl(base: string, runId: string, afterSeq: number | null): string {
  const url = `${base}/api/v1/runs/${encodeURIComponent(runId)}/events`;
  return afterSeq === null ? url : `${url}?after_seq=${afterSeq}`;
}

/** 1, 2, 4, 8, 16, 30 s, then null: give up and show the stream as not live. */
export function reconnectDelayMs(attempt: number): number | null {
  if (attempt >= MAX_RECONNECTS) return null;
  return Math.min(1000 * 2 ** attempt, 30_000);
}
