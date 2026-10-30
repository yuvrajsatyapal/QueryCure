import type { InvestigationSummary } from "@/lib/api/types";

/* Dashboard summaries computed from the investigation list (each item's latest run). Nothing
 * here is estimated: runs without the timestamps or outcome a summary needs are left out. */

// Most actionable first: a run paused on the user, then work in progress, then the queue.
const ACTIVE_ORDER: Record<string, number> = { awaiting_approval: 0, running: 1, cancelling: 2, queued: 3 };

export function activeFirst(items: InvestigationSummary[]): InvestigationSummary[] {
  return items
    .filter((i) => (i.latestRun?.status ?? "") in ACTIVE_ORDER)
    .sort((a, b) => {
      const rank = ACTIVE_ORDER[a.latestRun!.status]! - ACTIVE_ORDER[b.latestRun!.status]!;
      return rank || Date.parse(b.createdAt) - Date.parse(a.createdAt);
    });
}

export type OutcomeKey =
  | "verified_recommendation"
  | "unverified_recommendations"
  | "no_action_needed"
  | "inconclusive"
  | "replay"
  | "completed"
  | "failed"
  | "cancelled";

const OUTCOMES: readonly string[] = ["verified_recommendation", "unverified_recommendations", "no_action_needed", "inconclusive"];

/** Concluded runs only, keyed by RunOutcome; a completed run with an outcome this UI doesn't know
 * yet still counts, as plain "completed". A completed experiment replay is its own key: its stored
 * outcome is not a verification (REPLAY_OUTCOME_AUDIT §18.1), and the list carries no report. */
export function outcomeBreakdown(items: InvestigationSummary[]): { total: number; parts: { key: OutcomeKey; count: number }[] } {
  const counts = new Map<OutcomeKey, number>();
  for (const { latestRun: run } of items) {
    if (!run) continue;
    let key: OutcomeKey | null = null;
    if (run.status === "completed" && run.kind === "experiment_replay") key = "replay";
    else if (run.status === "completed") key = run.outcome && OUTCOMES.includes(run.outcome) ? (run.outcome as OutcomeKey) : "completed";
    else if (run.status === "failed" || run.status === "cancelled") key = run.status;
    if (key) counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  const parts = [...counts].map(([key, count]) => ({ key, count }));
  return { total: parts.reduce((n, p) => n + p.count, 0), parts };
}

/** Median wall-clock time of completed runs (started_at → finished_at), with how many it covers. */
export function medianRunMs(items: InvestigationSummary[]): { ms: number; n: number } | null {
  const spans = items
    .map((i) => i.latestRun)
    .filter((r) => r?.status === "completed" && r.startedAt && r.finishedAt)
    .map((r) => Date.parse(r!.finishedAt!) - Date.parse(r!.startedAt!))
    .filter((ms) => Number.isFinite(ms) && ms >= 0)
    .sort((a, b) => a - b);
  if (!spans.length) return null;
  const mid = spans.length >> 1;
  const ms = spans.length % 2 ? spans[mid]! : (spans[mid - 1]! + spans[mid]!) / 2;
  return { ms, n: spans.length };
}
