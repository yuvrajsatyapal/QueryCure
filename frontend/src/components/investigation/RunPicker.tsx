"use client";

import { Icon } from "@/components/ui/Icon";
import { StatusOrb, runStatusMeta } from "@/components/ui/StatusPill";
import { timeAgo } from "@/components/history/InvestigationRow";
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

export interface RunGroup {
  key: "investigation" | "replay";
  label: string;
  runs: RunSummary[];
}

/** Investigation runs (original and re-investigations, and any other kind that is not a replay)
 * then experiment replays, each newest first. Empty groups are left out. Report replays are not
 * runs and never appear here. */
export function groupRuns(runs: RunSummary[]): RunGroup[] {
  const newestFirst = [...runs].sort((a, b) => b.runNumber - a.runNumber);
  const groups: RunGroup[] = [
    { key: "investigation", label: "Investigation runs", runs: newestFirst.filter((r) => r.kind !== "experiment_replay") },
    { key: "replay", label: "Experiment replays", runs: newestFirst.filter((r) => r.kind === "experiment_replay") },
  ];
  return groups.filter((g) => g.runs.length > 0);
}

/** The run selector's menu content (UI_UX §3.6c): labelled groups of `menuitemradio` rows. Focus
 * and keys are the RunSelector's; only the selected row is a tab stop. Orbs are still: these are
 * recorded statuses (UI_UX §3.6b). */
export function RunPicker({ runs, selectedId, onSelect }: { runs: RunSummary[]; selectedId: string | null; onSelect: (runId: string) => void }) {
  return (
    <>
      {groupRuns(runs).map((group, gi) => (
        <div key={group.key} role="group" aria-label={group.label} className={gi > 0 ? "mt-1.5 border-t border-border pt-1.5" : undefined}>
          <div aria-hidden="true" className="flex items-baseline gap-2 px-2 pt-1 pb-1">
            <span className="qc-eyebrow">{group.label}</span>
            <span className="font-mono text-[11px] text-muted">{group.runs.length}</span>
          </div>
          {group.runs.map((run) => (
            <RunItem key={run.id} run={run} runs={runs} selected={run.id === selectedId} onSelect={onSelect} />
          ))}
        </div>
      ))}
    </>
  );
}

function RunItem({ run, runs, selected, onSelect }: { run: RunSummary; runs: RunSummary[]; selected: boolean; onSelect: (runId: string) => void }) {
  const status = runStatusMeta(run.status);
  const relation = runRelation(run, runs);
  const children = runs.filter((r) => r.parentRunId === run.id).sort((a, b) => a.runNumber - b.runNumber);
  return (
    <button
      type="button"
      role="menuitemradio"
      aria-checked={selected}
      // Roving tab stop on the selected run: keeps the scrolling list keyboard-reachable (axe
      // scrollable-region-focusable); arrows move focus, Tab closes the menu.
      tabIndex={selected ? 0 : -1}
      onClick={() => onSelect(run.id)}
      className={`grid w-full min-w-0 grid-cols-[14px_minmax(0,1fr)_auto] items-start gap-x-2.5 rounded-md px-2 py-1.5 text-left text-[13px] leading-[18px] outline-none pointer-coarse:min-h-11 pointer-coarse:py-2 ${
        selected ? "bg-accent-tint" : "hover:bg-hover focus:bg-hover"
      }`}
    >
      <StatusOrb tone={status.tone} size={14} className="mt-0.5" />
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="flex min-w-0 flex-wrap items-baseline gap-x-1.5">
          <span className="font-mono font-medium text-ink">#{run.runNumber}</span>
          <span className="text-ink">{runKindLabel(run.kind)}</span>
          {relation ? <span className="min-w-0 break-words text-muted">{relation}</span> : null}
        </span>
        <span className="flex min-w-0 flex-wrap gap-x-1.5 text-xs text-muted">
          <span>{status.label}</span>
          {run.outcome ? <span>· {run.outcome.replaceAll("_", " ")}</span> : null}
          {run.replay ? <span>· {REPLAY_STATUS_TEXT[run.replay.status] ?? run.replay.status.replaceAll("_", " ")}</span> : null}
        </span>
        {children.length ? (
          <span className="text-xs break-words text-muted">
            followed by {children.map((c) => `#${c.runNumber} (${runKindLabel(c.kind).toLowerCase()})`).join(", ")}
          </span>
        ) : null}
      </span>
      <span className="flex items-center gap-1.5">
        <time dateTime={run.createdAt} title={dateTime.format(new Date(run.createdAt))} className="font-mono text-xs text-muted">
          {timeAgo(run.createdAt)}
        </time>
        {selected ? <Icon name="check" size={14} data-selected-mark="" className="text-accent" /> : <span aria-hidden="true" className="w-3.5" />}
      </span>
    </button>
  );
}
