"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { AuditSummary } from "@/components/report/ReportView";
import { PlanDiffView } from "@/components/plan/PlanDiffView";
import { getExperiment, optimizationKeys } from "@/lib/api/optimization";
import { getVerifications, reportKeys } from "@/lib/api/reports";
import type { CandidateAudit } from "@/lib/report/types";
import type { ExperimentDetail, ExperimentSummary, OptimizationCandidate, SpeedupStats } from "@/lib/api/types";
import { formatMs } from "@/lib/format";
import { VerdictBadge } from "./VerdictBadge";

const ms = (ns: number | null | undefined) => (ns === null || ns === undefined ? "—" : formatMs(ns / 1e6));
const x = (v: number) => `${v >= 10 ? v.toFixed(1) : v.toFixed(2)}×`;
const bytes = (b: number) => (b >= 1024 * 1024 ? `${(b / 1024 / 1024).toFixed(1)} MB` : `${(b / 1024).toFixed(0)} kB`);

/** Speedup CI on a log scale from 0.1× to 100×, with the 1× line: where the interval sits
 * relative to "no change" is the whole verdict story (BENCHMARK_ENGINE §7). */
export function SpeedupBar({ low, high, point }: { low: number; high: number; point: number }) {
  const pos = (v: number) => `${((Math.log10(Math.min(Math.max(v, 0.1), 100)) + 1) / 3) * 100}%`;
  return (
    <div className="relative h-3 w-full min-w-24 rounded bg-surface-2" role="img" aria-label={`speedup ${x(point)}, 95% CI ${x(low)} to ${x(high)}`}>
      <div className="absolute inset-y-0 w-px bg-border-strong" style={{ left: pos(1) }} />
      <div className="absolute inset-y-0.5 rounded bg-accent/60" style={{ left: pos(low), width: `calc(${pos(high)} - ${pos(low)})` }} />
      <div className="absolute inset-y-0 w-0.5 bg-ink" style={{ left: pos(point) }} />
    </div>
  );
}

