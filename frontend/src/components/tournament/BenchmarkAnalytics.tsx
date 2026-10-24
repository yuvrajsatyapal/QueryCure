"use client";

import { useMemo, useRef, useState } from "react";
import type { ExperimentDetail, OptimizationCandidate, Verification } from "@/lib/api/types";
import {
  BADGE_STATUS,
  BASELINE,
  armDistribution,
  armsOf,
  classifyRecommendation,
  measurementWarnings,
  paramSetsOf,
  speedupRow,
  thresholdsOf,
  type ArmDistribution,
  type ExperimentResult,
  type RecommendationKind,
} from "@/lib/benchmark/analysis";
import { candidateKindLabel, describeCandidate } from "@/lib/benchmark/candidate";
import { correctnessView, type CorrectnessStatus } from "@/lib/benchmark/correctness";
import type { AuditCheck, AuditConcern } from "@/lib/report/types";
import { formatNs, formatSpeedup } from "@/lib/format";
import { adaptiveLogTicks, dodgeLanes, fraction, logDomain, placeLabels, tickText, tukeyOutliers, type LogDomain } from "@/lib/benchmark/scale";
import { useWidth } from "@/lib/ui/hooks";
import { StudioSection, useCompactStudio } from "./StudioSection";
import { VerdictBadge } from "./VerdictBadge";

// Charts are HTML on the design tokens (DESIGN_SYSTEM §2 "Charts"): baseline in --muted, candidates
// in --accent, --link, --hypothesis, --inconclusive. Labels stay real text at every width.
const SERIES = ["bg-accent", "bg-link", "bg-hypothesis", "bg-inconclusive"];
const SERIES_BORDER = ["border-accent", "border-link", "border-hypothesis", "border-inconclusive"];
const SERIES_FILL = ["bg-accent/15", "bg-link/15", "bg-hypothesis/15", "bg-inconclusive/15"];
const seriesOf = (arms: string[], arm: string) => {
  if (arm === BASELINE) return { dot: "bg-muted", border: "border-muted", fill: "bg-muted/15" };
  const i = Math.max(0, arms.filter((a) => a !== BASELINE).indexOf(arm)) % SERIES.length;
  return { dot: SERIES[i]!, border: SERIES_BORDER[i]!, fill: SERIES_FILL[i]! };
};

const ORDER: RecommendationKind[] = ["verified", "verified_noise", "disputed", "inconclusive", "rejected", "unverified"];

// The narrowest axes, in decades: a near-1× cluster is shown on at least a 1.32× range (speedup)
// or a 1.26× range (latency), so a 2% difference never fills the chart.
const SPEEDUP_MIN_DECADES = 0.12;
const LATENCY_MIN_DECADES = 0.1;
// Sample dots: 6px, dodged onto at most five lanes 7px apart.
const DOT_PX = 7;
const LANES = 5;

function attribution(detail: ExperimentDetail) {
  return `experiment ${detail.id.slice(0, 8)} · round ${detail.round + 1}${detail.replicate ? ` · replicate ${detail.replicate}` : ""}`;
}

const DISCLOSURE = "w-fit cursor-pointer rounded-sm text-muted select-none outline-none hover:text-ink focus-visible:ring-2 focus-visible:ring-accent";
const pct = (d: LogDomain, v: number) => `${fraction(d, v) * 100}%`;
const ratio = (decades: number) => formatSpeedup(10 ** decades);

/** Axis labels that never overlap; the reference (1×) always wins a collision. */
function LogAxis({ domain, width, ticks, format, reference }: { domain: LogDomain; width: number | null; ticks: number[]; format: (v: number) => string; reference?: number }) {
  const w = width ?? 600;
  const labels = placeLabels(
    ticks.map((t) => ({ key: String(t), x: fraction(domain, t) * w, text: format(t), priority: t === reference })),
    w,
  );
  return (
    <div aria-hidden className="relative h-4 font-mono text-[10px] text-muted tabular-nums">
      {labels.map((l) => (
        <span
          key={l.key}
          className={`absolute whitespace-nowrap ${l.anchor === "middle" ? "-translate-x-1/2" : l.anchor === "end" ? "-translate-x-full" : ""} ${l.priority ? "font-semibold text-ink" : ""}`}
          style={{ left: `${(l.x / w) * 100}%` }}
        >
          {l.text}
        </span>
      ))}
    </div>
  );
}

function Gridlines({ ticks, domain }: { ticks: number[]; domain: LogDomain }) {
  return (
    <>
      {ticks.map((t) => (
        <span
          key={t}
          aria-hidden
          // Powers of ten a little stronger than the steps between them.
          className={`absolute inset-y-0 w-px ${Number.isInteger(Math.log10(t)) ? "bg-border-strong/60" : "bg-border/70"}`}
          style={{ left: pct(domain, t) }}
        />
      ))}
    </>
  );
}

/** A tooltip inside its strip at fraction `at`: shifted by the same fraction of its own width,
 * so it never leaves the strip (no page overflow on phones). */
function Tip({ at, children }: { at: number; children: React.ReactNode }) {
  const f = Math.min(1, Math.max(0, at));
  return (
    <span
      aria-hidden
      className="pointer-events-none absolute bottom-full z-20 mb-1.5 w-max max-w-64 rounded-md border border-border-strong bg-surface px-2 py-1 font-mono text-[11px] leading-4 text-ink shadow-md"
      style={{ left: `${f * 100}%`, transform: `translateX(${-f * 100}%)` }}
    >
      {children}
    </span>
  );
}

