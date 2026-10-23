// Plain-language definitions for the benchmark figures (FINAL_UI_POLISH §2.3). They describe
// what the engine computes (BENCHMARK_ENGINE, ADR-0008, ADR-0018, ADR-0029); they add no rule.

export interface GlossaryEntry {
  term: string;
  text: string;
}

export const STATS_GLOSSARY: GlossaryEntry[] = [
  {
    term: "Speedup",
    text: "Baseline median latency divided by candidate median latency, per param set. 2× means the candidate took half the time; below 1× means it was slower.",
  },
  {
    term: "95% confidence interval (CI)",
    text: "A bootstrap interval around the speedup. Wide intervals mean the samples disagree. The verdict uses the interval, not the point: the lower end must clear the required effect (min_effect).",
  },
  {
    term: "IQR",
    text: "Interquartile range: the spread of the middle half of the samples (Q3 − Q1). It ignores the slowest and fastest quarter, so a few outliers barely move it.",
  },
  {
    term: "Robust CV",
    text: "Spread relative to the median, computed from the IQR rather than the standard deviation. Above max_cv the samples are too noisy to decide, and the result is inconclusive or sent to independent replication.",
  },
  {
    term: "Transport floor",
    text: "The median round trip of SELECT 1, measured outside the timed samples. It is time spent on network, relay and driver, paid by both arms, so when it is a large share of the fastest arm the measured speedup understates the server-side one.",
  },
  {
    term: "p95",
    text: "The 95th-percentile latency. Reported only with at least 20 samples; below that it would be one of the slowest samples, not a percentile.",
  },
];

export const FASTER_IS_NOT_VERIFIED =
  "Faster is not the same as verified. A recommendation is verified only when the candidate returned the same result rows as the baseline on every param set, passed every rule gate (build, complete measurements, correctness, sample count, no regression, dispersion, minimum effect), was not downgraded by the Benchmark Auditor, and, when single experiments were noisy, independent experiments agreed. It holds for the tested data, parameters and sandbox only.";
