"""bench@2 rule changes (ADR-0019): corroborated regressions and the per-experiment noise screen.

bench@1 stays frozen for replay, so every behavioural difference is asserted against both.
"""

import pytest

from querycure.benchmark.rules import CandidateEvidence, assess, compute_stats, evaluate
from querycure.domain.benchmark import ExperimentConfig, NoiseScreen, RuleVerdict
from tests.unit.benchmark.test_rules import (
    FAST,
    SLOW,
    _config,
    _evidence,
    _samples,
    blocks_of,
)


def _both(
    ev: CandidateEvidence, config: ExperimentConfig | None = None
) -> tuple[RuleVerdict, RuleVerdict, NoiseScreen | None]:
    config = config or _config()
    stats = compute_stats(ev, config)
    v1 = evaluate(ev, config, stats, query_has_params=True, engine_version="bench@1")
    v2, screen = assess(ev, config, stats, query_has_params=True, engine_version="bench@2")
    return v1, v2, screen


def _code(v: RuleVerdict) -> tuple[str, int | None, str | None]:
    return v.verdict, v.gate, v.reasons[0].code if v.reasons else None


# --- Gate 5: a regression must be corroborated before it rejects --------------------------


def test_consistent_regression_still_rejects_in_both_versions() -> None:
    ev = _evidence(base=SLOW, cand={"hot": _samples(1_000), "cold": _samples(20_000)})

    v1, v2, _ = _both(ev)

    assert _code(v1) == _code(v2) == ("rejected", 5, "regression")
    assert "cold" in v2.reasons[0].detail


def test_regression_with_fewer_than_twenty_samples_is_not_decisive() -> None:
    cand = {"hot": _samples(1_000), "cold": _samples(20_000, n=15)}

    v1, v2, _ = _both(_evidence(base=SLOW, cand=cand))

    assert _code(v1) == ("rejected", 5, "regression")
    assert _code(v2) == ("inconclusive", 5, "insufficient_evidence")
    assert "n=15" in v2.reasons[0].detail


def test_regression_against_a_censored_baseline_is_not_decisive() -> None:
    """A baseline timeout removes its slow tail: the regression could be an artefact (A3)."""
    ev = _evidence(
        base=SLOW,
        cand={"hot": _samples(1_000), "cold": _samples(20_000)},
        base_failures={"cold": ["timeout"]},
    )

    v1, v2, _ = _both(ev)

    assert _code(v1) == ("rejected", 5, "regression")
    assert _code(v2) == ("inconclusive", 5, "insufficient_evidence")
    assert "baseline" in v2.reasons[0].detail


def test_regression_seen_in_only_some_blocks_is_not_decisive() -> None:
    """Misleadingly narrow CI: an arm-specific disturbance in 5 of 6 blocks shifts the median,
    and the iid bootstrap reports a tight CI far below max_regression. One block disagrees."""
    cold = _samples(20_000)
    cold[10:15] = _samples(10_000, n=5)  # block 2: no slowdown at all
    ev = _evidence(base=SLOW, cand={"hot": _samples(1_000), "cold": cold})
    stats = compute_stats(ev, _config())
    assert stats["cold"].ci_high < 0.95  # the CI alone looks decisive

    v1, v2, _ = _both(ev)

    assert _code(v1) == ("rejected", 5, "regression")
    assert _code(v2) == ("inconclusive", 5, "insufficient_evidence")
    assert "block" in v2.reasons[0].detail


def test_a_block_slightly_below_one_does_not_corroborate() -> None:
    """A no-difference block lands below 1.0 half the time; it must clear max_regression."""
    cold = _samples(20_000)
    cold[10:15] = _samples(10_300, n=5)  # ratio ~0.97: below 1.0, above 0.95
    ev = _evidence(base=SLOW, cand={"hot": _samples(1_000), "cold": cold})

    _, v2, _ = _both(ev)

    assert _code(v2) == ("inconclusive", 5, "insufficient_evidence")
    assert "1 of 6 blocks" in v2.reasons[0].detail


