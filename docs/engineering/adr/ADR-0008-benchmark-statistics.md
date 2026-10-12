# ADR-0008: Median-based speedup with seeded percentile-bootstrap confidence intervals

- Status: Accepted (2026-10-11)
- Amended by: [ADR-0018](ADR-0018-robust-sample-quality-gate.md) (robust CV, gate order), [ADR-0019](ADR-0019-noise-warning-verification-and-corroborated-regression.md) (corroborated regression, replication rule, `bench@2`)
- Area: Benchmarking

## Context
Query latencies are right-skewed with outliers (GC, autovacuum, OS scheduling). We need a verdict that resists noise and expresses uncertainty, computed with minimal dependencies.

## Alternatives
1. Mean + Welch's t-test — sensitive to outliers and non-normality.
2. Mann–Whitney U — tests distribution shift, but doesn't give an effect-size interval directly.
3. **Ratio of medians + percentile bootstrap CI (2,000 resamples, fixed seed)** with gates on effect size (`min_effect`), regression (`max_regression`), and noise (`max_cv`).
4. HDR histogram percentile comparisons — great for high-volume load tests; overkill here.

## Decision
Option 3, implemented with stdlib `statistics` and `random` (no numpy/scipy).

## Rationale & trade-offs
- + Robust, assumption-light, explains well ("11–14× faster, 95% CI").
- + Deterministic given the seed → reproducible verdicts from stored samples.
- − Percentile bootstrap can be inaccurate for very small n; mitigated by n ≥ 10 hard floor and stricter rules for n < 20.
- − Independent resampling ignores pairing within blocks; acceptable, documented.

## Consequences
Thresholds are config, recorded in `ExperimentConfig` and the report. Changing defaults requires updating BENCHMARK_ENGINE §7 and the eval expectations.
