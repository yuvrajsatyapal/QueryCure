import type { ExperimentDetail, OptimizationCandidate, Verification } from "@/lib/api/types";
import { formatNs } from "@/lib/format";

// Display logic for recorded benchmark results (UI_UX §3.17). Nothing here computes a
// statistic the engine uses: speedups, CIs and verdicts are read as recorded. Quartiles are
// recomputed only to draw a box, with the engine's own method (benchmark/stats.py).

export type ExperimentResult = NonNullable<ExperimentDetail["result"]>;
export const BASELINE = "baseline";

/** Python's `statistics.quantiles(data, n=4, method="inclusive")`, plus the median. */
export function quartiles(sorted: readonly number[]): [number, number, number] {
  const n = sorted.length;
  if (n === 0) return [Number.NaN, Number.NaN, Number.NaN];
  if (n === 1) return [sorted[0]!, sorted[0]!, sorted[0]!];
  const m = n - 1;
  const at = (i: number) => {
    const j = Math.floor((i * m) / 4);
    const delta = i * m - j * 4;
    return (sorted[j]! * (4 - delta) + sorted[j + 1]! * delta) / 4;
  };
  const mid = n % 2 === 1 ? sorted[(n - 1) / 2]! : (sorted[n / 2 - 1]! + sorted[n / 2]!) / 2;
  return [at(1), mid, at(3)];
}

export interface ArmDistribution {
  arm: string;
  paramSet: string;
  samplesNs: number[];
  n: number;
  q1Ns: number;
  medianNs: number;
  q3Ns: number;
  minNs: number;
  maxNs: number;
  failures: string[];
  consistent: boolean;
}

/** One arm under one param set in one experiment: never pooled with anything else. */
export function armDistribution(result: ExperimentResult, arm: string, paramSet: string): ArmDistribution | null {
  const m = result.measurements.find((x) => x.arm === arm && x.paramSet === paramSet);
  if (!m || m.latenciesNs.length === 0) return null;
  const sorted = [...m.latenciesNs].sort((a, b) => a - b);
  const [q1Ns, medianNs, q3Ns] = quartiles(sorted);
  return {
    arm,
    paramSet,
    samplesNs: m.latenciesNs,
    n: sorted.length,
    q1Ns,
    medianNs,
    q3Ns,
    minNs: sorted[0]!,
    maxNs: sorted[sorted.length - 1]!,
    failures: m.failures,
    consistent: m.consistent,
  };
}

const unique = <T,>(xs: T[]) => [...new Set(xs)];

export function armsOf(result: ExperimentResult): string[] {
  const seen = unique([...result.measurements.map((m) => m.arm), ...result.stats.map((s) => s.arm)]);
  const ordered = [...result.tournament.map((t) => t.arm), ...seen].filter((a) => a !== BASELINE);
  return [...(seen.includes(BASELINE) ? [BASELINE] : []), ...unique(ordered)];
}

export function paramSetsOf(result: ExperimentResult, config: unknown): string[] {
  const recorded = unique([...result.measurements.map((m) => m.paramSet), ...result.stats.map((s) => s.paramSet)]);
  const configured = ((config as { paramSets?: { name?: unknown }[] } | null)?.paramSets ?? [])
    .map((p) => p.name)
    .filter((n): n is string => typeof n === "string" && recorded.includes(n));
  return unique([...configured, ...recorded]);
}

const NOT_COMPARABLE: Record<string, string> = {
  result_mismatch: "results differ from the baseline",
  nondeterministic_order: "rows or their order are not deterministic",
  result_too_large: "the result was too large to fingerprint",
};

export type SpeedupRow =
  | { status: "shown"; speedup: number; ciLow: number; ciHigh: number; nBaseline: number; nCandidate: number }
  | { status: "absent"; reason: string };

/** The recorded speedup and CI, only when they are valid and the arms are comparable. */
export function speedupRow(result: ExperimentResult, arm: string, paramSet: string): SpeedupRow {
  const verdict = result.verdicts.find((v) => v.arm === arm);
  const blocking = verdict?.reasons.find((r) => r.code in NOT_COMPARABLE);
  if (blocking) return { status: "absent", reason: `Not comparable: ${NOT_COMPARABLE[blocking.code]} (${blocking.code}).` };
  const s = result.stats.find((x) => x.arm === arm && x.paramSet === paramSet);
  if (!s) return { status: "absent", reason: "No speedup statistic recorded for this candidate and param set." };
  const values = [s.speedup, s.ciLow, s.ciHigh];
  if (values.some((v) => !Number.isFinite(v) || v <= 0) || s.ciLow > s.speedup || s.speedup > s.ciHigh) {
    return { status: "absent", reason: "The recorded statistic is not usable (non-finite or inconsistent interval), so it is not drawn." };
  }
  return { status: "shown", speedup: s.speedup, ciLow: s.ciLow, ciHigh: s.ciHigh, nBaseline: s.baseline.n, nCandidate: s.candidate.n };
}

export type RecommendationKind = "verified" | "verified_noise" | "disputed" | "rejected" | "inconclusive" | "unverified";

export const RECOMMENDATION_LABEL: Record<RecommendationKind, string> = {
  verified: "Verified · tested scope",
  verified_noise: "Verified · noise warning",
  disputed: "Disputed · auditor downgrade",
  rejected: "Rejected",
  inconclusive: "Inconclusive",
  unverified: "Unverified · not measured",
};

/** VerdictBadge status for each class (the badge carries icon and words). */
export const BADGE_STATUS: Record<RecommendationKind, string> = {
  verified: "verified",
  verified_noise: "verified_with_noise_warning",
  disputed: "disputed",
  rejected: "rejected",
  inconclusive: "inconclusive",
  unverified: "unverified",
};