def test_regression_needs_at_least_three_blocks() -> None:
    ev = _evidence(base=SLOW, cand={"hot": _samples(1_000), "cold": _samples(20_000)})
    two_blocks = {ps: blocks_of(ev.baseline[ps].latencies_ns, ev.candidate[ps].latencies_ns, 15)
                  for ps in ("hot", "cold")}  # fmt: skip
    ev = CandidateEvidence(
        arm=ev.arm, build=ev.build, baseline=ev.baseline, candidate=ev.candidate,
        correctness=ev.correctness, blocks=two_blocks,
    )  # fmt: skip

    _, v2, _ = _both(ev)

    assert _code(v2) == ("inconclusive", 5, "insufficient_evidence")


def test_missing_block_structure_fails_closed() -> None:
    ev = _evidence(base=SLOW, cand={"hot": _samples(1_000), "cold": _samples(20_000)})
    ev = CandidateEvidence(
        arm=ev.arm, build=ev.build, baseline=ev.baseline, candidate=ev.candidate,
        correctness=ev.correctness,
    )  # fmt: skip

    _, v2, _ = _both(ev)

    assert _code(v2) == ("inconclusive", 5, "insufficient_evidence")


def test_corroborated_regression_wins_over_an_uncorroborated_one() -> None:
    hot = _samples(20_000)
    hot[0:5] = _samples(10_000, n=5)  # hot: indicated, one block disagrees
    base = {"hot": SLOW["hot"], "cold": SLOW["cold"]}
    ev = _evidence(base=base, cand={"hot": hot, "cold": _samples(30_000)})

    _, v2, _ = _both(ev)

    assert _code(v2) == ("rejected", 5, "regression")
    assert "cold" in v2.reasons[0].detail


def test_uncorroborated_regression_is_never_verified() -> None:
    """Losing the right to reject does not grant the right to verify."""
    cand = {"hot": _samples(1_000), "cold": _samples(20_000, n=15)}

    _, v2, screen = _both(_evidence(base=SLOW, cand=cand))

    assert v2.verdict != "verified"
    assert screen is None


# --- Noise screen (D11): recorded on gate-4b failures only; the verdict does not change ------

# Broad but clearly separated: per block [300, 600, 900, 1200, 300] ns, robust CV ~ 0.6.
NOISY_FAST = [300 * (1 + (i % 4)) for i in range(30)]


def test_noisy_but_separated_win_stays_inconclusive_with_an_eligible_screen() -> None:
    ev = _evidence(base=SLOW, cand={"hot": NOISY_FAST, "cold": _samples(1_000)})

    v1, v2, screen = _both(ev)

    assert _code(v1) == _code(v2) == ("inconclusive", 4, "insufficient_evidence")
    assert screen is not None
    assert screen.eligible, screen
    assert {c.name for c in screen.checks} == {
        "n", "censor", "noregress", "effect", "separation", "blocks"
    }  # fmt: skip
    assert all(c.passed for c in screen.checks)
    assert screen.max_robust_cv is not None
    assert screen.max_robust_cv > 0.25


def _failed(screen: NoiseScreen | None) -> set[str]:
    assert screen is not None
    assert not screen.eligible
    return {c.name for c in screen.checks if not c.passed}


def test_overlapping_distributions_fail_separation() -> None:
    """CI lower bound above min_effect, but the middle halves overlap: not good enough."""
    # 120 evenly spread samples per arm, shuffled by a fixed permutation: a CI from many samples
    # is narrow, but quartiles do not shrink with n. base 5-15 us, candidate 5.5-8.5 us.
    order = [(i * 37) % 120 for i in range(120)]
    base = [5_000 + round(10_000 * k / 119) for k in order]
    cand = [5_500 + round(3_000 * k / 119) for k in order]
    ev = _evidence(
        base={"hot": base, "cold": _samples(10_000, n=120)},
        cand={"hot": cand, "cold": _samples(1_000, n=120)},
    )
    stats = compute_stats(ev, _config())
    assert stats["hot"].ci_low >= 1.10

    _, v2, screen = _both(ev)

    assert _code(v2) == ("inconclusive", 4, "insufficient_evidence")
    assert "separation" in _failed(screen)


