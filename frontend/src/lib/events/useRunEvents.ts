"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { API_BASE_URL } from "@/lib/api/client";
import { investigationKeys } from "@/lib/api/investigations";
import { optimizationKeys } from "@/lib/api/optimization";
import { reportKeys } from "@/lib/api/reports";
import type { RunEvent } from "@/lib/api/types";
import { EVENT_TYPES, isTerminal, mergeEvents, parseEvent } from "./runEvents";

const REFRESH_ON = new Set([
  "finding.created",
  "hypothesis.created",
  "node.completed",
  "budget.warning",
  "run.status_changed",
]);

/** Streams a run's events into the query cache (key: events). The browser resumes with
 * Last-Event-ID after a drop; the hook closes the stream itself once the run is terminal,
 * because EventSource would otherwise reconnect forever. */
export function useRunEvents(runId: string | null): { events: RunEvent[]; live: boolean } {
  const client = useQueryClient();
  const [live, setLive] = useState(false);
  const key = investigationKeys.events(runId ?? "none");
  const { data } = useQuery<RunEvent[]>({
    queryKey: key,
    queryFn: () => client.getQueryData<RunEvent[]>(key) ?? [],
    enabled: false,
    initialData: [],
  });

  useEffect(() => {
    if (!runId || typeof EventSource === "undefined") return;
    const source = new EventSource(`${API_BASE_URL}/api/v1/runs/${runId}/events`, {
      withCredentials: true,
    });
    const onEvent = (message: MessageEvent<string>) => {
      const event = parseEvent(message.data);
      if (!event) return;
      client.setQueryData<RunEvent[]>(investigationKeys.events(runId), (prev) =>
        mergeEvents(prev ?? [], [event]),
      );
      if (event.type === "finding.created" || event.type === "hypothesis.created") {
        void client.invalidateQueries({ queryKey: investigationKeys.findings(runId) });
      }
      if (REFRESH_ON.has(event.type)) {
        void client.invalidateQueries({ queryKey: investigationKeys.run(runId), exact: true });
      }
      if (event.type === "candidate.created") {
        void client.invalidateQueries({ queryKey: optimizationKeys.candidates(runId) });
      }
      if (event.type === "approval.requested" || event.type === "approval.decided") {
        void client.invalidateQueries({ queryKey: optimizationKeys.approvals(runId) });
        void client.invalidateQueries({ queryKey: optimizationKeys.candidates(runId) });
      }
      if (event.type === "verification.completed" || (event.type === "benchmark.progress" && (event.payload as { state?: string }).state === "provisioning")) {
        void client.invalidateQueries({ queryKey: optimizationKeys.experiments(runId) });
        void client.invalidateQueries({ queryKey: optimizationKeys.candidates(runId) });
        void client.invalidateQueries({ queryKey: ["experiments"] });
      }
      if (event.type === "verification.completed") {
        void client.invalidateQueries({ queryKey: reportKeys.verifications(runId) });
      }
      if (event.type === "replay.status_changed" || event.type === "replay.compared") {
        void client.invalidateQueries({ predicate: (q) => q.queryKey.includes("replay-attempts") });
      }
      if (event.type === "evidence.created") {
        void client.invalidateQueries({ queryKey: investigationKeys.plans(runId) });
      }
      if (isTerminal(event)) {
        source.close();
        setLive(false);
        void client.invalidateQueries({ queryKey: ["investigations"] });
        void client.invalidateQueries({ queryKey: investigationKeys.findings(runId) });
        void client.invalidateQueries({ queryKey: optimizationKeys.experiments(runId) });
        void client.invalidateQueries({ queryKey: ["experiments"] });
        void client.invalidateQueries({ queryKey: reportKeys.report(runId) });
        void client.invalidateQueries({ queryKey: reportKeys.verifications(runId) });
      }
    };
    source.onopen = () => setLive(true);
    source.onerror = () => setLive(source.readyState === EventSource.OPEN);
    for (const type of EVENT_TYPES) source.addEventListener(type, onEvent as EventListener);
    return () => {
      source.close();
      setLive(false);
    };
  }, [runId, client]);

  return { events: data ?? [], live };
}
