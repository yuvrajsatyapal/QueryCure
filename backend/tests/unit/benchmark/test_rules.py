"""Verdict gates 1-6 (BENCHMARK_ENGINE §7): evaluated in order, first failure wins."""

import uuid

import pytest

from querycure.benchmark.correctness import CorrectnessOutcome
from querycure.benchmark.rules import CandidateEvidence, compute_stats, evaluate
from querycure.domain.benchmark import (
    ArmFingerprint,
    ArmMeasurement,
    BuildResult,
    CandidateArm,
    ExperimentConfig,
    ParamSetSpec,
)

ARM = "oc_aaaaaaaaaaaa"
FP = ArmFingerprint(rows=20, multiset="m", ordered="o", truncated=False)
MATCH = CorrectnessOutcome("match")


def _config(**overrides: object) -> ExperimentConfig:
    base: dict[str, object] = {
        "experiment_id": uuid.uuid4(),
        "workload_id": "orders_ecommerce@v1:sf=0.1:seed=42",
        "baseline_query": "SELECT 1",
        "candidates": [_arm()],
        "param_sets": [ParamSetSpec(name="hot", values=[1]), ParamSetSpec(name="cold", values=[2])],
        "seed": 42,
    }
    base.update(overrides)
    return ExperimentConfig.model_validate(base)


def _arm(kind: str = "create_index") -> CandidateArm:
    return CandidateArm(
        arm=ARM,
        candidate_id=None,
        kind=kind,  # type: ignore[arg-type]
        ddl=["CREATE INDEX ON t (a)"] if kind == "create_index" else [],
        query="SELECT 2" if kind == "query_rewrite" else None,
    )


def _samples(center: int, n: int = 30, spread: int = 2) -> list[int]:
    return [center + (i % (2 * spread + 1)) - spread for i in range(n)]


def _m(arm: str, ps: str, samples: list[int], failures: list[str] | None = None) -> ArmMeasurement:
    return ArmMeasurement(
        arm=arm,
        param_set=ps,
        latencies_ns=samples,
        failures=failures or [],  # type: ignore[arg-type]
        fingerprint=FP,
        consistent=True,
    )


def _evidence(
    *,
    base: dict[str, list[int]],
    cand: dict[str, list[int]],
    build: BuildResult | None = None,
    correctness: dict[str, CorrectnessOutcome] | None = None,
    base_failures: dict[str, list[str]] | None = None,
    cand_failures: dict[str, list[str]] | None = None,
    kind: str = "create_index",
) -> CandidateEvidence:
    return CandidateEvidence(
        arm=_arm(kind),
        build=build or BuildResult(arm=ARM, ok=True),
        baseline={
            ps: _m("baseline", ps, s, (base_failures or {}).get(ps)) for ps, s in base.items()
        },
        candidate={ps: _m(ARM, ps, s, (cand_failures or {}).get(ps)) for ps, s in cand.items()},
        correctness=correctness or {ps: MATCH for ps in base},
        blocks={ps: blocks_of(base[ps], cand[ps]) for ps in base if ps in cand},
    )


def blocks_of(base: list[int], cand: list[int], size: int = 5) -> list[tuple[list[int], list[int]]]:
    """Interleaved blocks as the engine records them: `size` samples per arm per block."""
    count = max(len(base), len(cand)) // size + (max(len(base), len(cand)) % size > 0)
    return [
        (base[i * size : (i + 1) * size], cand[i * size : (i + 1) * size]) for i in range(count)
    ]


def _verdict(ev: CandidateEvidence, config: ExperimentConfig | None = None, **kw: bool):  # type: ignore[no-untyped-def]
    config = config or _config()
    return evaluate(ev, config, compute_stats(ev, config), query_has_params=kw.get("params", True))


FAST = {"hot": _samples(1_000), "cold": _samples(1_000)}
SLOW = {"hot": _samples(10_000), "cold": _samples(10_000)}


def test_clear_win_is_verified() -> None:
    v = _verdict(_evidence(base=SLOW, cand=FAST))

    assert (v.verdict, v.gate, v.reasons) == ("verified", None, [])


@pytest.mark.parametrize("reason", ["ddl_failed", "constraint_violation"])
def test_gate1_build_failure_rejects(reason: str) -> None:
    build = BuildResult(arm=ARM, ok=False, reason=reason, detail="x")  # type: ignore[arg-type]

    v = _verdict(_evidence(base=SLOW, cand=FAST, build=build))

    assert (v.verdict, v.gate, v.reasons[0].code) == ("rejected", 1, reason)


def test_gate2_too_many_timeouts_is_unstable() -> None:
    v = _verdict(
        _evidence(base=SLOW, cand=FAST, cand_failures={"hot": ["timeout"] * 5}),
    )

    assert (v.verdict, v.gate, v.reasons[0].code) == ("inconclusive", 2, "unstable_execution")


def test_gate2_tolerates_a_few_timeouts() -> None:
    v = _verdict(_evidence(base=SLOW, cand=FAST, cand_failures={"hot": ["timeout"]}))

    assert v.verdict == "verified"


def test_gate3_candidate_only_errors_reject_even_when_frequent() -> None:
    """Error parity: a candidate that fails where the baseline works is wrong, not noisy."""
    v = _verdict(_evidence(base=SLOW, cand=FAST, cand_failures={"hot": ["error"] * 30}))

    assert (v.verdict, v.gate, v.reasons[0].code) == ("rejected", 3, "result_mismatch")


