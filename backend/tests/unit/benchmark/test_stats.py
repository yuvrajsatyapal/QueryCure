import math
import random

import pytest

from querycure.benchmark.stats import bootstrap_speedup_ci, speedup, summarize


def test_summary_of_known_values() -> None:
    s = summarize([10, 20, 30, 40, 50])

    assert (s.n, s.median_ns, s.min_ns, s.max_ns) == (5, 30.0, 10, 50)
    assert s.iqr_ns == 20.0  # inclusive quartiles 20 and 40
    assert s.cv == pytest.approx(math.sqrt(250) / 30)


def test_even_sample_median_is_midpoint() -> None:
    assert summarize([1, 2, 3, 4]).median_ns == 2.5


def test_p95_is_suppressed_below_twenty_samples() -> None:
    assert summarize(list(range(1, 20))).p95_ns is None


def test_p95_uses_nearest_rank() -> None:
    assert summarize(list(range(1, 21))).p95_ns == 19
    assert summarize(list(range(1, 101))).p95_ns == 95


def test_single_sample_has_no_cv() -> None:
    assert summarize([7]).cv is None


def test_empty_samples_are_refused() -> None:
    with pytest.raises(ValueError, match="no samples"):
        summarize([])


def test_speedup_is_ratio_of_medians() -> None:
    assert speedup([100, 100, 100], [10, 10, 10]) == 10.0


def test_bootstrap_is_deterministic_for_a_seed() -> None:
    base = [100 + i for i in range(30)]
    cand = [40 + (i * 7) % 11 for i in range(30)]

    first = bootstrap_speedup_ci(base, cand, seed=42)
    again = bootstrap_speedup_ci(base, cand, seed=42)
    other = bootstrap_speedup_ci(base, cand, seed=43)

    assert first == again
    assert first != other
    assert first[0] <= speedup(base, cand) <= first[1]


def test_identical_constant_arms_give_a_point_interval() -> None:
    assert bootstrap_speedup_ci([5] * 10, [5] * 10, seed=1) == (1.0, 1.0)


def _lognormal(rng: random.Random, median: float, n: int) -> list[int]:
    return [round(rng.lognormvariate(math.log(median), 0.3)) for _ in range(n)]


def test_ci_covers_the_true_ratio_on_synthetic_distributions() -> None:
    """Property: a 95% CI of the median ratio should contain the true ratio most of the time."""
    rng = random.Random(2026)
    trials, covered = 60, 0
    for trial in range(trials):
        true_ratio = rng.choice([1.0, 1.5, 3.0, 12.0])
        base = _lognormal(rng, 1_000_000 * true_ratio, 30)
        cand = _lognormal(rng, 1_000_000, 30)
        low, high = bootstrap_speedup_ci(base, cand, seed=trial, resamples=1000)
        covered += low <= true_ratio <= high
    assert covered / trials >= 0.85


def test_robust_cv_ignores_a_sparse_spike_that_dominates_classic_cv() -> None:
    samples = [1_000 + (i % 5) * 10 for i in range(19)] + [3_000]

    s = summarize(samples)

    assert s.cv is not None
    assert s.cv > 0.25
    assert s.robust_cv is not None
    assert s.robust_cv < 0.05


def test_robust_cv_flags_a_broad_distribution() -> None:
    s = summarize([1_000 * (1 + (i % 4)) for i in range(20)])

    assert s.robust_cv is not None
    assert s.robust_cv > 0.25


def test_robust_cv_is_iqr_over_scaled_median() -> None:
    s = summarize([10, 20, 30, 40, 50])

    assert s.robust_cv == pytest.approx(20 / (1.349 * 30))
