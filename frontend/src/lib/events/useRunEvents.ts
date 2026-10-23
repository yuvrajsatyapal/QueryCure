"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { API_BASE_URL } from "@/lib/api/client";
import { investigationKeys } from "@/lib/api/investigations";
import { optimizationKeys } from "@/lib/api/optimization";
import { reportKeys } from "@/lib/api/reports";
import type { RunEvent } from "@/lib/api/types";
import {
  EVENT_TYPES,
  isTerminal,
  mergeEvents,
  parseEvent,
  reconnectDelayMs,
  runEventsUrl,
} from "./runEvents";

const REFRESH_ON = new Set([
  "finding.created",
  "hypothesis.created",
  "node.completed",
  "budget.warning",
  "run.status_changed",
]);

/** Streams a run's events into the query cache (key: events). The browser resumes with
 * Last-Event-ID after a network drop; after an HTTP error the hook reconnects itself with
 * bounded backoff (`reconnectDelayMs`). It closes the stream once the run is terminal,
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
    let source: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    let lastSeq: number | null = null;
    let done = false;
    const onEvent = (message: MessageEvent<string>) => {
      const event = parseEvent(message.data);
      if (!event) return;
      lastSeq = Math.max(lastSeq ?? 0, event.seq);
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
        done = true;
        source?.close();
        setLive(false);
        void client.invalidateQueries({ queryKey: ["investigations"] });
        void client.invalidateQueries({ queryKey: investigationKeys.findings(runId) });
        void client.invalidateQueries({ queryKey: optimizationKeys.experiments(runId) });
        void client.invalidateQueries({ queryKey: ["experiments"] });
        void client.invalidateQueries({ queryKey: reportKeys.report(runId) });
        void client.invalidateQueries({ queryKey: reportKeys.verifications(runId) });
      }
    };
    const connect = () => {
      const current = new EventSource(runEventsUrl(API_BASE_URL, runId, lastSeq), {
        withCredentials: true,
      });
      source = current;
      current.onopen = () => {
        attempt = 0;
        setLive(true);
      };
      current.onerror = () => {
        setLive(current.readyState === EventSource.OPEN);
        if (done || current.readyState !== EventSource.CLOSED) return;
        const delay = reconnectDelayMs(attempt);
        if (delay === null) return;
        attempt += 1;
        retry = setTimeout(connect, delay);
      };
      for (const type of EVENT_TYPES) current.addEventListener(type, onEvent as EventListener);
    };
    connect();
    return () => {
      done = true;
      clearTimeout(retry);
      source?.close();
      setLive(false);
    };
  }, [runId, client]);

  return { events: data ?? [], live };
}
