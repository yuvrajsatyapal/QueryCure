import type { RunDetail } from "@/lib/api/types";

function Row({ label, used, limit }: { label: string; used: number; limit: number }) {
  const pct = Math.min(100, Math.round((used / Math.max(limit, 1)) * 100));
  return (
    <div className="flex flex-col gap-1">
      <div className="flex justify-between font-mono text-[11px] text-muted">
        <span>{label}</span>
        <span>
          {used.toLocaleString()} / {limit.toLocaleString()}
        </span>
      </div>
      <div className="h-1 rounded-full bg-surface-2" role="meter" aria-label={label} aria-valuenow={used} aria-valuemin={0} aria-valuemax={limit}>
        <div className={`h-1 rounded-full ${pct >= 80 ? "bg-inconclusive" : "bg-accent"}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function BudgetMeter({ run }: { run: RunDetail }) {
  const u = run.usage ?? {};
  return (
    <section aria-label="Budget" className="qc-panel flex flex-col gap-2.5 p-3">
      <h2 className="qc-eyebrow">Budget</h2>
      <Row label="LLM calls" used={u.llmCalls ?? 0} limit={run.budget.llmCalls} />
      <Row label="Tokens" used={(u.inputTokens ?? 0) + (u.outputTokens ?? 0)} limit={run.budget.totalTokens} />
      <Row label="Tool calls" used={u.toolCalls ?? 0} limit={run.budget.toolCalls} />
      <p className="border-t border-border pt-2 font-mono text-[11px] text-muted">
        {run.llmModel ? `${run.llmModel} via ${run.llmProvider}` : "model not assigned yet"}
      </p>
    </section>
  );
}
