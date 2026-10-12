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