def test_a_block_without_the_effect_fails_the_screen() -> None:
    """Misleadingly narrow CI on the win side: the effect is absent in one block."""
    hot = list(NOISY_FAST)
    hot[15:20] = _samples(10_000, n=5)
    ev = _evidence(base=SLOW, cand={"hot": hot, "cold": _samples(1_000)})
    assert compute_stats(ev, _config())["hot"].ci_low >= 1.10

    _, _, screen = _both(ev)

    assert _failed(screen) == {"blocks"}


def test_any_censored_sample_fails_the_screen() -> None:
    ev = _evidence(
        base=SLOW,
        cand={"hot": NOISY_FAST, "cold": _samples(1_000)},
        cand_failures={"hot": ["timeout"]},
    )

    _, _, screen = _both(ev)

    assert "censor" in _failed(screen)


def test_fewer_than_thirty_samples_fail_the_screen() -> None:
    ev = _evidence(
        base={"hot": _samples(10_000, n=20), "cold": _samples(10_000, n=20)},
        cand={"hot": NOISY_FAST[:20], "cold": _samples(1_000, n=20)},
    )

    _, _, screen = _both(ev)

    assert "n" in _failed(screen)


def test_possible_regression_on_another_param_set_fails_the_screen() -> None:
    """No evidence of harm is not evidence of no harm: the secondary CI must clear 0.95."""
    wide = [7_000, 9_000, 11_000, 13_000, 15_000] * 6
    ev = _evidence(
        base={"hot": SLOW["hot"], "cold": wide}, cand={"hot": NOISY_FAST, "cold": wide[::-1]}
    )
    stats = compute_stats(ev, _config())
    assert stats["cold"].ci_low < 0.95 <= stats["cold"].ci_high

    _, v2, screen = _both(ev)

    assert v2.gate == 4
    assert "noregress" in _failed(screen)


@pytest.mark.parametrize(
    ("base", "cand"),
    [
        (SLOW, FAST),  # verified
        ({"hot": _samples(10_000, spread=300), "cold": SLOW["cold"]},
         {"hot": _samples(10_000, spread=300), "cold": FAST["cold"]}),  # gate 6
        (SLOW, {"hot": _samples(1_000, n=9), "cold": FAST["cold"]}),  # gate 4a
    ],
)  # fmt: skip
def test_screen_is_recorded_only_for_gate_4b_failures(
    base: dict[str, list[int]], cand: dict[str, list[int]]
) -> None:
    _, v2, screen = _both(_evidence(base=base, cand=cand))

    assert v2.gate != 4 or v2.reasons[0].detail.endswith("n=9")
    assert screen is None


def test_bench1_never_produces_a_screen() -> None:
    ev = _evidence(base=SLOW, cand={"hot": NOISY_FAST, "cold": _samples(1_000)})
    config = _config()

    _, screen = assess(
        ev, config, compute_stats(ev, config), query_has_params=True, engine_version="bench@1"
    )

    assert screen is None


def test_unknown_engine_version_is_refused() -> None:
    ev = _evidence(base=SLOW, cand=FAST)
    config = _config()

    with pytest.raises(ValueError, match="bench@9"):
        evaluate(ev, config, compute_stats(ev, config), query_has_params=True,
                 engine_version="bench@9")  # fmt: skip


@pytest.mark.xfail(
    strict=True,
    reason="Known limitation (ADR-0019 residual risk, PHASE_3_REPORT §6): the clean verified "
    "path has no block check, so a tight arm-specific bias in 5 of 6 blocks verifies. "
    "Changing gate 6 is an owner decision.",
)
def test_known_limitation_tight_bias_in_most_blocks_is_not_verified() -> None:
    hot = _samples(10_000)
    for start in range(5, 30, 5):  # baseline delayed 2x in blocks 1-5; block 0 shows no effect
        hot[start : start + 5] = _samples(20_000, n=5)
    ev = _evidence(
        base={"hot": hot, "cold": SLOW["cold"]},
        cand={"hot": _samples(10_000), "cold": FAST["cold"]},
    )

    _, v2, _ = _both(ev)

    assert v2.verdict != "verified"
