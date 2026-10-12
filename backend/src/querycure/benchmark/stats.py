"""Latency statistics (BENCHMARK_ENGINE §6, ADR-0008). Pure stdlib, deterministic given a seed.

Inputs are integer nanosecond samples. Every rule here (percentile method, resampling draw) is
spelled out instead of delegated, so a stored experiment recomputes to the same numbers on any
Python version: the only randomness is `Random.random()`, whose Mersenne Twister stream is
stable for an integer seed.
"""

import math
import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

P95_MIN_SAMPLES = 20
DEFAULT_RESAMPLES = 2_000
# IQR of a normal distribution is 1.349 sigma, so IQR / 1.349 estimates sigma robustly.
IQR_TO_SIGMA = 1.349


@dataclass(frozen=True)
class SampleSummary:
    n: int
    median_ns: float
    p95_ns: int | None  # nearest rank; None when n < 20 ("n/a (n<20)")
    min_ns: int
    max_ns: int
    iqr_ns: float
    cv: float | None  # sample stdev / mean; None when n < 2 (reported)
    # IQR / (1.349 * median): the sample-quality gate's dispersion (ADR-0018). Unlike CV it is
    # not dominated by one spike, and it matches the median-based speedup it protects.
    robust_cv: float | None


def _nearest_rank(ordered: Sequence[int], fraction: float) -> int:
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def summarize(samples: Sequence[int]) -> SampleSummary:
    if not samples:
        raise ValueError("no samples")
    ordered = sorted(samples)
    n = len(ordered)
    if n >= 2:
        q1, _, q3 = statistics.quantiles(ordered, n=4, method="inclusive")
        mean = statistics.fmean(ordered)
        cv = statistics.stdev(ordered) / mean if mean > 0 else None
    else:
        q1 = q3 = float(ordered[0])
        cv = None
    median = float(statistics.median(ordered))
    robust_cv = (q3 - q1) / (IQR_TO_SIGMA * median) if n >= 2 and median > 0 else None
    return SampleSummary(
        n=n,
        median_ns=median,
        p95_ns=_nearest_rank(ordered, 0.95) if n >= P95_MIN_SAMPLES else None,
        min_ns=ordered[0],
        max_ns=ordered[-1],
        iqr_ns=float(q3 - q1),
        cv=cv,
        robust_cv=robust_cv,
    )


def speedup(baseline: Sequence[int], candidate: Sequence[int]) -> float:
    """median(baseline) / median(candidate): > 1 means the candidate is faster."""
    return float(statistics.median(baseline)) / float(statistics.median(candidate))


def _resample(rng: random.Random, values: Sequence[int]) -> list[int]:
    n = len(values)
    return [values[int(rng.random() * n)] for _ in range(n)]


def bootstrap_speedup_ci(
    baseline: Sequence[int],
    candidate: Sequence[int],
    *,
    seed: int,
    resamples: int = DEFAULT_RESAMPLES,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """Percentile bootstrap CI of the ratio of medians; each arm resampled independently."""
    if not baseline or not candidate:
        raise ValueError("no samples")
    rng = random.Random(seed)  # noqa: S311 - reproducibility, not secrecy
    ratios = sorted(
        float(statistics.median(_resample(rng, baseline)))
        / float(statistics.median(_resample(rng, candidate)))
        for _ in range(resamples)
    )
    tail = (1 - confidence) / 2
    low = ratios[math.floor(tail * resamples)]
    high = ratios[math.ceil((1 - tail) * resamples) - 1]
    return low, high
