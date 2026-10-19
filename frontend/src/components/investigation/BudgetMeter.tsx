import type { RunDetail } from "@/lib/api/types";

const compactNumber = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

/** Run usage against its budget, as reported by GET /runs/{id} (usage, budget). Header-sized:
 * label, used / limit, and a thin bar that turns warning-colored at 80%. */
function Meter({ label, used, limit }: { label: string; used: number; limit: number }) {
  const pct = Math.min(100, Math.round((used / Math.max(limit, 1)) * 100));
  return (
    <div className="flex min-w-0 flex-col gap-1" title={`${label}: ${used.toLocaleString()} of ${limit.toLocaleString()}`}>
      <div className="flex items-baseline justify-between gap-2 text-[11px]">
        <span className="text-muted">{label}</span>
        <span className="font-mono text-ink tabular-nums">
          {compactNumber.format(used)}
          <span className="text-muted">/{compactNumber.format(limit)}</span>
        </span>
      </div>
      <div className="h-1 w-full rounded-full bg-surface-2" role="meter" aria-label={label} aria-valuenow={used} aria-valuemin={0} aria-valuemax={limit}>
        <div className={`h-1 rounded-full ${pct >= 80 ? "bg-inconclusive" : "bg-accent"}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function BudgetMeter({ run }: { run: RunDetail }) {
  const u = run.usage ?? {};
  return (
    <section aria-label="Budget" className="grid w-full grid-cols-3 gap-4 sm:w-80">
      <Meter label="LLM calls" used={u.llmCalls ?? 0} limit={run.budget.llmCalls} />
      <Meter label="Tokens" used={(u.inputTokens ?? 0) + (u.outputTokens ?? 0)} limit={run.budget.totalTokens} />
      <Meter label="Tool calls" used={u.toolCalls ?? 0} limit={run.budget.toolCalls} />
    </section>
  );
}