function Comparison({ stats }: { stats: SpeedupStats[] }) {
  return (
    <table className="w-full text-left text-sm">
      <caption className="sr-only">Baseline versus candidate per parameter set</caption>
      <thead className="font-mono text-[11px] uppercase text-muted">
        <tr>
          <th className="py-1 pr-2">Param set</th>
          <th className="py-1 pr-2">Baseline median · p95</th>
          <th className="py-1 pr-2">Candidate median · p95</th>
          <th className="py-1 pr-2">n</th>
          <th className="py-1 pr-2">Speedup (95% CI)</th>
          <th className="w-40 py-1" />
        </tr>
      </thead>
      <tbody>
        {stats.map((s) => (
          <tr key={s.paramSet} className="border-t border-border">
            <td className="py-1 pr-2 font-mono text-xs">{s.paramSet}</td>
            <td className="py-1 pr-2">
              {ms(s.baseline.medianNs)} · {s.baseline.p95Ns === null ? "n/a (n<20)" : ms(s.baseline.p95Ns)}
            </td>
            <td className="py-1 pr-2">
              {ms(s.candidate.medianNs)} · {s.candidate.p95Ns === null ? "n/a (n<20)" : ms(s.candidate.p95Ns)}
            </td>
            <td className="py-1 pr-2 font-mono text-xs">
              {s.baseline.n}/{s.candidate.n}
            </td>
            <td className="py-1 pr-2">
              {x(s.speedup)} <span className="text-muted">({x(s.ciLow)}–{x(s.ciHigh)})</span>
            </td>
            <td className="py-1">
              <SpeedupBar low={s.ciLow} high={s.ciHigh} point={s.speedup} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

type Replication = NonNullable<ExperimentDetail["replication"]>;

/** ADR-0019: a noisy round re-measured in independent experiments. The warning is always in
 * words next to the range, which spans every replicate's CI (the conservative reading). */
function ReplicationNote({ replication }: { replication: Replication }) {
  return (
    <section aria-label="Independent replication" className="flex flex-col gap-1 rounded-md border border-dashed border-border-strong p-3 text-sm">
      <h3 className="font-semibold">Noisy samples · independent replication</h3>
      <ul className="flex flex-col gap-1">
        {replication.verdicts.map((v) => (
          <li key={v.arm} className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs">{v.arm}</span>
            <VerdictBadge status={v.verdict} />
            {v.ciLow !== null && v.ciHigh !== null ? (
              <span>
                {x(v.ciLow)} – {x(v.ciHigh)} across {v.experimentIds.length} independent experiments
              </span>
            ) : null}
            {v.reasons[0] ? <span className="text-xs text-muted">{v.reasons[0].detail}</span> : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Benchmark Auditor verdicts for one experiment (downgrade-only, ADR-0009). */
function AuditList({ runId, experimentId }: { runId: string; experimentId: string }) {
  const audits = useQuery({ queryKey: reportKeys.verifications(runId), queryFn: ({ signal }) => getVerifications(runId, signal) });
  const mine = (audits.data?.items ?? []).filter((v) => v.experimentId === experimentId);
  if (mine.length === 0) return <p className="text-xs text-muted">Benchmark Auditor: not reviewed yet.</p>;
  return (
    <section aria-label="Benchmark Auditor" className="flex flex-col gap-2">
      <h3 className="text-sm font-semibold">Benchmark Auditor</h3>
      {mine.map((v) => {
        const audit: CandidateAudit = {
          arm: v.candidateKey,
          engineVerdict: v.engineVerdict as CandidateAudit["engineVerdict"],
          verdict: v.verdict as CandidateAudit["verdict"],
          downgraded: v.auditorDowngraded,
          auditorStatus: v.auditorStatus as CandidateAudit["auditorStatus"],
          promptVersion: v.auditorPromptVersion,
          notes: v.auditorNotes,
          checks: v.checks as unknown as CandidateAudit["checks"],
          concerns: v.auditorConcerns as unknown as CandidateAudit["concerns"],
        };
        return <AuditSummary key={v.candidateKey} audit={audit} />;
      })}
    </section>
  );
}

/** Baseline vs candidate plan for one parameter set, from the post-timing EXPLAIN ANALYZE captures. */
function PlanCompare({ runId, detail, arm }: { runId: string; detail: ExperimentDetail; arm: string }) {
  const plans = detail.blocks.filter((b) => b.phase === "plan" && b.planSha256);
  const sets = [...new Set(plans.filter((b) => b.arm === arm).map((b) => b.paramSet))];
  const [ps, setPs] = useState<string | null>(null);
  const chosen = ps ?? sets[0] ?? null;
  const from = plans.find((b) => b.arm === "baseline" && b.paramSet === chosen)?.planSha256;
  const to = plans.find((b) => b.arm === arm && b.paramSet === chosen)?.planSha256;
  if (!chosen || !from || !to) return null;
  return (
    <section aria-label="Plan diff" className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold">Plan diff · baseline → {arm}</h3>
        {sets.map((s) => (
          <button key={s} type="button" aria-pressed={s === chosen} onClick={() => setPs(s)}
            className={`rounded-md px-2 py-0.5 font-mono text-xs ${s === chosen ? "bg-accent-tint" : "text-muted"}`}>
            {s}
          </button>
        ))}
      </div>
      <PlanDiffView runId={runId} from={from} to={to} />
    </section>
  );
}

export function ExperimentView({
  detail,
  candidates,
  runId,
}: {
  detail: ExperimentDetail;
  candidates: OptimizationCandidate[];
  runId?: string;
}) {
  const result = detail.result;
  const [selected, setSelected] = useState<string | null>(null);
  if (!result) {
    return (
      <p className="text-sm text-muted">
        Experiment {detail.status}
        {detail.errorCode ? ` · ${detail.errorCode}` : ""}. Results appear when measurement finishes.
      </p>
    );
  }
  const byKey = new Map(candidates.map((c) => [c.key, c]));
  const verdicts = new Map(result.verdicts.map((v) => [v.arm, v]));
  const builds = new Map(result.builds.map((b) => [b.arm, b]));
  const primary = (detail.config as { paramSets?: { name: string }[] } | null)?.paramSets?.[0]?.name;
  const active = selected ?? result.tournament[0]?.arm ?? null;
  const env = detail.environment as Record<string, unknown> | null;
  const replication = detail.replication ?? null;
  const replicated = new Map((replication?.verdicts ?? []).map((v) => [v.arm, v]));
  const winner = replication?.winner ?? result.winner;

  return (
    <div className="flex flex-col gap-4">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Optimization tournament</caption>
        <thead className="font-mono text-[11px] uppercase text-muted">
          <tr>
            <th className="py-1 pr-2">Rank</th>
            <th className="py-1 pr-2">Candidate</th>
            <th className="py-1 pr-2">Verdict</th>
            <th className="py-1 pr-2">Primary CI low</th>
            <th className="py-1">Index size</th>
          </tr>
        </thead>
        <tbody>
          {result.tournament.map((t) => {
            const c = byKey.get(t.arm);
            const v = verdicts.get(t.arm);
            const b = builds.get(t.arm);
            return (
              <tr
                key={t.arm}
                className={`cursor-pointer border-t border-border ${active === t.arm ? "bg-accent-tint" : ""}`}
                onClick={() => setSelected(t.arm)}
                aria-selected={active === t.arm}
              >
                <td className="py-1 pr-2 font-mono">{t.rank}</td>
                <td className="py-1 pr-2">
                  <span className="font-mono text-xs">{t.arm}</span>{" "}
                  <span className="break-words font-mono text-xs text-muted">{c ? (c.ddl.join("; ") || c.querySql) : ""}</span>
                  {winner === t.arm ? <span className="ml-1 text-xs font-medium text-verified">Winner</span> : null}
                </td>
                <td className="py-1 pr-2">
                  <VerdictBadge status={replicated.get(t.arm)?.verdict ?? t.verdict} />
                  {v?.reasons[0] ? (
                    <span className="ml-1 font-mono text-[11px] text-muted" title={v.reasons[0].detail}>
                      {v.reasons[0].code}
                    </span>
                  ) : null}
                </td>
                <td className="py-1 pr-2">{t.primaryCiLow === null ? "—" : x(t.primaryCiLow)}</td>
                <td className="py-1">{b && b.ok ? bytes(b.indexSizeBytes) : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {replication ? <ReplicationNote replication={replication} /> : null}
      {active ? (
        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold">
            Benchmark comparison · <span className="font-mono">{active}</span>
            {primary ? <span className="font-normal text-muted"> · primary param set {primary}</span> : null}
          </h3>
          {verdicts.get(active)?.reasons[0]?.detail ? (
            <p className="text-xs text-muted">{verdicts.get(active)?.reasons[0]?.detail}</p>
          ) : null}
          <Comparison stats={result.stats.filter((s) => s.arm === active)} />
          {runId ? <PlanCompare runId={runId} detail={detail} arm={active} /> : null}
        </div>
      ) : null}
      {runId ? <AuditList runId={runId} experimentId={detail.id} /> : null}
      <p className="text-xs text-muted">
        <span className="font-medium">Measured in the sandbox</span> ({detail.engineVersion}, {detail.rowProfile}
        {env ? `, PostgreSQL ${String(env.pgVersion ?? "?")}, ${String(env.cpuArch ?? "?")}` : ""}
        {detail.environmentDigest ? `, environment ${detail.environmentDigest.slice(0, 12)}` : ""}). Warm cache, single session,
        synthetic demo data: a verified result holds within this tested scope, not as a production guarantee.
      </p>
    </div>
  );
}

export function TournamentPanel({
  experiments,
  candidates,
  runId,
}: {
  experiments: ExperimentSummary[];
  candidates: OptimizationCandidate[];
  runId?: string;
}) {
  // Replicates (ADR-0019) belong to their round's approved experiment, which shows them.
  const rounds = experiments.filter((e) => e.replicate === 0);
  const latest = rounds.at(-1) ?? null;
  const [chosen, setChosen] = useState<string | null>(null);
  const id = chosen ?? latest?.id ?? null;
  const detail = useQuery({
    queryKey: optimizationKeys.experiment(id ?? ""),
    queryFn: ({ signal }) => getExperiment(id ?? "", signal),
    enabled: id !== null,
  });

  if (candidates.length === 0) {
    return <p className="qc-panel p-6 text-muted">No optimization candidates for this run.</p>;
  }
  return (
    <div className="flex flex-col gap-4">
      {rounds.length > 1 ? (
        <div role="tablist" aria-label="Rounds" className="flex gap-2">
          {rounds.map((e) => (
            <button
              key={e.id}
              role="tab"
              aria-selected={e.id === id}
              onClick={() => setChosen(e.id)}
              className={`rounded-md px-3 py-1 text-sm ${e.id === id ? "bg-accent-tint font-medium" : "text-muted"}`}
            >
              Round {e.round + 1}
            </button>
          ))}
        </div>
      ) : null}
      {detail.data ? (
        <ExperimentView detail={detail.data} candidates={candidates} runId={runId} />
      ) : (
        <ul className="flex flex-col gap-2">
          {candidates.map((c) => (
            <li key={c.key} className="flex flex-wrap items-center gap-2 text-sm">
              <VerdictBadge status={c.status} />
              <span className="font-mono text-xs">{c.key}</span>
              <span className="break-words font-mono text-xs text-muted">{c.ddl.join("; ") || c.querySql}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
