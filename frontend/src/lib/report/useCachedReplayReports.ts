"use client";

import { useQueries } from "@tanstack/react-query";
import { useMemo } from "react";
import { getReport, reportKeys } from "@/lib/api/reports";
import type { RunSummary } from "@/lib/api/types";
import { replayReportMeta, type ReplayReportMeta, type ReplayReportState } from "./replay";

/** Replay report metadata for list views, read from the query cache only (REPLAY_OUTCOME_AUDIT
 * §18.2). Lists never fetch a report per row: a replay whose report this session has not loaded
 * reads "Replay completed" until a summary field exists on the list endpoint. */
export function useCachedReplayReports(runs: (RunSummary | null | undefined)[]): ReadonlyMap<string, ReplayReportState> {
  const ids = runs.filter((r): r is RunSummary => r?.kind === "experiment_replay" && r.status === "completed").map((r) => r.id);
  const key = useQueries({
    queries: ids.map((id) => ({
      queryKey: reportKeys.report(id),
      queryFn: ({ signal }: { signal: AbortSignal }) => getReport(id, signal),
      enabled: false,
      staleTime: Infinity,
    })),
    combine: (results) => JSON.stringify(results.flatMap((q, i) => (q.data ? [[ids[i], replayReportMeta(q.data)] as const] : []))),
  });
  return useMemo(
    () => new Map((JSON.parse(key) as [string, ReplayReportMeta][]).map(([id, meta]) => [id, { status: "loaded", meta } as const])),
    [key],
  );
}
