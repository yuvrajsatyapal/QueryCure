"use client";

import Link from "next/link";
import type { RunSummary } from "@/lib/api/types";

/** What each run kind is, in the user's words (GLOSSARY: run, replay, re-investigation). */
export const RUN_KIND_LABEL: Record<string, string> = {
  initial: "Original run",
  reinvestigation: "AI re-investigation",
  experiment_replay: "Experiment replay",
};

const REPLAY_STATUS_TEXT: Record<string, string> = {
  queued: "replay queued",
  running: "replay measuring",
  comparing: "comparing with the original",
  reproduced: "reproduced",
  reproduced_with_drift: "reproduced with drift",
  not_reproduced: "not reproduced",
  inconclusive: "replay inconclusive",
  failed: "replay failed",
  cancelled: "replay cancelled",
  not_replayable: "not replayable",
};

const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

export function runKindLabel(kind: string): string {
  return RUN_KIND_LABEL[kind] ?? kind.replaceAll("_", " ");
}

/** "Experiment replay of run #1", "AI re-investigation of run #2", or the plain kind. */
export function runRelation(run: RunSummary, runs: RunSummary[]): string | null {
  if (!run.parentRunId) return null;
  const parent = runs.find((r) => r.id === run.parentRunId);
  return parent ? `of run #${parent.runNumber}` : "of a run that is no longer available";
}

export function RunPicker({
  runs,
  selectedId,
  onSelect,
}: {
  runs: RunSummary[];
  selectedId: string | null;
  onSelect: (runId: string) => void;
}) {
  if (runs.length < 2) return null;
  const newestFirst = [...runs].sort((a, b) => b.runNumber - a.runNumber);
  return (
    <nav aria-label="Runs of this investigation" className="rounded-lg border border-border bg-surface p-3">
      <p className="mb-2 font-mono text-xs uppercase tracking-wider text-muted">Runs ({runs.length})</p>
      <ul className="flex flex-col gap-1">
        {newestFirst.map((run) => {
          const selected = run.id === selectedId;
          const relation = runRelation(run, runs);
          const children = runs.filter((r) => r.parentRunId === run.id);
          return (
            <li key={run.id} className="min-w-0">
              <button
                type="button"
                aria-current={selected ? "true" : undefined}
                onClick={() => onSelect(run.id)}
                className={`flex w-full min-w-0 flex-col items-start gap-0.5 rounded-md px-2 py-1.5 text-left text-sm ${
                  selected ? "bg-accent-tint" : "hover:bg-surface-2"
                }`}
              >
                <span className="flex w-full min-w-0 flex-wrap items-baseline gap-x-2">
                  <span className="font-medium">#{run.runNumber}</span>
                  <span>{runKindLabel(run.kind)}</span>
                  {relation ? <span className="text-muted">{relation}</span> : null}
                </span>
                <span className="flex w-full min-w-0 flex-wrap gap-x-2 text-xs text-muted">
                  <span>{run.status.replaceAll("_", " ")}</span>
                  {run.outcome ? <span>· {run.outcome.replaceAll("_", " ")}</span> : null}
                  {run.replay ? <span>· {REPLAY_STATUS_TEXT[run.replay.status] ?? run.replay.status}</span> : null}
                  <time dateTime={run.createdAt}>· {dateTime.format(new Date(run.createdAt))}</time>
                </span>
                {children.length ? (
                  <span className="text-xs text-muted">
                    followed by {children.map((c) => `#${c.runNumber} (${runKindLabel(c.kind).toLowerCase()})`).join(", ")}
                  </span>
                ) : null}
              </button>
              {selected && run.finalized ? (
                <Link href={`/app/reports/${run.id}`} className="ml-2 text-xs text-link">
                  Open this run&apos;s report
                </Link>
              ) : null}
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