def test_gate3_mismatch_rejects_before_noise_is_considered() -> None:
    mismatch = CorrectnessOutcome("mismatch", "result_mismatch", "row count 3 vs 4")
    noisy = {"hot": [i * 1000 for i in range(1, 31)], "cold": _samples(1_000)}

    v = _verdict(_evidence(base=SLOW, cand=noisy, correctness={"hot": MATCH, "cold": mismatch}))

    assert (v.verdict, v.gate, v.reasons[0].code) == ("rejected", 3, "result_mismatch")


def test_gate3_mismatch_beats_nondeterminism_across_param_sets() -> None:
    v = _verdict(
        _evidence(
            base=SLOW,
            cand=FAST,
            correctness={
                "hot": CorrectnessOutcome("inconclusive", "nondeterministic_order"),
                "cold": CorrectnessOutcome("mismatch", "result_mismatch"),
            },
        )
    )

    assert v.reasons[0].code == "result_mismatch"


@pytest.mark.parametrize("reason", ["nondeterministic_order", "result_too_large"])
def test_gate3_inconclusive_correctness(reason: str) -> None:
    outcome = CorrectnessOutcome("inconclusive", reason)

    v = _verdict(_evidence(base=SLOW, cand=FAST, correctness={"hot": outcome, "cold": MATCH}))

    assert (v.verdict, v.gate, v.reasons[0].code) == ("inconclusive", 3, reason)


def test_gate3_rewrite_with_parameters_needs_three_param_sets_and_an_edge_case() -> None:
    v = _verdict(_evidence(base=SLOW, cand=FAST, kind="query_rewrite"))

    assert (v.verdict, v.gate, v.reasons[0].code) == ("inconclusive", 3, "insufficient_evidence")


def test_gate3_parameterless_rewrite_is_not_held_to_param_set_rule() -> None:
    v = _verdict(_evidence(base=SLOW, cand=FAST, kind="query_rewrite"), params=False)

    assert v.verdict == "verified"


def test_gate4_high_cv_is_insufficient_evidence() -> None:
    noisy = {"hot": [1_000 * (1 + (i % 3) * 2) for i in range(30)], "cold": _samples(1_000)}

    v = _verdict(_evidence(base=SLOW, cand=noisy))

    assert (v.verdict, v.gate, v.reasons[0].code) == ("inconclusive", 4, "insufficient_evidence")


def test_gate4_requires_ten_successful_samples() -> None:
    few = {"hot": _samples(1_000, n=9), "cold": _samples(1_000)}

    v = _verdict(_evidence(base=SLOW, cand=few))

    assert (v.gate, v.reasons[0].code) == (4, "insufficient_evidence")


def test_gate5_regression_on_any_param_set_rejects() -> None:
    cand = {"hot": _samples(1_000), "cold": _samples(20_000)}

    v = _verdict(_evidence(base=SLOW, cand=cand))

    assert (v.verdict, v.gate, v.reasons[0].code) == ("rejected", 5, "regression")
    assert "cold" in v.reasons[0].detail


def test_gate6_no_improvement_when_ci_is_below_one() -> None:
    cand = {"hot": _samples(10_300, spread=5), "cold": _samples(10_000)}

    v = _verdict(_evidence(base=SLOW, cand=cand), _config(max_regression=0.5))

    assert (v.verdict, v.gate, v.reasons[0].code) == ("rejected", 6, "no_improvement")


def test_gate6_straddling_ci_is_not_significant() -> None:
    cand = {"hot": _samples(10_000, spread=300), "cold": _samples(10_000)}
    base = {"hot": _samples(10_000, spread=300), "cold": _samples(10_000)}

    v = _verdict(_evidence(base=base, cand=cand))

    assert (v.verdict, v.gate, v.reasons[0].code) == ("inconclusive", 6, "effect_not_significant")


def test_gate6_uses_the_primary_param_set_only() -> None:
    """A big win on a secondary set cannot verify a candidate that is flat on the primary."""
    cand = {"hot": _samples(10_000), "cold": _samples(1_000)}

    v = _verdict(_evidence(base=SLOW, cand=cand))

    assert v.verdict != "verified"
    assert v.gate == 6


def test_stats_are_computed_per_param_set_and_seeded() -> None:
    ev = _evidence(base=SLOW, cand=FAST)
    config = _config()

    stats = compute_stats(ev, config)

    assert set(stats) == {"hot", "cold"}
    assert stats["hot"].speedup == pytest.approx(10.0)
    assert stats["hot"].baseline.n == 30
    assert compute_stats(ev, config) == stats


def test_gate4_tolerates_sparse_spikes() -> None:
    """One 3x spike in 30 samples is environment noise, not a broad distribution (ADR-0018)."""
    spiky = _samples(1_000)
    spiky[7] = 3_000
    v = _verdict(_evidence(base=SLOW, cand={"hot": spiky, "cold": _samples(1_000)}))

    assert v.verdict == "verified"


def test_decisive_regression_rejects_even_with_noisy_samples() -> None:
    """Noise widens the CI, so a CI entirely below max_regression is real harm (ADR-0018)."""
    noisy_win = [300 * (1 + (i % 4)) for i in range(30)]  # broad: robust CV > 0.25
    cand = {"hot": noisy_win, "cold": _samples(50_000)}

    v = _verdict(_evidence(base=SLOW, cand=cand))

    assert (v.verdict, v.gate, v.reasons[0].code) == ("rejected", 5, "regression")


def test_sample_count_floor_still_precedes_regression() -> None:
    cand = {"hot": _samples(1_000), "cold": _samples(50_000, n=9)}

    v = _verdict(_evidence(base=SLOW, cand=cand))

    assert (v.gate, v.reasons[0].code) == (4, "insufficient_evidence")
