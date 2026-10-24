"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { AuditSummary } from "@/components/report/ReportView";
import { PlanDiffView } from "@/components/plan/PlanDiffView";
import { getExperiment, optimizationKeys } from "@/lib/api/optimization";
import { getVerifications, reportKeys } from "@/lib/api/reports";
import type { CandidateAudit } from "@/lib/report/types";
import type { ExperimentDetail, ExperimentSummary, OptimizationCandidate, SpeedupStats, Verification } from "@/lib/api/types";
import { BADGE_STATUS, classifyRecommendation, speedupRow, type ExperimentResult } from "@/lib/benchmark/analysis";
import { formatNs as ms, formatSpeedup as x } from "@/lib/format";
import { describeCandidate } from "@/lib/benchmark/candidate";
import { BenchmarkAnalytics } from "./BenchmarkAnalytics";
import { CorrectnessPanel } from "./CorrectnessPanel";
import { StatsGlossary } from "./StatsGlossary";
import { StudioSection, useCompactStudio } from "./StudioSection";
import { VerdictBadge } from "./VerdictBadge";

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

const cv = (v: number | null) => (v === null ? "—" : v.toFixed(2));

function Comparison({ stats, result }: { stats: SpeedupStats[]; result: ExperimentResult }) {
  const failed = (arm: string, ps: string) => result.measurements.find((m) => m.arm === arm && m.paramSet === ps)?.failures.length ?? null;
  return (
    // A focusable region, so keyboard users can scroll it (axe scrollable-region-focusable).
    <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Benchmark statistics table">
      <table className="w-full min-w-[880px] text-left text-sm">
        <caption className="sr-only">Baseline versus candidate per parameter set</caption>
        <thead className="font-mono text-[11px] uppercase text-muted">
          <tr>
            <th className="py-1 pr-2">Param set</th>
            <th className="py-1 pr-2">Baseline median · p95</th>
            <th className="py-1 pr-2">Candidate median · p95</th>
            <th className="py-1 pr-2">n</th>
            <th className="py-1 pr-2">IQR</th>
            <th className="py-1 pr-2">Robust CV</th>
            <th className="py-1 pr-2">Min–max</th>
            <th className="py-1 pr-2">Failed</th>
            <th className="py-1 pr-2">Speedup (95% CI)</th>
            <th className="w-40 py-1" />
          </tr>
        </thead>
        <tbody>
          {stats.map((s) => {
            const row = speedupRow(result, s.arm, s.paramSet);
            return (
              <tr key={s.paramSet} className="border-t border-border align-top">
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
                <td className="py-1 pr-2 font-mono text-xs whitespace-nowrap">
                  {ms(s.baseline.iqrNs)} / {ms(s.candidate.iqrNs)}
                </td>
                <td className="py-1 pr-2 font-mono text-xs">
                  {cv(s.baseline.robustCv)} / {cv(s.candidate.robustCv)}
                </td>
                <td className="py-1 pr-2 font-mono text-xs whitespace-nowrap">
                  {ms(s.baseline.minNs)}–{ms(s.baseline.maxNs)}
                  <br />
                  {ms(s.candidate.minNs)}–{ms(s.candidate.maxNs)}
                </td>
                <td className="py-1 pr-2 font-mono text-xs">
                  {failed("baseline", s.paramSet) ?? "—"} / {failed(s.arm, s.paramSet) ?? "—"}
                </td>
                {row.status === "shown" ? (
                  <>
                    <td className="py-1 pr-2 whitespace-nowrap">
                      {x(row.speedup)} <span className="text-muted">({x(row.ciLow)}–{x(row.ciHigh)})</span>
                    </td>
                    <td className="py-1">
                      <SpeedupBar low={row.ciLow} high={row.ciHigh} point={row.speedup} />
                    </td>
                  </>
                ) : (
                  <td colSpan={2} className="py-1 text-xs text-muted">
                    {row.reason}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
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
function AuditList({ audits, experimentId }: { audits: Verification[]; experimentId: string }) {
  const mine = audits.filter((v) => v.experimentId === experimentId);
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
  focusArm = null,
}: {
  detail: ExperimentDetail;
  candidates: OptimizationCandidate[];
  runId?: string;
  /** Arm to select, e.g. from "Open in benchmark" on the evidence tab. */
  focusArm?: string | null;
}) {
  const result = detail.result;
  const [selected, setSelected] = useState<string | null>(focusArm);
  const [seenFocus, setSeenFocus] = useState(focusArm);
  if (focusArm !== seenFocus) {
    setSeenFocus(focusArm);
    if (focusArm) setSelected(focusArm);
  }
  const [tables, setTables] = useState(false);
  const compact = useCompactStudio();
  const verifications = useQuery({
    queryKey: reportKeys.verifications(runId ?? ""),
    queryFn: ({ signal }) => getVerifications(runId ?? "", signal),
    enabled: runId !== undefined,
  });
  const audits = verifications.data?.items ?? [];
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
  const ranked = result.tournament.map((t) => t.arm);
  const active = selected && (byKey.has(selected) || ranked.includes(selected)) ? selected : (ranked[0] ?? candidates[0]?.key ?? null);
  const activeCandidate = active ? byKey.get(active) : undefined;
  const env = detail.environment as Record<string, unknown> | null;
  const replication = detail.replication ?? null;
  const replicated = new Map((replication?.verdicts ?? []).map((v) => [v.arm, v]));
  const winner = replication?.winner ?? result.winner;
  const audited = new Map(audits.filter((a) => a.experimentId === detail.id).map((a) => [a.candidateKey, a]));
  const primary = (detail.config as { paramSets?: { name: string }[] } | null)?.paramSets?.[0]?.name;

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="flex min-w-0 flex-col">
          <h2 className="text-lg font-semibold">Candidate comparison</h2>
          <p className="text-xs text-muted">
            Experiment {detail.id.slice(0, 8)} · round {detail.round + 1}
            {detail.replicate ? ` · replicate ${detail.replicate}` : ""} · {detail.provenance === "prerecorded" ? "prerecorded, not measured now" : "measured in the sandbox"}
          </p>
        </div>
        <button type="button" aria-expanded={tables} aria-controls={`tables-${detail.id}`} onClick={() => setTables((v) => !v)} className="qc-btn-secondary qc-btn-sm ml-auto">
          {tables ? "Hide data tables" : "Show data tables"}
        </button>
      </header>
      {replication ? <ReplicationNote replication={replication} /> : null}
      <BenchmarkAnalytics detail={detail} candidates={candidates} audits={audits} selected={active} onSelect={setSelected} />
      {active && runId && detail.blocks.some((b) => b.phase === "plan" && b.planSha256 && b.arm === active) ? (
        <StudioSection key={active} compact={compact} title="Execution-plan differences" summary={`baseline → ${active} · EXPLAIN ANALYZE captured after timing`}>
          <PlanCompare runId={runId} detail={detail} arm={active} />
        </StudioSection>
      ) : null}
      {tables ? (
        <section id={`tables-${detail.id}`} aria-label="Data tables" className="flex min-w-0 flex-col gap-4 rounded-lg border border-border p-4">
          <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Tournament ranking table">
            <table className="w-full min-w-[420px] text-left text-sm">
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
                      className={`cursor-pointer border-t border-border ${active === t.arm ? "bg-surface-2 shadow-[inset_3px_0_0_var(--accent)]" : ""}`}
                      onClick={() => setSelected(t.arm)}
                      aria-selected={active === t.arm}
                    >
                      <td className="py-1 pr-2 font-mono">{t.rank}</td>
                      <td className="py-1 pr-2">
                        {c ? <span className="block font-medium">{describeCandidate(c)}</span> : null}
                        <span className="font-mono text-xs">{t.arm}</span>{" "}
                        <span className="break-words font-mono text-xs text-muted">{c ? c.ddl.join("; ") || c.querySql : ""}</span>
                        {winner === t.arm ? <span className="ml-1 text-xs font-medium text-verified">Winner</span> : null}
                      </td>
                      <td className="py-1 pr-2">
                        <VerdictBadge
                          status={
                            c
                              ? BADGE_STATUS[
                                  classifyRecommendation({ candidate: c, ruleVerdict: t.verdict, audit: audited.get(t.arm), replicationVerdict: replicated.get(t.arm)?.verdict })
                                    .kind
                                ]
                              : (replicated.get(t.arm)?.verdict ?? t.verdict)
                          }
                        />
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
          </div>
          {active ? (
            <div className="flex min-w-0 flex-col gap-2">
              <h3 className="text-sm font-semibold">
                Benchmark statistics · {activeCandidate ? `${describeCandidate(activeCandidate)} · ` : ""}
                <span className="font-mono">{active}</span>
                {primary ? <span className="font-normal text-muted"> · primary param set {primary}</span> : null}
              </h3>
              {verdicts.get(active)?.reasons[0]?.detail ? <p className="text-xs text-muted">{verdicts.get(active)?.reasons[0]?.detail}</p> : null}
              <Comparison stats={result.stats.filter((s) => s.arm === active)} result={result} />
              <CorrectnessPanel result={result} arm={active} />
            </div>
          ) : null}
          {runId ? <AuditList audits={audits} experimentId={detail.id} /> : null}
        </section>
      ) : null}
      <StatsGlossary />
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
  focusArm = null,
}: {
  experiments: ExperimentSummary[];
  candidates: OptimizationCandidate[];
  runId?: string;
  focusArm?: string | null;
}) {
  // Replicates (ADR-0019) are independent experiments of their round: each is shown on its
  // own, never pooled with the approved experiment (UI_UX §3.17).
  const rounds = experiments.filter((e) => e.replicate === 0);
  const latest = rounds.at(-1) ?? null;
  const [chosen, setChosen] = useState<string | null>(null);
  const [replicate, setReplicate] = useState<string | null>(null);
  const roundId = chosen ?? latest?.id ?? null;
  const round = rounds.find((e) => e.id === roundId) ?? null;
  const siblings = round ? experiments.filter((e) => e.round === round.round).sort((a, b) => a.replicate - b.replicate) : [];
  const id = replicate && siblings.some((e) => e.id === replicate) ? replicate : roundId;
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
              onClick={() => {
                setChosen(e.id);
                setReplicate(null);
              }}
              className={`rounded-md px-3 py-1 text-sm ${e.id === id ? "bg-accent-tint font-medium" : "text-muted"}`}
            >
              Round {e.round + 1}
            </button>
          ))}
        </div>
      ) : null}
      {siblings.length > 1 ? (
        <div role="tablist" aria-label="Experiments in this round" className="flex flex-wrap gap-2">
          {siblings.map((e) => (
            <button
              key={e.id}
              role="tab"
              aria-selected={e.id === id}
              onClick={() => setReplicate(e.id)}
              className={`rounded-md px-3 py-1 text-sm ${e.id === id ? "bg-accent-tint font-medium" : "text-muted"}`}
            >
              {e.replicate === 0 ? "Approved experiment" : `Replicate ${e.replicate}`}
              <span className="ml-1 font-mono text-[11px] text-muted">{e.id.slice(0, 8)}</span>
            </button>
          ))}
        </div>
      ) : null}
      {detail.data ? (
        <ExperimentView detail={detail.data} candidates={candidates} runId={runId} focusArm={focusArm} />
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