function Warnings({ result, config }: { result: ExperimentResult; config: unknown }) {
  const warnings = measurementWarnings(result, config);
  return (
    <section aria-label="Measurement warnings" className="flex min-w-0 flex-col gap-1.5 rounded-lg border border-border bg-surface p-4">
      <h3 className="qc-eyebrow">Measurement notes</h3>
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

interface DistRow {
  arm: string;
  d: ArmDistribution;
  /** Recording-order samples sorted by latency: what the arrow keys step through. */
  byLatency: number[];
  lanes: number[];
  outliers: boolean[];
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
  const plot = useRef<HTMLDivElement>(null);
  const width = useWidth(plot);
  const [cursor, setCursor] = useState<{ arm: string; i: number } | null>(null);
  const base = arms.map((arm) => ({ arm, d: armDistribution(result, arm, paramSet) })).filter((r): r is { arm: string; d: ArmDistribution } => r.d !== null);
  const floorNs = result.transportFloor?.medianNs ?? null;
  const domain = logDomain([...base.flatMap((r) => [r.d.minNs / 1e6, r.d.maxNs / 1e6]), ...(floorNs ? [floorNs / 1e6] : [])], { minDecades: LATENCY_MIN_DECADES });
  if (base.length === 0 || !domain) return <p className="text-sm text-muted">No recorded samples for param set {paramSet}.</p>;
  const w = width ?? 600;
  const at = (ns: number) => fraction(domain, ns / 1e6);
  const rows: DistRow[] = base.map(({ arm, d }) => ({
    arm,
    d,
    byLatency: d.samplesNs.map((_, i) => i).sort((a, b) => d.samplesNs[a]! - d.samplesNs[b]! || a - b),
    lanes: dodgeLanes(d.samplesNs.map(at), DOT_PX / w, LANES),
    outliers: tukeyOutliers(d.samplesNs, d.q1Ns, d.q3Ns),
  }));
  const ticks = adaptiveLogTicks(domain, w, { minGapPx: 52 });
  const outlierCount = (r: DistRow) => r.outliers.filter(Boolean).length;
  const label = `Latency distribution · ${attribution(detail)} · param set ${paramSet}: ${rows
    .map((r) => `${r.arm} median ${formatNs(r.d.medianNs)}, n ${r.d.n}${outlierCount(r) ? `, ${outlierCount(r)} outlier${outlierCount(r) === 1 ? "" : "s"}` : ""}`)
    .join("; ")}`;
  const sampleText = (r: DistRow, i: number) => {
    const ns = r.d.samplesNs[i]!;
    return `${r.arm} · sample ${i + 1} of ${r.d.samplesNs.length} (recording order) · ${formatNs(ns)}${r.outliers[i] ? " · outlier (beyond 1.5×IQR)" : ""}`;
  };
  const rowGrid = "grid grid-cols-1 gap-1 @lg/studio:grid-cols-[8.5rem_minmax(0,1fr)] @lg/studio:items-center @lg/studio:gap-3";
  // Narrow: the name, then the figures as one unbreakable unit (it moves to the next line whole, never
  // splitting at a separator). Beside the strip: stacked.
  const armLabel = (r: DistRow) => (
    <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 font-mono text-[11px] @lg/studio:block">
      <span className="max-w-full truncate font-medium text-ink @lg/studio:block">{r.arm}</span>
      <span className="whitespace-nowrap text-muted @lg/studio:whitespace-normal">
        <span className="@lg/studio:block">median {formatNs(r.d.medianNs)}</span>
        <span className="@lg/studio:hidden"> · </span>
        <span className="@lg/studio:block">
        {[
          `n ${r.d.n}`,
          r.d.failures.length ? `${r.d.failures.length} failed` : "",
          outlierCount(r) ? `${outlierCount(r)} outlier${outlierCount(r) === 1 ? "" : "s"}` : "",
        ]
          .filter(Boolean)
          .join(" · ")}
        </span>
      </span>
    </div>
  );
  const floorLabel = floorNs ? placeLabels([{ key: "floor", x: at(floorNs) * w, text: "transport floor" }], w)[0] : undefined;
  return (
    <div className="flex flex-col gap-1">
      <div className="relative">
        <div role="img" aria-label={label} className="flex flex-col gap-2">
          {floorLabel ? (
            <div aria-hidden className={rowGrid}>
              <span className="hidden @lg/studio:block" />
              <div className="relative h-3.5 font-mono text-[10px] text-hypothesis">
                <span
                  className={`absolute whitespace-nowrap ${floorLabel.anchor === "middle" ? "-translate-x-1/2" : floorLabel.anchor === "end" ? "-translate-x-full" : ""}`}
                  style={{ left: `${at(floorNs!) * 100}%` }}
                >
                  transport floor
                </span>
              </div>
            </div>
          ) : null}
          {rows.map((r) => {
            const s = seriesOf(arms, r.arm);
            const { d } = r;
            return (
              <div key={r.arm} className={rowGrid}>
                <div aria-hidden>{armLabel(r)}</div>
                <div aria-hidden className="relative h-11 rounded bg-surface-2">
                  <Gridlines ticks={ticks} domain={domain} />
                  {floorNs ? <span className="absolute inset-y-0 border-l-[1.5px] border-dashed border-hypothesis/80" style={{ left: `${at(floorNs) * 100}%` }} /> : null}
                  <span className="absolute top-1/2 h-px bg-border-strong" style={{ left: `${at(d.minNs) * 100}%`, width: `${(at(d.maxNs) - at(d.minNs)) * 100}%` }} />
                  <span
                    className={`absolute inset-y-2 rounded-sm border ${s.border} ${s.fill}`}
                    style={{ left: `${at(d.q1Ns) * 100}%`, width: `max(2px, ${(at(d.q3Ns) - at(d.q1Ns)) * 100}%)` }}
                  />
                  {d.samplesNs.map((ns, i) => {
                    const on = cursor?.arm === r.arm && cursor.i === i;
                    return (
                      <span
                        key={i}
                        className={`absolute -translate-x-1/2 -translate-y-1/2 rounded-full ${
                          r.outliers[i] ? `size-2 border-2 ${s.border} bg-surface-2` : `size-1.5 opacity-75 ${s.dot}`
                        } ${on ? "z-10 ring-2 ring-ink" : ""}`}
                        style={{ left: `${at(ns) * 100}%`, top: `calc(50% + ${r.lanes[i]! * DOT_PX}px)` }}
                      />
                    );
                  })}
                  {/* Median above the dots, with a halo so it reads on any fill. */}
                  <span
                    className="absolute inset-y-1 w-[3px] -translate-x-1/2 rounded-full bg-ink shadow-[0_0_0_1.5px_var(--surface-2)]"
                    style={{ left: `${at(d.medianNs) * 100}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
        {/* Keyboard and pointer inspection of single samples, outside the image so it stays one
            named picture; the strips line up with the drawn ones (same grid, invisible labels). */}
        <div className="absolute inset-0 flex flex-col gap-2">
          {floorLabel ? <div aria-hidden className="h-3.5 shrink-0" /> : null}
          {rows.map((r) => {
            const active = cursor?.arm === r.arm ? cursor.i : null;
            const pos = active === null ? -1 : r.byLatency.indexOf(active);
            const move = (k: number) => setCursor({ arm: r.arm, i: r.byLatency[Math.min(r.byLatency.length - 1, Math.max(0, k))]! });
            return (
              <div key={r.arm} className={rowGrid}>
                <div aria-hidden className="invisible">
                  {armLabel(r)}
                </div>
                <div
                  ref={r === rows[0] ? plot : undefined}
                  role="slider"
                  tabIndex={0}
                  aria-label={`${r.arm} samples, ${paramSet}`}
                  aria-valuemin={1}
                  aria-valuemax={r.byLatency.length}
                  aria-valuenow={pos + 1 || 1}
                  aria-valuetext={active === null ? `${r.byLatency.length} samples; arrow keys step through them from fastest to slowest` : sampleText(r, active)}
                  onKeyDown={(e) => {
                    const step: Record<string, number> = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1, PageUp: 5, PageDown: -5 };
                    if (e.key === "Escape") setCursor(null);
                    else if (e.key === "Home") move(0);
                    else if (e.key === "End") move(r.byLatency.length - 1);
                    else if (e.key in step) move(pos < 0 ? 0 : pos + step[e.key]!);
                    else return;
                    e.preventDefault();
                  }}
                  onFocus={() => (active === null ? move(0) : undefined)}
                  onBlur={() => setCursor(null)}
                  onMouseLeave={() => setCursor(null)}
                  onMouseMove={(e) => {
                    const box = e.currentTarget.getBoundingClientRect();
                    const f = (e.clientX - box.left) / box.width;
                    let best = 0;
                    r.d.samplesNs.forEach((ns, i) => {
                      if (Math.abs(at(ns) - f) < Math.abs(at(r.d.samplesNs[best]!) - f)) best = i;
                    });
                    setCursor({ arm: r.arm, i: best });
                  }}
                  className="relative h-11 rounded outline-none focus-visible:ring-2 focus-visible:ring-accent"
                >
                  {active !== null ? <Tip at={at(r.d.samplesNs[active]!)}>{sampleText(r, active)}</Tip> : null}
                </div>
              </div>
            );
          })}
        </div>
      </div>
      <div className="grid grid-cols-1 @lg/studio:grid-cols-[8.5rem_minmax(0,1fr)] @lg/studio:gap-3">
        <span className="hidden @lg/studio:block" />
        <LogAxis domain={domain} width={width} ticks={ticks} format={(v) => `${tickText(v)} ms`} />
      </div>
      <ul aria-label="Chart key" className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-muted">
        <li className="inline-flex items-center gap-1.5">
          <span aria-hidden className="inline-block h-3 w-[3px] rounded-full bg-ink" />
          median
        </li>
        <li className="inline-flex items-center gap-1.5">
          <span aria-hidden className="inline-block size-2 rounded-full border-2 border-muted" />
          outliers, kept
        </li>
        {floorNs ? (
          <li className="inline-flex items-center gap-1.5">
            <span aria-hidden className="inline-block h-3 border-l-[1.5px] border-dashed border-hypothesis" />
            transport floor {formatNs(floorNs)}
          </li>
        ) : null}
      </ul>
      <div className="flex flex-col gap-1">
        <details className="text-xs">
          <summary className={DISCLOSURE}>How to read this chart</summary>
          <p className="mt-1.5 max-w-prose text-[11px] leading-relaxed text-muted">
            Each dot is one recorded sample at its recorded latency, spread vertically only so dots do not overlap. Box: Q1–Q3, the middle half of the samples;
            bold line: median; thin line (whisker): min–max. Rings: outliers beyond 1.5×IQR from the box, kept and counted.
            {floorNs ? <> Dashed line: transport floor, the {formatNs(floorNs)} median SELECT 1 round trip; a sample near it is mostly round-trip time.</> : null} The
            axis is a log scale, so equal distances are equal ratios. Focus a row and use the arrow keys to read single samples (Home and End jump to the fastest and
            slowest).
          </p>
        </details>
        <SamplesTable paramSet={paramSet} rows={rows} />
      </div>
    </div>
  );
}

function SamplesTable({ paramSet, rows }: { paramSet: string; rows: { arm: string; d: ArmDistribution }[] }) {
  const n = Math.max(...rows.map((r) => r.d.samplesNs.length));
  return (
    <details className="text-xs">
      <summary className={DISCLOSURE}>
        {/* Counts in chart order; the arm names head the table's columns. */}
        Recorded samples · {paramSet} · n {rows.map((r) => r.d.n).join(" / ")}
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

/** Where an interval sits against 1×, in words (arithmetic on the recorded bounds, not a verdict). */
function sideOfOne(lo: number, hi: number): string {
  return lo > 1 ? "interval above 1×" : hi < 1 ? "interval below 1×" : "interval crosses 1×";
}

function SpeedupChart({
  detail,
  result,
  paramSets,
  arms,
  selected,
}: {
  detail: ExperimentDetail;
  result: ExperimentResult;
  paramSets: string[];
  arms: string[];
  selected: string | null;
}) {
  const plot = useRef<HTMLDivElement>(null);
  const width = useWidth(plot);
  const [tip, setTip] = useState<string | null>(null);
  const { minEffect, maxRegression } = thresholdsOf(detail.config);
  const candidates = arms.filter((a) => a !== BASELINE);
  const rows = candidates.flatMap((arm) => paramSets.map((ps) => ({ arm, ps, row: speedupRow(result, arm, ps) })));
  const replication = (detail.replication?.verdicts ?? []).filter((v) => v.ciLow !== null && v.ciHigh !== null && v.ciLow > 0 && v.ciHigh >= v.ciLow);
  const domain = logDomain(
    [
      1,
      ...(minEffect ? [minEffect] : []),
      ...(maxRegression ? [maxRegression] : []),
      ...rows.flatMap((r) => (r.row.status === "shown" ? [r.row.ciLow, r.row.ciHigh] : [])),
      ...replication.flatMap((v) => [v.ciLow ?? 1, v.ciHigh ?? 1]),
    ],
    { minDecades: SPEEDUP_MIN_DECADES },
  );
  if (rows.length === 0 || !domain) return null;
  const w = width ?? 600;
  const ticks = adaptiveLogTicks(domain, w, { must: [1] });
  const refs = (
    <>
      {/* 1×: solid ink with a halo, so it reads apart from the gridline under it and the dashed thresholds. */}
      <span aria-hidden className="absolute inset-y-0 w-0.5 -translate-x-1/2 bg-ink shadow-[0_0_0_1px_var(--surface-2)]" style={{ left: pct(domain, 1) }} />
      {minEffect ? <span aria-hidden className="absolute inset-y-0 border-l-[1.5px] border-dashed border-verified" style={{ left: pct(domain, minEffect) }} /> : null}
      {maxRegression ? <span aria-hidden className="absolute inset-y-0 border-l-[1.5px] border-dashed border-rejected" style={{ left: pct(domain, maxRegression) }} /> : null}
    </>
  );
  const heads = placeLabels(
    [
      { key: "one", x: fraction(domain, 1) * w, text: "1× no change", priority: true },
      ...(minEffect ? [{ key: "min", x: fraction(domain, minEffect) * w, text: `min ${formatSpeedup(minEffect)}` }] : []),
      ...(maxRegression ? [{ key: "reg", x: fraction(domain, maxRegression) * w, text: `max reg. ${formatSpeedup(maxRegression)}` }] : []),
    ],
    w,
  );
  const headTone: Record<string, string> = { one: "font-semibold text-ink", min: "text-verified", reg: "text-rejected" };
  const grid = "grid grid-cols-1 gap-1 @2xl/studio:grid-cols-[12rem_minmax(0,1fr)_9.5rem] @2xl/studio:items-center @2xl/studio:gap-3";
  // Narrow: a header line (candidate and param set left, ratio and n right) over the strip, rows ruled apart.
  // Wide: the header dissolves into the grid's name and value columns either side of the strip.
  const rowCls = `${grid} border-t border-border pt-2 first:border-t-0 first:pt-0 @2xl/studio:border-t-0 @2xl/studio:pt-0`;
  const head = "flex min-w-0 items-start justify-between gap-3 @2xl/studio:contents";
  const valueCls = "shrink-0 text-right font-mono text-[12px] tabular-nums @2xl/studio:order-3 @2xl/studio:text-left";
  const stripCls = "relative h-6 rounded bg-surface-2 @2xl/studio:order-2 @2xl/studio:h-7";
  return (
    <figure aria-label={`Speedup with 95% CI · ${attribution(detail)}`} className="flex flex-col gap-1.5">
      <figcaption className="flex flex-col gap-1">
        <span className="text-sm font-semibold">Speedup with 95% CI · {attribution(detail)}</span>
        <span className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted">
          <span className="inline-flex items-center gap-1">
            <span aria-hidden className="inline-block h-3 w-0.5 bg-ink" />
            1× no change
          </span>
          {minEffect ? (
            <span className="inline-flex items-center gap-1">
              <span aria-hidden className="inline-block h-3 border-l-[1.5px] border-dashed border-verified" />
              min effect {formatSpeedup(minEffect)}
            </span>
          ) : null}
          {maxRegression ? (
            <span className="inline-flex items-center gap-1">
              <span aria-hidden className="inline-block h-3 border-l-[1.5px] border-dashed border-rejected" />
              max regression {formatSpeedup(maxRegression)}
            </span>
          ) : null}
        </span>
        <span className="text-[11px] text-muted">
          Right of 1× is faster · median baseline / median candidate, percentile bootstrap · axis {formatSpeedup(domain.lo)}–{formatSpeedup(domain.hi)}, log scale
          {domain.widened ? `; widened to at least a ${ratio(SPEEDUP_MIN_DECADES)} range so small differences are not exaggerated` : ""}.
        </span>
      </figcaption>
      <div aria-hidden className={grid}>
        <span className="hidden @2xl/studio:block" />
        <div ref={plot} className="relative h-4 font-mono text-[10px]">
          {heads.map((h) => (
            <span
              key={h.key}
              className={`absolute whitespace-nowrap ${h.anchor === "middle" ? "-translate-x-1/2" : h.anchor === "end" ? "-translate-x-full" : ""} ${headTone[h.key]}`}
              style={{ left: `${(h.x / w) * 100}%` }}
            >
              {h.text}
            </span>
          ))}
        </div>
        <span className="hidden @2xl/studio:block" />
      </div>
      <ul className="flex flex-col gap-2">
        {rows.map(({ arm, ps, row }) => {
          const s = seriesOf(arms, arm);
          const key = `${arm}-${ps}`;
          const words =
            row.status === "shown"
              ? `${arm} on ${ps}: ratio ${formatSpeedup(row.speedup)} (95% CI ${formatSpeedup(row.ciLow)}–${formatSpeedup(row.ciHigh)}), ${sideOfOne(row.ciLow, row.ciHigh)}; n ${row.nBaseline} baseline / ${row.nCandidate} candidate samples`
              : "";
          return (
            <li key={key} className={rowCls}>
              <div data-row-head className={head}>
                <span className="min-w-0 font-mono text-[11px] @2xl/studio:order-1">
                  <span className={`block truncate ${arm === selected ? "font-semibold text-ink" : ""}`} title={arm}>
                    {arm}
                    {arm === selected ? <span className="font-sans font-normal text-muted"> · selected</span> : null}
                  </span>
                  <span className="block truncate text-muted">param set {ps}</span>
                </span>
                {row.status === "shown" ? (
                  <span className={valueCls}>
                    {formatSpeedup(row.speedup)} ({formatSpeedup(row.ciLow)}–{formatSpeedup(row.ciHigh)})
                    <span className="block text-[11px] text-muted">
                      n {row.nBaseline} / {row.nCandidate}
                    </span>
                  </span>
                ) : null}
              </div>
              {row.status === "shown" ? (
                <>
                  <span
                    role="img"
                    tabIndex={0}
                    aria-label={words}
                    onMouseEnter={() => setTip(key)}
                    onMouseLeave={() => setTip(null)}
                    onFocus={() => setTip(key)}
                    onBlur={() => setTip(null)}
                    onKeyDown={(e) => (e.key === "Escape" ? setTip(null) : undefined)}
                    className={`${stripCls} outline-none focus-visible:ring-2 focus-visible:ring-accent`}
                  >
                    <Gridlines ticks={ticks} domain={domain} />
                    {refs}
                    <span
                      className={`absolute top-1/2 h-2 -translate-y-1/2 rounded-full opacity-70 ${s.dot}`}
                      style={{ left: pct(domain, row.ciLow), width: `max(2px, calc(${pct(domain, row.ciHigh)} - ${pct(domain, row.ciLow)}))` }}
                    />
                    <span className={`absolute top-1/2 h-3.5 w-px -translate-y-1/2 ${s.dot}`} style={{ left: pct(domain, row.ciLow) }} />
                    <span className={`absolute top-1/2 h-3.5 w-px -translate-y-1/2 ${s.dot}`} style={{ left: pct(domain, row.ciHigh) }} />
                    <span className={`absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-surface ${s.dot}`} style={{ left: pct(domain, row.speedup) }} />
                    {tip === key ? (
                      <Tip at={fraction(domain, row.speedup)}>
                        {formatSpeedup(row.speedup)} · 95% CI {formatSpeedup(row.ciLow)}–{formatSpeedup(row.ciHigh)}
                        <span className="block text-muted">
                          {ps} · n {row.nBaseline}/{row.nCandidate} · {sideOfOne(row.ciLow, row.ciHigh)}
                        </span>
                      </Tip>
                    ) : null}
                  </span>
                </>
              ) : (
                <span className="text-xs text-muted @2xl/studio:order-2 @2xl/studio:col-span-2">{row.reason}</span>
              )}
            </li>
          );
        })}
        {replication.map((v) => (
          <li key={`rep-${v.arm}`} className={rowCls}>
            <div data-row-head className={head}>
              <span className="min-w-0 font-mono text-[11px] @2xl/studio:order-1">
                <span className="block truncate">{v.arm}</span>
                <span className="block text-muted">
                  {v.primaryParamSet} · range across {v.experimentIds.length} experiments
                </span>
              </span>
              <span className={valueCls}>
                {formatSpeedup(v.ciLow)}–{formatSpeedup(v.ciHigh)}
                <span className="block text-[11px] text-muted">range, not one CI</span>
              </span>
            </div>
            <span aria-hidden className={stripCls}>
              <Gridlines ticks={ticks} domain={domain} />
              {refs}
              <span
                className={`absolute top-1/2 h-2 -translate-y-1/2 rounded-full border border-dashed ${seriesOf(arms, v.arm).border}`}
                style={{ left: pct(domain, v.ciLow ?? 1), width: `max(2px, calc(${pct(domain, v.ciHigh ?? 1)} - ${pct(domain, v.ciLow ?? 1)}))` }}
              />
            </span>
          </li>
        ))}
      </ul>
      <div className={grid}>
        <span className="hidden @2xl/studio:block" />
        <LogAxis domain={domain} width={width} ticks={ticks} format={(v) => `${tickText(v)}×`} reference={1} />
        <span className="hidden @2xl/studio:block" />
      </div>
    </figure>
  );
}

const bytes = (b: number) => (b >= 1024 * 1024 ? `${(b / 1024 / 1024).toFixed(1)} MB` : `${Math.round(b / 1024)} kB`);

interface ArmView {
  candidate: OptimizationCandidate;
  rec: ReturnType<typeof classifyRecommendation>;
  audit: Verification | undefined;
}

function armViews(detail: ExperimentDetail, result: ExperimentResult, candidates: OptimizationCandidate[], audits: Verification[]): ArmView[] {
  const replicated = new Map((detail.replication?.verdicts ?? []).map((v) => [v.arm, v.verdict]));
  const rule = new Map(result.verdicts.map((v) => [v.arm, v.verdict]));
  const mine = new Map(audits.filter((a) => a.experimentId === detail.id).map((a) => [a.candidateKey, a]));
  const rank = new Map(result.tournament.map((t) => [t.arm, t.rank]));
  return [...candidates]
    .sort((a, b) => (rank.get(a.key) ?? 1e9) - (rank.get(b.key) ?? 1e9))
    .map((c) => ({
      candidate: c,
      audit: mine.get(c.key),
      rec: classifyRecommendation({ candidate: c, ruleVerdict: rule.get(c.key), audit: mine.get(c.key), replicationVerdict: replicated.get(c.key) }),
    }));
}

/** The arms rail (prototype "Bench Studio"): the baseline as the reference, then every candidate
 * with its backend verdict class and recorded primary interval. Selecting one drives the cards. */
function ArmsRail({
  detail,
  result,
  views,
  arms,
  primary,
  selected,
  onSelect,
}: {
  detail: ExperimentDetail;
  result: ExperimentResult;
  views: ArmView[];
  arms: string[];
  primary: string | null;
  selected: string | null;
  onSelect: (arm: string) => void;
}) {
  const counts = ORDER.map((k) => [k, views.filter((v) => v.rec.kind === k).length] as const).filter(([, n]) => n > 0);
  const winner = detail.replication?.winner ?? result.winner;
  return (
    <section aria-label="Recommendation verdicts" className="flex min-w-0 flex-col gap-2">
      <h3 className="qc-eyebrow">
        Round {detail.round + 1} · {views.length + 1} arms
      </h3>
      <p className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
        {counts.map(([k, n]) => (
          <span key={k}>
            {n} {k === "verified_noise" ? "verified with noise warning" : k}
          </span>
        ))}
      </p>
      <ul className="flex flex-col gap-2">
        <li className="flex flex-col gap-0.5 rounded-lg border border-border px-3 py-2">
          <span className="flex items-center gap-2 text-sm font-medium">
            <span aria-hidden="true" className="size-2.5 rounded-full bg-muted" />
            Baseline
          </span>
          <span className="font-mono text-[11px] text-muted">original query · reference for every speedup</span>
        </li>
        {views.map(({ candidate: c, rec }) => {
          const row = primary ? speedupRow(result, c.key, primary) : null;
          const on = c.key === selected;
          return (
            <li key={c.key}>
              <button
                type="button"
                aria-pressed={on}
                aria-label={`${describeCandidate(c)}, ${c.key}: ${rec.label}${row?.status === "shown" ? `, ${formatSpeedup(row.speedup)} on ${primary}` : ""}${winner === c.key ? ", winner" : ""}`}
                onClick={() => onSelect(c.key)}
                className={`flex w-full min-w-0 flex-col gap-1 rounded-lg border px-3 py-2 text-left ${on ? "border-accent bg-surface-2 shadow-[0_0_0_1px_var(--accent)]" : "border-border hover:border-border-strong"}`}
              >
                <span className="flex min-w-0 items-center gap-2 text-sm font-medium">
                  <span aria-hidden="true" className={`size-2.5 shrink-0 rounded-full ${seriesOf(arms, c.key).dot}`} />
                  <span className="min-w-0 break-words">{describeCandidate(c)}</span>
                </span>
                <span className="font-mono text-[11px] text-muted">
                  {c.key}
                  {winner === c.key ? <span className="font-sans font-medium text-verified"> · Winner</span> : null}
                </span>
                <span className="line-clamp-2 font-mono text-[11px] break-all text-muted">{c.ddl.join("; ") || c.querySql}</span>
                <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <VerdictBadge status={BADGE_STATUS[rec.kind]} />
                  {row?.status === "shown" ? (
                    <span className="font-mono text-[11px] tabular-nums">
                      {formatSpeedup(row.speedup)} <span className="text-muted">({formatSpeedup(row.ciLow)}–{formatSpeedup(row.ciHigh)}) · {primary}</span>
                    </span>
                  ) : null}
                </span>
                {rec.detail ? <span className="text-xs text-muted">{rec.detail}</span> : null}
              </button>
            </li>
          );
        })}
      </ul>
      <p className="text-xs text-muted">
        {detail.engineVersion} · {paramSetsOf(result, detail.config).length} param sets · row profile {detail.rowProfile}
        {result.transportFloor ? ` · transport floor ${formatNs(result.transportFloor.medianNs)}` : ""}
      </p>
    </section>
  );
}

const TONE: Record<string, string> = {
  verified: "border-verified/45 text-verified",
  verified_noise: "border-verified/45 text-verified",
  disputed: "border-inconclusive/50 text-inconclusive",
  inconclusive: "border-inconclusive/50 text-inconclusive",
  rejected: "border-rejected/50 text-rejected",
  unverified: "border-border-strong text-muted",
};
const GLYPH: Record<string, string> = { verified: "✓", verified_noise: "✓", disputed: "!", inconclusive: "?", rejected: "✕", unverified: "–" };

/** The selected arm's verdict, its measured intervals, and what the agent predicted, kept apart. */
function VerdictCard({ view, result, paramSets }: { view: ArmView; result: ExperimentResult; paramSets: string[] }) {
  const c = view.candidate;
  const build = result.builds.find((b) => b.arm === c.key);
  const rows = paramSets.map((ps) => ({ ps, row: speedupRow(result, c.key, ps) }));
  const headline =
    view.rec.kind === "verified" || view.rec.kind === "verified_noise"
      ? `${describeCandidate(c)} verified within the tested scope`
      : `${describeCandidate(c)}: ${view.rec.label.toLowerCase()}`;
  const predictedSize = c.estimatedCost?.indexSizeEstimateBytes;
  const correctness = CORRECTNESS_GATE[correctnessView(result, c.key).outcome.status];
  return (
    <section aria-label={`Verdict · ${c.key}`} className={`flex min-w-0 flex-col gap-3 rounded-lg border bg-surface p-4 ${TONE[view.rec.kind]?.split(" ")[0] ?? "border-border"}`}>
      <div className="flex items-start gap-3">
        <span aria-hidden="true" className={`text-2xl leading-7 ${TONE[view.rec.kind]?.split(" ")[1] ?? "text-muted"}`}>
          {GLYPH[view.rec.kind]}
        </span>
        <div className="flex min-w-0 flex-col gap-0.5">
          <h3 className="text-base font-semibold">{headline}</h3>
          <span className="text-xs text-muted">
            {view.rec.label}
            {view.rec.detail ? ` · ${view.rec.detail}` : ""}
          </span>
        </div>
      </div>
      <div className="grid gap-3 @lg/studio:grid-cols-2">
        <div className="flex min-w-0 flex-col gap-1">
          <span className="qc-eyebrow">Measured</span>
          <ul className="flex flex-col gap-0.5 text-sm">
            {rows.map(({ ps, row }) => (
              <li key={ps} className="font-mono text-[12px] tabular-nums">
                {row.status === "shown" ? (
                  <>
                    {formatSpeedup(row.speedup)} <span className="text-muted">95% CI {formatSpeedup(row.ciLow)}–{formatSpeedup(row.ciHigh)} · {ps} · n {row.nBaseline}/{row.nCandidate}</span>
                  </>
                ) : (
                  <span className="font-sans text-xs text-muted">
                    {ps}: {row.reason}
                  </span>
                )}
              </li>
            ))}
            {build ? (
              <li className="text-xs text-muted">
                Index build {build.ok ? `${bytes(build.indexSizeBytes)} in ${formatNs(build.buildNs)}` : `failed${build.reason ? ` (${build.reason})` : ""}`}
              </li>
            ) : null}
          </ul>
          <p className="text-xs">
            <span aria-hidden="true" className={GATE[correctness.status]!.tone}>
              {GATE[correctness.status]!.icon}
            </span>{" "}
            <span className="sr-only">{GATE[correctness.status]!.word}: </span>
            Correctness: {correctness.text}
          </p>
          <p className="text-xs text-muted">
            Tested scope: {paramSets.length} param set{paramSets.length === 1 ? "" : "s"} ({paramSets.join(", ")}), never pooled
          </p>
        </div>
        <div className="flex min-w-0 flex-col gap-1 rounded-md border border-dashed border-border-strong p-2">
          <span className="qc-eyebrow">Predicted · not measured</span>
          <p className="text-xs">{c.expectedBenefit || "No expected benefit recorded."}</p>
          <p className="text-xs text-muted">
            {candidateKindLabel(c.kind)}
            {predictedSize ? ` · est. index size ${bytes(predictedSize)}` : ""}
            {c.estimatedCost?.writeOverhead ? ` · write overhead ${c.estimatedCost.writeOverhead}` : ""}
          </p>
        </div>
      </div>
    </section>
  );
}

const GATE: Record<string, { icon: string; tone: string; word: string }> = {
  pass: { icon: "✓", tone: "text-verified", word: "pass" },
  warn: { icon: "!", tone: "text-inconclusive", word: "warning" },
  fail: { icon: "✕", tone: "text-rejected", word: "fail" },
  skip: { icon: "–", tone: "text-muted", word: "skipped" },
};
const CORRECTNESS_GATE: Record<CorrectnessStatus, { status: keyof typeof GATE; text: string }> = {
  passed: { status: "pass", text: "Same rows as the baseline on every param set" },
  failed: { status: "fail", text: "Results differ from the baseline" },
  inconclusive: { status: "warn", text: "Correctness could not be decided" },
  not_reached: { status: "skip", text: "Correctness not checked: stopped at an earlier gate" },
  not_evaluated: { status: "skip", text: "Correctness not checked: no rule verdict recorded" },
};

function GateRow({ status, name, note }: { status: keyof typeof GATE; name: string; note?: string }) {
  const g = GATE[status]!;
  return (
    <li className="grid grid-cols-[1rem_minmax(0,1fr)] gap-x-2 text-sm">
      <span aria-hidden="true" className={g.tone}>
        {g.icon}
      </span>
      <span className="min-w-0">
        <span className="sr-only">{g.word}: </span>
        {name}
        {note ? <span className="block text-xs break-words text-muted">{note}</span> : null}
      </span>
    </li>
  );
}

/** One line for the collapsed gates section on phones; failures and warnings keep it open. */
function gatesSummary(arm: string, result: ExperimentResult, audit: Verification | undefined): { summary: string; attention: boolean } {
  const correctness = correctnessView(result, arm).outcome.status;
  const rule = result.verdicts.find((v) => v.arm === arm);
  const checks = (audit?.checks ?? []) as unknown as AuditCheck[];
  const count = (st: string) => checks.filter((c) => c.status === st).length;
  const parts = [
    `correctness ${correctness.replaceAll("_", " ")}`,
    rule ? `rule verdict ${rule.verdict}` : "no rule verdict",
    audit ? `auditor ${count("pass")} pass${count("warn") ? `, ${count("warn")} warning` : ""}${count("fail") ? `, ${count("fail")} fail` : ""}${audit.auditorDowngraded ? ", downgraded" : ""}` : "not audited yet",
  ];
  const concerns = ((audit?.auditorConcerns ?? []) as unknown as AuditConcern[]).length;
  return {
    summary: parts.join(" · ") + (concerns ? ` · ${concerns} concern${concerns === 1 ? "" : "s"}` : ""),
    attention: correctness !== "passed" || count("warn") + count("fail") > 0 || concerns > 0 || !!audit?.auditorDowngraded,
  };
}

/** Correctness gate, rule verdict and the Benchmark Auditor's checks for the selected arm. */
function Gates({ arm, result, audit }: { arm: string; result: ExperimentResult; audit: Verification | undefined }) {
  const correctness = correctnessView(result, arm).outcome;
  const cg = CORRECTNESS_GATE[correctness.status];
  const rule = result.verdicts.find((v) => v.arm === arm);
  const checks = (audit?.checks ?? []) as unknown as AuditCheck[];
  const concerns = (audit?.auditorConcerns ?? []) as unknown as AuditConcern[];
  const floor = result.transportFloor;
  return (
    <section aria-label={`Correctness and audit gates · ${arm}`} className="flex min-w-0 flex-col gap-2 rounded-lg border border-border bg-surface p-4">
      <h3 className="qc-eyebrow">Correctness and audit gates</h3>
      <ul className="flex flex-col gap-1.5">
        <GateRow status={cg.status} name={cg.text} note={correctness.code ? `${correctness.code}${correctness.detail ? ` · ${correctness.detail}` : ""}` : "result fingerprints"} />
        <GateRow
          status={!rule ? "skip" : rule.verdict === "verified" ? "pass" : rule.verdict === "rejected" ? "fail" : "warn"}
          name={rule ? `Rule verdict: ${rule.verdict}` : "No rule verdict recorded"}
          note={rule ? (rule.gate === null ? "every gate passed" : `stopped at gate ${rule.gate}${rule.reasons[0] ? ` · ${rule.reasons[0].code}` : ""}`) : undefined}
        />
        {floor?.transportDominated ? <GateRow status="warn" name="Transport floor dominates the fastest arm" note="note only: compresses speedups, does not change the verdict" /> : null}
      </ul>
      <h4 className="mt-1 text-xs font-semibold">Benchmark Auditor</h4>
      {audit ? (
        <>
          <p className="text-xs text-muted">
            Engine <span className="font-mono">{audit.engineVerdict}</span> → final <span className="font-mono">{audit.verdict}</span>
            {audit.auditorDowngraded ? " · downgraded" : " · not downgraded"} · {audit.auditorStatus === "deterministic_only" ? "deterministic checks only" : "review completed"}. It can only downgrade.
          </p>
          <ul aria-label="Auditor checks" className="grid gap-x-6 gap-y-1.5 @2xl/studio:grid-cols-2">
            {checks.map((c) => (
              <GateRow key={c.name} status={(c.status in GATE ? c.status : "skip") as keyof typeof GATE} name={c.name.replaceAll("_", " ")} note={c.detail} />
            ))}
          </ul>
          {concerns.length ? (
            <ul aria-label="Auditor concerns" className="flex flex-col gap-1 text-xs">
              {concerns.map((c, i) => (
                <li key={i}>
                  <span className="font-mono">{c.severity}</span> · {c.text}
                </li>
              ))}
            </ul>
          ) : null}
        </>
      ) : (
        <p className="text-xs text-muted">Not reviewed yet: no verification recorded for this candidate in this experiment.</p>
      )}
    </section>
  );
}

/** The benchmark comparison studio for one experiment (UI_UX §3.17, prototype "Bench Studio").
 * Every figure is the recorded one; verdicts are the backend's; predictions are labelled. */
export function BenchmarkAnalytics({
  detail,
  candidates,
  audits,
  selected: selectedProp,
  onSelect,
}: {
  detail: ExperimentDetail;
  candidates: OptimizationCandidate[];
  audits: Verification[];
  selected?: string | null;
  onSelect?: (arm: string) => void;
}) {
  const result = detail.result;
  const arms = useMemo(() => (result ? armsOf(result) : []), [result]);
  const paramSets = useMemo(() => (result ? paramSetsOf(result, detail.config) : []), [result, detail.config]);
  const [chosen, setChosen] = useState<string | null>(null);
  const [own, setOwn] = useState<string | null>(null);
  const compact = useCompactStudio();
  if (!result) return null;
  const views = armViews(detail, result, candidates, audits);
  const pick = selectedProp ?? own;
  const selected = views.find((v) => v.candidate.key === pick)?.candidate.key ?? views[0]?.candidate.key ?? null;
  const view = views.find((v) => v.candidate.key === selected);
  const active = chosen && paramSets.includes(chosen) ? chosen : (paramSets[0] ?? null);
  const hasSamples = result.measurements.some((m) => m.latenciesNs.length > 0);
  const select = (arm: string) => {
    setOwn(arm);
    onSelect?.(arm);
  };

  return (
    <div className="@container/bench min-w-0">
    <div className="grid min-w-0 gap-5 @4xl/bench:grid-cols-[15rem_minmax(0,1fr)]">
      <ArmsRail detail={detail} result={result} views={views} arms={arms} primary={paramSets[0] ?? null} selected={selected} onSelect={select} />
      <div className="@container/studio flex min-w-0 flex-col gap-4">
        <div className="grid min-w-0 gap-4 @3xl/studio:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
          {view ? <VerdictCard view={view} result={result} paramSets={paramSets} /> : null}
          <Warnings result={result} config={detail.config} />
        </div>
        <section className="min-w-0 rounded-lg border border-border bg-surface p-4">
          <SpeedupChart detail={detail} result={result} paramSets={paramSets} arms={arms} selected={selected} />
        </section>
        <div className="grid min-w-0 gap-4 @4xl/studio:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          <StudioSection
            compact={compact}
            title="Timing distributions"
            summary={`${arms.length} arms × ${paramSets.length} param set${paramSets.length === 1 ? "" : "s"} · every recorded sample, log scale`}
          >
          <section aria-label="Timing distributions" className="flex min-w-0 flex-col gap-2 rounded-lg border border-border bg-surface p-4">
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
                      className={`rounded px-2.5 py-1 font-mono text-xs pointer-coarse:py-2.5 ${ps === active ? "bg-surface font-medium text-ink shadow-sm" : "text-muted hover:text-ink"}`}
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
          </StudioSection>
          {selected ? (
            <StudioSection key={selected} compact={compact} title="Correctness and auditor checks" {...gatesSummary(selected, result, view?.audit)}>
              <Gates arm={selected} result={result} audit={view?.audit} />
            </StudioSection>
          ) : null}
        </div>
      </div>
    </div>
    </div>
  );
}
