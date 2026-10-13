"use client";

import { useEffect, useRef, useState } from "react";
import type { RunEvent } from "@/lib/api/types";

type Payload = Record<string, unknown>;
const ANNOUNCE_EVERY_MS = 5000;

function str(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** One line per event, in words (status is never colour alone). */
export function describe(event: RunEvent): { text: string; tone: "normal" | "muted" | "error" } {
  const p = event.payload as Payload;
  switch (event.type) {
    case "run.status_changed":
      return { text: `Run ${str(p.to)}${p.outcome ? ` · ${str(p.outcome).replaceAll("_", " ")}` : ""}`, tone: "normal" };
    case "node.started":
      return { text: `${str(p.node)} started`, tone: "muted" };
    case "node.completed":
      return { text: `${str(p.node)} done · ${Number(p.durationMs ?? 0)} ms`, tone: "muted" };
    case "agent.summary":
      return { text: `${str(p.agent)}: ${str(p.text)}`, tone: "normal" };
    case "tool.started":
      return { text: `${str(p.agent)} → ${str(p.tool)}`, tone: "muted" };
    case "tool.completed": {
      const ids = Array.isArray(p.evidenceIds) ? p.evidenceIds.length : 0;
      return {
        text: `${str(p.tool)} ${str(p.status)} · ${Number(p.durationMs ?? 0)} ms · ${ids} evidence`,
        tone: p.status === "ok" ? "muted" : "error",
      };
    }
    case "evidence.created":
      return { text: `+${Array.isArray(p.evidenceIds) ? p.evidenceIds.length : 0} evidence`, tone: "muted" };
    case "finding.created":
      return { text: `Finding: ${str(p.title)}`, tone: "normal" };
    case "hypothesis.created":
      return { text: `Hypothesis: ${str(p.category)} (${str(p.confidence)})`, tone: "normal" };
    case "budget.warning":
      return { text: `Budget: ${str(p.budget)} at ${Number(p.used)}/${Number(p.limit)}`, tone: "error" };
    case "candidate.created":
      return { text: `Candidate ${str(p.key)}: ${str(p.kind).replaceAll("_", " ")}`, tone: "normal" };
    case "approval.requested":
      return {
        text: p.status === "pending" ? `Approval needed for round ${Number(p.round ?? 0) + 1}` : `Approval recorded (${str(p.decidedBy)})`,
        tone: "normal",
      };
    case "approval.decided":
      return { text: `Approval ${str(p.status).replaceAll("_", " ")}`, tone: "normal" };
    case "benchmark.progress": {
      const block = typeof p.block === "number" && typeof p.blocksTotal === "number" ? ` · block ${p.block}/${p.blocksTotal}` : "";
      return { text: `Benchmark ${str(p.state).replaceAll("_", " ")}${block}`, tone: "muted" };
    }
    case "verification.completed": {
      const reasons = Array.isArray(p.reasons) && p.reasons.length ? ` (${str((p.reasons[0] as Payload).code)})` : "";
      return { text: `${str(p.candidateKey)}: ${str(p.verdict)}${reasons}`, tone: p.verdict === "rejected" ? "error" : "normal" };
    }
    case "run.concluded":
      return { text: `Concluded: ${str(p.finalStatus)}${p.outcome ? ` · ${str(p.outcome).replaceAll("_", " ")}` : ""}`, tone: "normal" };
    case "report.ready":
      return { text: "Final report sealed", tone: "normal" };
    case "replay.status_changed":
      return { text: `Replay ${str(p.to).replaceAll("_", " ")}${p.failureCode ? ` (${str(p.failureCode)})` : ""}`, tone: p.to === "failed" ? "error" : "normal" };
    case "replay.compared":
      return { text: `Replay compared: ${str(p.status).replaceAll("_", " ")} (${str(p.comparisonMode).replaceAll("_", " ")})`, tone: "normal" };
    case "error":
      return { text: `Error in ${str(p.node)}: ${str(p.code)} — ${str(p.message)}`, tone: "error" };
    default:
      return { text: event.type, tone: "muted" };
  }
}

const TONE = { normal: "text-ink", muted: "text-muted", error: "text-rejected" } as const;

export function Timeline({ events, live }: { events: RunEvent[]; live: boolean }) {
  const [announcement, setAnnouncement] = useState("");
  const latest = useRef<string>("");
  const last = events.at(-1);
  const lastText = last ? describe(last).text : "";
  useEffect(() => {
    latest.current = lastText;
  }, [lastText]);
  useEffect(() => {
    // Screen readers get at most one update every 5 s (DESIGN_SYSTEM §9).
    const timer = setInterval(() => setAnnouncement(latest.current), ANNOUNCE_EVERY_MS);
    return () => clearInterval(timer);
  }, []);

  return (
    <section aria-label="Agent timeline" className="flex min-w-0 flex-col gap-2">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Timeline</h2>
        <span className="font-mono text-[11px] text-muted">{live ? "● live" : "○ not streaming"}</span>
      </div>
      <p className="sr-only" aria-live="polite">
        {announcement}
      </p>
      {events.length === 0 ? (
        <p className="text-sm text-muted">Waiting for the worker to pick up the run…</p>
      ) : (
        <ol className="flex max-h-[60vh] flex-col gap-1 overflow-y-auto">
          {events.map((e) => {
            const { text, tone } = describe(e);
            return (
              <li key={e.seq} className={`flex gap-2 text-sm ${TONE[tone]}`}>
                <time className="shrink-0 font-mono text-[11px] text-muted" dateTime={e.ts} title={e.ts}>
                  {new Date(e.ts).toLocaleTimeString()}
                </time>
                <span className="min-w-0 break-words">{text}</span>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