const MEASURED: Record<string, RecommendationKind> = {
  verified: "verified",
  verified_with_noise_warning: "verified_noise",
  rejected: "rejected",
  inconclusive: "inconclusive",
};

export interface Recommendation {
  kind: RecommendationKind;
  label: string;
  detail: string | null;
}

/** Backend verdicts only. "Disputed" is the Benchmark Auditor's downgrade (it may never
 * upgrade); the backend has no separate disputed verdict. */
export function classifyRecommendation(input: {
  candidate: OptimizationCandidate;
  ruleVerdict?: string | null;
  audit?: Verification | null;
  replicationVerdict?: string | null;
}): Recommendation {
  const make = (kind: RecommendationKind, detail: string | null = null) => ({ kind, label: RECOMMENDATION_LABEL[kind], detail });
  const { audit } = input;
  if (audit?.auditorDowngraded) {
    return make("disputed", `Engine verdict ${audit.engineVerdict}; Benchmark Auditor downgraded it to ${audit.verdict}.`);
  }
  for (const v of [input.replicationVerdict, audit?.verdict, input.ruleVerdict, input.candidate.status]) {
    if (v && v in MEASURED) return make(MEASURED[v]!);
  }
  return make("unverified", `Candidate ${input.candidate.status}: no measured verdict.`);
}

export interface Thresholds {
  minEffect: number | null;
  maxRegression: number | null;
  maxCv: number | null;
}

export function thresholdsOf(config: unknown): Thresholds {
  const c = (config ?? {}) as Record<string, unknown>;
  const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  return { minEffect: num(c.minEffect), maxRegression: num(c.maxRegression), maxCv: num(c.maxCv) };
}

export interface MeasurementWarning {
  code: string;
  tone: "warn" | "info";
  text: string;
}

const pct = (share: number) => `${Math.round(share * 100)}%`;
const plural = (k: number, word: string) => `${k} ${word}${k === 1 ? "" : "s"}`;

/** Only what the experiment recorded, in words. */
export function measurementWarnings(result: ExperimentResult, config: unknown): MeasurementWarning[] {
  const out: MeasurementWarning[] = [];
  const floor = result.transportFloor;
  if (!floor) {
    out.push({ code: "transport_unrecorded", tone: "info", text: "Transport floor not recorded for this experiment (results before ADR-0029)." });
  } else if (floor.transportDominated && floor.shareOfFastestArm !== null) {
    out.push({
      code: "transport_dominated",
      tone: "warn",
      text: `Transport floor ${formatNs(floor.medianNs)} is ${pct(floor.shareOfFastestArm)} of the fastest arm's median: much of each sample is network, relay and driver, which compresses speedups (ADR-0029).`,
    });
  } else {
    const share = floor.shareOfFastestArm === null ? "" : ` (${pct(floor.shareOfFastestArm)} of the fastest arm's median)`;
    out.push({ code: "transport_floor", tone: "info", text: `Transport floor ${formatNs(floor.medianNs)}${share}, measured outside every timed sample.` });
  }

  const { maxCv } = thresholdsOf(config);
  const seen = new Set<string>();
  for (const s of result.stats) {
    for (const [arm, summary] of [[BASELINE, s.baseline], [s.arm, s.candidate]] as const) {
      const key = `${arm}\u0000${s.paramSet}`;
      if (seen.has(key)) continue;
      seen.add(key);
      if (maxCv !== null && summary.robustCv !== null && summary.robustCv > maxCv) {
        out.push({ code: "robust_cv", tone: "warn", text: `${arm} · ${s.paramSet}: robust CV ${summary.robustCv.toFixed(2)} above max_cv ${maxCv}.` });
      }
      if (summary.p95Ns === null) {
        out.push({ code: "p95_unavailable", tone: "info", text: `${arm} · ${s.paramSet}: p95 not reported (n = ${summary.n}, below 20).` });
      }
    }
  }
  for (const m of result.measurements) {
    if (m.failures.length === 0) continue;
    out.push({
      code: "failed_samples",
      tone: "warn",
      text: `${m.arm} · ${m.paramSet}: ${plural(m.failures.length, "failed sample")} (${unique(m.failures).join(", ")}), not plotted.`,
    });
  }
  for (const screen of result.noiseScreens ?? []) {
    const failed = screen.checks.filter((c) => !c.passed).map((c) => c.name);
    out.push({
      code: "noise_screen",
      tone: "warn",
      text: `${screen.arm}: noisy samples; noise screen ${screen.eligible ? "eligible for independent replication" : `not eligible (failed: ${failed.join(", ") || "none"})`}.`,
    });
  }
  if (result.provenance === "prerecorded") {
    out.push({ code: "prerecorded", tone: "info", text: "Prerecorded measurement: not measured in this session." });
  }
  out.push({
    code: "host_contention_unrecorded",
    tone: "info",
    text: "Host contention is not recorded by the benchmark engine. A busy host widens intervals and can make a result inconclusive.",
  });
  return out;
}

/** 1-2-5 ticks inside [min, max], for a log axis. */
export function logTicks(min: number, max: number): number[] {
  if (!(min > 0) || !(max >= min)) return [];
  const out: number[] = [];
  for (let e = Math.floor(Math.log10(min)) - 1; e <= Math.ceil(Math.log10(max)) + 1; e++) {
    for (const k of [1, 2, 5]) {
      const v = Number((k * 10 ** e).toPrecision(6));
      if (v >= min * (1 - 1e-9) && v <= max * (1 + 1e-9)) out.push(v);
    }
  }
  return out;
}
