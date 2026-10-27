import type { RunDetail, RunEvent } from "@/lib/api/types";
import { formatDuration } from "@/lib/format";

const compactNumber = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

/** One usage figure against its budget, as reported by GET /runs/{id} (usage, budget); the bar
 * turns warning-coloured at 80%. */
function Meter({ label, used, limit }: { label: string; used: number; limit: number }) {
  const pct = Math.min(100, Math.round((used / Math.max(limit, 1)) * 100));
  return (
    <div className="flex min-w-0 flex-col gap-1 px-4 py-2.5" title={`${label}: ${used.toLocaleString()} of ${limit.toLocaleString()}`}>
      <span className="qc-label">{label}</span>
      <span className="font-mono text-lg leading-6 font-medium tabular-nums">
        {compactNumber.format(used)}
        <span className="text-[13px] text-muted"> / {compactNumber.format(limit)}</span>
      </span>
      <div className="h-1 w-full rounded-full bg-surface-2" role="meter" aria-label={label} aria-valuenow={used} aria-valuemin={0} aria-valuemax={limit}>
        <div className={`h-1 rounded-full ${pct >= 80 ? "bg-inconclusive" : "bg-accent"}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function Figure({ label, value, title }: { label: string; value: string; title?: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-1 px-4 py-2.5" title={title}>
      <span className="qc-label">{label}</span>
      <span className="font-mono text-lg leading-6 font-medium tabular-nums">{value}</span>
    </div>
  );
}

/** The run's figures (prototype header strip): wall clock from the run's own timestamps, usage
 * against budget, and counts taken from the recorded events. `nowMs` is null until mounted. */
export function RunStats({ run, events, nowMs }: { run: RunDetail; events: RunEvent[]; nowMs: number | null }) {
  const u = run.usage ?? {};
  const evidence = new Set(events.flatMap((e) => (e.type === "evidence.created" && Array.isArray(e.payload.evidenceIds) ? (e.payload.evidenceIds as string[]) : []))).size;
  const errors = events.filter((e) => e.type === "error").length;
  const started = run.startedAt ? Date.parse(run.startedAt) : null;
  const end = run.finishedAt ? Date.parse(run.finishedAt) : nowMs;
  const duration = started !== null && end !== null ? formatDuration(end - started) : "—";
  const llmCalls = u.llmCalls ?? 0;
  const tokens = (u.inputTokens ?? 0) + (u.outputTokens ?? 0);
  // An experiment replay re-measures in the sandbox and never calls a model (REPLAY_ENGINE §8.2),
  // so a meter against the model budget would suggest calls were allowed. Recorded usage still wins.
  const modelUnused = run.kind === "experiment_replay" && llmCalls === 0 && tokens === 0;
  const unusedTitle = "Experiment replays make no model calls";
  return (
    <section
      aria-label="Budget"
      className="qc-panel grid grid-cols-2 divide-border overflow-hidden sm:grid-cols-3 @4xl:grid-cols-6 [&>*]:border-border [&>*]:-mr-px [&>*]:-mb-px [&>*]:border-b [&>*]:border-r"
    >
      <Figure label="Duration" value={duration} title={run.finishedAt ? "Started → finished" : "Since the run started"} />
      {modelUnused ? (
        <>
          <Figure label="LLM calls" value="Not used" title={unusedTitle} />
          <Figure label="Tokens" value="Not used" title={unusedTitle} />
        </>
      ) : (
        <>
          <Meter label="LLM calls" used={llmCalls} limit={run.budget.llmCalls} />
          <Meter label="Tokens" used={tokens} limit={run.budget.totalTokens} />
        </>
      )}
      <Meter label="Tool calls" used={u.toolCalls ?? 0} limit={run.budget.toolCalls} />
      <Figure label="Evidence" value={String(evidence)} title="Evidence records announced in this run's events" />
      <Figure label="Errors" value={String(errors)} title="Error events in this run" />
    </section>
  );
}
