"use client";

import { useMemo, useState } from "react";
import type { ExperimentDetail, OptimizationCandidate, Verification } from "@/lib/api/types";
import {
  BADGE_STATUS,
  BASELINE,
  armDistribution,
  armsOf,
  classifyRecommendation,
  logTicks,
  measurementWarnings,
  paramSetsOf,
  speedupRow,
  thresholdsOf,
  type ArmDistribution,
  type ExperimentResult,
  type RecommendationKind,
} from "@/lib/benchmark/analysis";
import { describeCandidate } from "@/lib/benchmark/candidate";
import { formatNs, formatSpeedup } from "@/lib/format";
import { VerdictBadge } from "./VerdictBadge";

// Charts are HTML on the design tokens (DESIGN_SYSTEM §2 "Charts"): baseline in --muted, candidates
// in --accent, --link, --hypothesis, --inconclusive. Labels stay real text at every width.
const SERIES = ["bg-accent", "bg-link", "bg-hypothesis", "bg-inconclusive"];
const SERIES_BORDER = ["border-accent", "border-link", "border-hypothesis", "border-inconclusive"];
const seriesOf = (arms: string[], arm: string) => {
  if (arm === BASELINE) return { dot: "bg-muted", border: "border-muted" };
  const i = Math.max(0, arms.filter((a) => a !== BASELINE).indexOf(arm)) % SERIES.length;
  return { dot: SERIES[i]!, border: SERIES_BORDER[i]! };
};

const ORDER: RecommendationKind[] = ["verified", "verified_noise", "disputed", "inconclusive", "rejected", "unverified"];

function attribution(detail: ExperimentDetail) {
  return `experiment ${detail.id.slice(0, 8)} · round ${detail.round + 1}${detail.replicate ? ` · replicate ${detail.replicate}` : ""}`;
}

/** Log scale with 8% padding; every position is a CSS percentage. */
function logScale(values: number[]) {
  const finite = values.filter((v) => Number.isFinite(v) && v > 0);
  const lo0 = Math.min(...finite);
  const hi0 = Math.max(...finite);
  const span = Math.max(Math.log10(hi0) - Math.log10(lo0), 0.05);
  const lo = Math.log10(lo0) - span * 0.08;
  const hi = Math.log10(hi0) + span * 0.08;
  return {
    pos: (v: number) => `${((Math.log10(v) - lo) / (hi - lo)) * 100}%`,
    lo: 10 ** lo,
    hi: 10 ** hi,
  };
}

function Axis({ ticks, pos, format }: { ticks: number[]; pos: (v: number) => string; format: (v: number) => string }) {
  return (
    <div aria-hidden className="relative h-4 font-mono text-[10px] text-muted tabular-nums">
      {ticks.map((t) => (
        <span key={t} className="absolute -translate-x-1/2 whitespace-nowrap" style={{ left: pos(t) }}>
          {format(t)}
        </span>
      ))}
    </div>
  );
}

function Gridlines({ ticks, pos }: { ticks: number[]; pos: (v: number) => string }) {
  return (
    <>
      {ticks.map((t) => (
        <span key={t} aria-hidden className="absolute inset-y-0 w-px bg-border" style={{ left: pos(t) }} />
      ))}
    </>
  );
}

