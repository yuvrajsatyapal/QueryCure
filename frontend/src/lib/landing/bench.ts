/* The landing page's illustrative benchmark: synthetic samples from a seeded PRNG, deterministic on every
 * render and never presented as recorded. The hero's X-Ray result and the benchmark section both read it,
 * so the page shows one set of numbers. It is a separate example, not a measurement of the X-Ray plan
 * (docs/design/prototypes/landing/README.md). */

export type IllustrativeBench = {
  n: number;
  baseline: number[];
  candidate: number[];
  baselineMedian: number;
  candidateMedian: number;
  ratio: number;
  ciLow: number;
  ciHigh: number;
  baselineCv: number;
  candidateCv: number;
  /** Fastest possible round trip on the illustrated host, ms. */
  transportFloorMs: number;
};

export function mulberry32(seed: number): () => number {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function lognormal(rng: () => number, med: number, sigma: number): number {
  const u = 1 - rng();
  const v = rng();
  return med * Math.exp(sigma * Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v));
}

// Indices below are always in range; NaN would surface a broken caller in the tests instead of hiding it.
const at = (xs: readonly number[], i: number): number => xs[i] ?? Number.NaN;

export function median(xs: readonly number[]): number {
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? at(s, m) : (at(s, m - 1) + at(s, m)) / 2;
}

export function quantile(xs: readonly number[], q: number): number {
  const s = [...xs].sort((a, b) => a - b);
  const p = (s.length - 1) * q;
  const lo = Math.floor(p);
  return at(s, lo) + (at(s, Math.ceil(p)) - at(s, lo)) * (p - lo);
}

export function coefficientOfVariation(xs: readonly number[]): number {
  const mean = xs.reduce((a, b) => a + b, 0) / xs.length;
  return Math.sqrt(xs.reduce((s, x) => s + (x - mean) ** 2, 0) / (xs.length - 1)) / mean;
}

/** Position of `v` on a log-scale axis spanning `domain`, as a percentage. */
export function logPosition(v: number, [a, b]: readonly [number, number]): number {
  return ((Math.log10(v) - Math.log10(a)) / (Math.log10(b) - Math.log10(a))) * 100;
}

/** A CSS percentage rounded to 2 decimals, so server and browser serialize chart positions identically. */
export const pct = (v: number): string => `${v.toFixed(2)}%`;

const BOOTSTRAP_RESAMPLES = 2000;

export function makeIllustrativeBench(): IllustrativeBench {
  const rng = mulberry32(42);
  const n = 40;
  const baseline = Array.from({ length: n }, (_, k) => lognormal(rng, 11.8, 0.17) * (k % 13 === 0 ? 1.6 : 1));
  const candidate = Array.from({ length: n }, (_, k) => lognormal(rng, 4.05, 0.21) * (k % 17 === 0 ? 1.5 : 1));
  // Percentile bootstrap of the median ratio, each arm resampled independently (BENCHMARK_ENGINE §6).
  const brng = mulberry32(7);
  const ratios: number[] = [];
  for (let r = 0; r < BOOTSTRAP_RESAMPLES; r++) {
    const rb = Array.from({ length: n }, () => at(baseline, Math.floor(brng() * n)));
    const rc = Array.from({ length: n }, () => at(candidate, Math.floor(brng() * n)));
    ratios.push(median(rb) / median(rc));
  }
  const baselineMedian = median(baseline);
  const candidateMedian = median(candidate);
  return {
    n,
    baseline,
    candidate,
    baselineMedian,
    candidateMedian,
    ratio: baselineMedian / candidateMedian,
    ciLow: quantile(ratios, 0.025),
    ciHigh: quantile(ratios, 0.975),
    baselineCv: coefficientOfVariation(baseline),
    candidateCv: coefficientOfVariation(candidate),
    transportFloorMs: 0.62,
  };
}

export const ILLUSTRATIVE_BENCH = makeIllustrativeBench();