function VerdictSummary({
  detail,
  result,
  candidates,
  audits,
}: {
  detail: ExperimentDetail;
  result: ExperimentResult;
  candidates: OptimizationCandidate[];
  audits: Verification[];
}) {
  const replicated = new Map((detail.replication?.verdicts ?? []).map((v) => [v.arm, v.verdict]));
  const rule = new Map(result.verdicts.map((v) => [v.arm, v.verdict]));
  const mine = new Map(audits.filter((a) => a.experimentId === detail.id).map((a) => [a.candidateKey, a]));
  const rows = candidates.map((c) => ({
    candidate: c,
    rec: classifyRecommendation({ candidate: c, ruleVerdict: rule.get(c.key), audit: mine.get(c.key), replicationVerdict: replicated.get(c.key) }),
  }));
  const counts = ORDER.map((k) => [k, rows.filter((r) => r.rec.kind === k).length] as const).filter(([, n]) => n > 0);
  return (
    <section aria-label="Recommendation verdicts" className="flex flex-col gap-2">
      <h3 className="text-sm font-semibold">Recommendation verdicts</h3>
      <p className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
        {counts.map(([k, n]) => (
          <span key={k}>
            {n} {k === "verified_noise" ? "verified with noise warning" : k}
          </span>
        ))}
      </p>
      <ul className="flex flex-col gap-1.5">
        {rows.map(({ candidate: c, rec }) => (
          <li key={c.key} className="flex flex-wrap items-baseline gap-2 text-sm">
            <VerdictBadge status={BADGE_STATUS[rec.kind]} />
            <span className="font-medium">{describeCandidate(c)}</span>
            <span className="font-mono text-xs">{c.key}</span>
            <span className="min-w-0 break-words font-mono text-xs text-muted">{c.ddl.join("; ") || c.querySql}</span>
            {rec.detail ? <span className="w-full text-xs text-muted sm:w-auto">{rec.detail}</span> : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

function Warnings({ result, config }: { result: ExperimentResult; config: unknown }) {
  const warnings = measurementWarnings(result, config);
  return (
    <section aria-label="Measurement warnings" className="flex flex-col gap-1.5 rounded-md border border-border bg-surface-2 p-3">
      <h3 className="text-sm font-semibold">Measurement warnings</h3>
      <ul className="flex flex-col gap-1 text-xs">
        {warnings.map((w, i) => (
          <li key={`${w.code}-${i}`} className={`flex gap-2 ${w.tone === "warn" ? "text-inconclusive" : "text-muted"}`}>
            <span aria-hidden>{w.tone === "warn" ? "!" : "·"}</span>
            <span>
              <span className="sr-only">{w.tone === "warn" ? "Warning: " : "Note: "}</span>
              {w.text}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function DistributionChart({
  detail,
  result,
  paramSet,
  arms,
}: {
  detail: ExperimentDetail;
  result: ExperimentResult;
  paramSet: string;
  arms: string[];
}) {
  const rows = arms.map((arm) => ({ arm, d: armDistribution(result, arm, paramSet) })).filter((r): r is { arm: string; d: ArmDistribution } => r.d !== null);
  if (rows.length === 0) return <p className="text-sm text-muted">No recorded samples for param set {paramSet}.</p>;
  const floorNs = result.transportFloor?.medianNs ?? null;
  const scale = logScale([...rows.flatMap((r) => [r.d.minNs, r.d.maxNs]), ...(floorNs ? [floorNs] : [])]);
  const ticks = logTicks(scale.lo / 1e6, scale.hi / 1e6);
  const posNs = (ns: number) => scale.pos(ns);
  const posMs = (ms: number) => scale.pos(ms * 1e6);
  const label = `Latency distribution · ${attribution(detail)} · param set ${paramSet}: ${rows
    .map((r) => `${r.arm} median ${formatNs(r.d.medianNs)}, n ${r.d.n}`)
    .join("; ")}`;
  return (
    <div className="flex flex-col gap-1">
      <div role="img" aria-label={label} className="flex flex-col gap-2">
        {rows.map(({ arm, d }) => {
          const s = seriesOf(arms, arm);
          return (
            <div key={arm} className="grid grid-cols-1 gap-1 sm:grid-cols-[10rem_minmax(0,1fr)] sm:items-center sm:gap-3">
              <div aria-hidden className="min-w-0 font-mono text-[11px]">
                <span className="block truncate">{arm}</span>
                <span className="text-muted">
                  median {formatNs(d.medianNs)} · n {d.n}
                  {d.failures.length ? ` · ${d.failures.length} failed` : ""}
                </span>
              </div>
              <div aria-hidden className="relative h-8 rounded bg-surface-2">
                <Gridlines ticks={ticks} pos={posMs} />
                <span className="absolute top-1/2 h-px bg-border-strong" style={{ left: posNs(d.minNs), width: `calc(${posNs(d.maxNs)} - ${posNs(d.minNs)})` }} />
                <span
                  className={`absolute inset-y-1.5 rounded-sm border ${s.border} bg-bg/40`}
                  style={{ left: posNs(d.q1Ns), width: `max(2px, calc(${posNs(d.q3Ns)} - ${posNs(d.q1Ns)}))` }}
                />
                <span className="absolute inset-y-1 w-0.5 bg-ink" style={{ left: posNs(d.medianNs) }} />
                {d.samplesNs.map((ns, i) => (
                  <span
                    key={i}
                    className={`absolute size-1.5 -translate-x-1/2 rounded-full opacity-70 ${s.dot}`}
                    style={{ left: posNs(ns), top: `${18 + (i % 5) * 14}%` }}
                  />
                ))}
                {floorNs ? <span className="absolute inset-y-0 border-l border-dashed border-hypothesis" style={{ left: posNs(floorNs) }} /> : null}
              </div>
            </div>
          );
        })}
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-[10rem_minmax(0,1fr)] sm:gap-3">
        <span className="hidden sm:block" />
        <Axis ticks={ticks} pos={posMs} format={(v) => `${v} ms`} />
      </div>
      <p className="text-[11px] text-muted">
        Dots: every recorded sample (log scale). Box: Q1–Q3; dark line: median; thin line: min–max.
        {floorNs ? <> Dashed line: transport floor, {formatNs(floorNs)} median SELECT 1 round trip.</> : null}
      </p>
      <SamplesTable paramSet={paramSet} rows={rows} />
    </div>
  );
}

function SamplesTable({ paramSet, rows }: { paramSet: string; rows: { arm: string; d: ArmDistribution }[] }) {
  const n = Math.max(...rows.map((r) => r.d.samplesNs.length));
  return (
    <details className="text-xs">
      <summary className="cursor-pointer text-muted select-none hover:text-ink">
        Recorded samples · {paramSet} ({rows.map((r) => `${r.arm} ${r.d.n}`).join(", ")})
      </summary>
      <div className="mt-2 max-h-72 overflow-auto rounded-md border border-border" tabIndex={0} role="region" aria-label={`Recorded samples table, ${paramSet}`}>
        <table className="w-full text-left font-mono text-[12px] tabular-nums">
          <caption className="sr-only">Recorded samples, {paramSet}, in recording order (ms)</caption>
          <thead className="sticky top-0 bg-surface-2 text-muted">
            <tr>
              <th className="px-2 py-1">#</th>
              {rows.map((r) => (
                <th key={r.arm} className="px-2 py-1">
                  {r.arm}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: n }, (_, i) => (
              <tr key={i} className="border-t border-border">
                <td className="px-2 py-0.5 text-muted">{i + 1}</td>
                {rows.map((r) => (
                  <td key={r.arm} className="px-2 py-0.5">
                    {r.d.samplesNs[i] !== undefined ? formatNs(r.d.samplesNs[i]) : "—"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function SpeedupChart({ detail, result, paramSets, arms }: { detail: ExperimentDetail; result: ExperimentResult; paramSets: string[]; arms: string[] }) {
  const { minEffect, maxRegression } = thresholdsOf(detail.config);
  const candidates = arms.filter((a) => a !== BASELINE);
  const rows = candidates.flatMap((arm) => paramSets.map((ps) => ({ arm, ps, row: speedupRow(result, arm, ps) })));
  const replication = (detail.replication?.verdicts ?? []).filter((v) => v.ciLow !== null && v.ciHigh !== null && v.ciLow > 0 && v.ciHigh >= v.ciLow);
  if (rows.length === 0) return null;
  const values = [
    1,
    ...(minEffect ? [minEffect] : []),
    ...(maxRegression ? [maxRegression] : []),
    ...rows.flatMap((r) => (r.row.status === "shown" ? [r.row.ciLow, r.row.ciHigh] : [])),
    ...replication.flatMap((v) => [v.ciLow ?? 1, v.ciHigh ?? 1]),
  ];
  const scale = logScale(values);
  const ticks = logTicks(scale.lo, scale.hi);
  const refs = (
    <>
      <span aria-hidden className="absolute inset-y-0 w-0.5 bg-ink/70" style={{ left: scale.pos(1) }} />
      {minEffect ? <span aria-hidden className="absolute inset-y-0 border-l border-dashed border-verified" style={{ left: scale.pos(minEffect) }} /> : null}
      {maxRegression ? <span aria-hidden className="absolute inset-y-0 border-l border-dashed border-rejected" style={{ left: scale.pos(maxRegression) }} /> : null}
    </>
  );
  const grid = "grid grid-cols-1 gap-1 sm:grid-cols-[12rem_minmax(0,1fr)_9.5rem] sm:items-center sm:gap-3";
  return (
    <figure aria-label={`Speedup with 95% CI · ${attribution(detail)}`} className="flex flex-col gap-1.5">
      <figcaption className="flex flex-col gap-1">
        <span className="text-sm font-semibold">Speedup with 95% CI · {attribution(detail)}</span>
        <span className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted">
          <span className="inline-flex items-center gap-1">
            <span aria-hidden className="inline-block h-3 w-0.5 bg-ink/70" />
            1× no improvement
          </span>
          {minEffect ? (
            <span className="inline-flex items-center gap-1">
              <span aria-hidden className="inline-block h-3 border-l border-dashed border-verified" />
              min effect {formatSpeedup(minEffect)}
            </span>
          ) : null}
          {maxRegression ? (
            <span className="inline-flex items-center gap-1">
              <span aria-hidden className="inline-block h-3 border-l border-dashed border-rejected" />
              max regression {formatSpeedup(maxRegression)}
            </span>
          ) : null}
          <span>Right of 1× is faster. Log scale. Median baseline / median candidate, percentile bootstrap.</span>
        </span>
      </figcaption>
      <ul className="flex flex-col gap-2">
        {rows.map(({ arm, ps, row }) => {
          const s = seriesOf(arms, arm);
          return (
            <li key={`${arm}-${ps}`} className={grid}>
              <span className="min-w-0 font-mono text-[11px]">
                <span className="block truncate">{arm}</span>
                <span className="text-muted">param set {ps}</span>
              </span>
              {row.status === "shown" ? (
                <>
                  <span aria-hidden className="relative h-6 rounded bg-surface-2">
                    <Gridlines ticks={ticks} pos={scale.pos} />
                    {refs}
                    <span
                      className={`absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full opacity-60 ${s.dot}`}
                      style={{ left: scale.pos(row.ciLow), width: `max(2px, calc(${scale.pos(row.ciHigh)} - ${scale.pos(row.ciLow)}))` }}
                    />
                    <span className={`absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-bg ${s.dot}`} style={{ left: scale.pos(row.speedup) }} />
                  </span>
                  <span className="font-mono text-[12px] tabular-nums">
                    {formatSpeedup(row.speedup)} ({formatSpeedup(row.ciLow)}–{formatSpeedup(row.ciHigh)})
                    <span className="block text-[11px] text-muted">
                      n {row.nBaseline} / {row.nCandidate}
                    </span>
                  </span>
                </>
              ) : (
                <span className="text-xs text-muted sm:col-span-2">{row.reason}</span>
              )}
            </li>
          );
        })}
        {replication.map((v) => (
          <li key={`rep-${v.arm}`} className={grid}>
            <span className="min-w-0 font-mono text-[11px]">
              <span className="block truncate">{v.arm}</span>
              <span className="text-muted">
                {v.primaryParamSet} · range across {v.experimentIds.length} experiments
              </span>
            </span>
            <span aria-hidden className="relative h-6 rounded bg-surface-2">
              <Gridlines ticks={ticks} pos={scale.pos} />
              {refs}
              <span
                className={`absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full border border-dashed ${seriesOf(arms, v.arm).border}`}
                style={{ left: scale.pos(v.ciLow ?? 1), width: `max(2px, calc(${scale.pos(v.ciHigh ?? 1)} - ${scale.pos(v.ciLow ?? 1)}))` }}
              />
            </span>
            <span className="font-mono text-[12px] tabular-nums">
              {formatSpeedup(v.ciLow)}–{formatSpeedup(v.ciHigh)}
              <span className="block text-[11px] text-muted">range, not one CI</span>
            </span>
          </li>
        ))}
      </ul>
      <div className={grid}>
        <span className="hidden sm:block" />
        <Axis ticks={ticks} pos={scale.pos} format={(v) => `${v}×`} />
        <span className="hidden sm:block" />
      </div>
    </figure>
  );
}

/** Benchmark analytics for one experiment (UI_UX §3.17). Every figure is the recorded one. */
export function BenchmarkAnalytics({
  detail,
  candidates,
  audits,
}: {
  detail: ExperimentDetail;
  candidates: OptimizationCandidate[];
  audits: Verification[];
}) {
  const result = detail.result;
  const arms = useMemo(() => (result ? armsOf(result) : []), [result]);
  const paramSets = useMemo(() => (result ? paramSetsOf(result, detail.config) : []), [result, detail.config]);
  const [chosen, setChosen] = useState<string | null>(null);
  if (!result) return null;
  const active = chosen && paramSets.includes(chosen) ? chosen : (paramSets[0] ?? null);
  const hasSamples = result.measurements.some((m) => m.latenciesNs.length > 0);

  return (
    <div className="flex min-w-0 flex-col gap-5">
      <VerdictSummary detail={detail} result={result} candidates={candidates} audits={audits} />
      <Warnings result={result} config={detail.config} />
      <section aria-label="Timing distributions" className="flex min-w-0 flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">Timing distributions · {attribution(detail)}</h3>
          {paramSets.length > 1 ? (
            <div role="tablist" aria-label="Param set" className="flex flex-wrap gap-0.5 rounded-md border border-border bg-surface-2 p-0.5">
              {paramSets.map((ps) => (
                <button
                  key={ps}
                  role="tab"
                  aria-selected={ps === active}
                  onClick={() => setChosen(ps)}
                  className={`rounded px-2.5 py-1 font-mono text-xs ${ps === active ? "bg-surface font-medium text-ink shadow-sm" : "text-muted hover:text-ink"}`}
                >
                  {ps}
                </button>
              ))}
            </div>
          ) : null}
        </div>
        {!hasSamples || !active ? (
          <p className="text-sm text-muted">No recorded samples for this experiment.</p>
        ) : (
          <DistributionChart detail={detail} result={result} paramSet={active} arms={arms} />
        )}
      </section>
      <SpeedupChart detail={detail} result={result} paramSets={paramSets} arms={arms} />
    </div>
  );
}
