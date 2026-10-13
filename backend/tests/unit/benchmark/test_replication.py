"""verified_with_noise_warning by agreement of independent experiments (ADR-0019 §3)."""

import uuid
from typing import Any

import pytest

from querycure.benchmark.replication import (
    REPLICATES,
    Replicate,
    assess_all,
    assess_arm,
    eligible_arms,
    replicate_config,
)
from querycure.domain.benchmark import (
    CandidateArm,
    ExperimentConfig,
    ExperimentResult,
    LatencySummary,
    NoiseCheck,
    NoiseScreen,
    ParamSetSpec,
    Reason,
    RuleVerdict,
    SpeedupStats,
)

ARM = "oc_aaaaaaaaaaaa"
OTHER = "oc_bbbbbbbbbbbb"
ENV = "e" * 64


def _arm(key: str = ARM, ddl: str = "CREATE INDEX ON t (a)") -> CandidateArm:
    return CandidateArm(arm=key, candidate_id=None, kind="create_index", ddl=[ddl], query=None)


def _config(index: int, arms: list[CandidateArm] | None = None, **kw: Any) -> ExperimentConfig:
    body: dict[str, Any] = {
        "experiment_id": uuid.UUID(int=index + 1),
        "workload_id": "orders_ecommerce@v1:sf=0.1:seed=42",
        "baseline_query": "SELECT * FROM orders WHERE customer_id = $1",
        "candidates": arms or [_arm()],
        "param_sets": [ParamSetSpec(name="hot", values=[1]), ParamSetSpec(name="cold", values=[2])],
        "seed": 100 + index,
    }
    body.update(kw)
    return ExperimentConfig.model_validate(body)


def _summary(robust_cv: float) -> LatencySummary:
    return LatencySummary(n=30, median_ns=1e6, p95_ns=None, min_ns=1, max_ns=2, iqr_ns=1.0,
                          cv=0.5, robust_cv=robust_cv)  # fmt: skip


def _stats(arm: str, ps: str, low: float, high: float) -> SpeedupStats:
    return SpeedupStats(arm=arm, param_set=ps, baseline=_summary(0.05), candidate=_summary(0.4),
                        speedup=(low + high) / 2, ci_low=low, ci_high=high)  # fmt: skip


def _screen(arm: str, eligible: bool = True) -> NoiseScreen:
    return NoiseScreen(
        arm=arm,
        eligible=eligible,
        checks=[NoiseCheck(name="separation", passed=eligible, detail="")],
        max_robust_cv=0.4,
    )


NOISY = RuleVerdict(
    arm=ARM,
    verdict="inconclusive",
    gate=4,
    reasons=[Reason(code="insufficient_evidence", detail="robust CV 0.40")],
)


def _replicate(
    index: int,
    *,
    primary: tuple[float, float] = (5.0, 7.0),
    cold: tuple[float, float] = (4.0, 6.0),
    verdict: RuleVerdict = NOISY,
    eligible: bool = True,
    env: str = ENV,
    provenance: str = "measured",
    config: ExperimentConfig | None = None,
) -> Replicate:
    config = config or _config(index)
    result = ExperimentResult(
        experiment_id=config.experiment_id,
        environment_digest=env,
        builds=[],
        measurements=[],
        stats=[_stats(ARM, "hot", *primary), _stats(ARM, "cold", *cold)],
        verdicts=[verdict],
        tournament=[],
        winner=ARM if verdict.verdict == "verified" else None,
        order_is_total=False,
        noise_screens=[] if verdict.gate != 4 else [_screen(ARM, eligible)],
        provenance=provenance,  # type: ignore[arg-type]
    )
    return Replicate(config=config, result=result)


def _three(**kw: Any) -> list[Replicate]:
    return [_replicate(i, **kw) for i in range(REPLICATES)]


def test_three_agreeing_noisy_replicates_verify_with_a_warning() -> None:
    reps = [_replicate(0, primary=(5.0, 7.0)), _replicate(1, primary=(6.0, 8.0)),
            _replicate(2, primary=(5.5, 6.5))]  # fmt: skip

    v = assess_arm(ARM, reps)

    assert v.verdict == "verified_with_noise_warning", v
    assert (v.ci_low, v.ci_high) == (5.0, 8.0)  # conservative: widest range across replicates
    assert v.experiment_ids == [r.config.experiment_id for r in reps]
    assert v.max_robust_cv == pytest.approx(0.4)


def test_fewer_than_three_replicates_stay_inconclusive() -> None:
    v = assess_arm(ARM, _three()[:2])

    assert (v.verdict, v.reasons[0].code) == ("inconclusive", "insufficient_evidence")
    assert "2 of 3" in v.reasons[0].detail


def test_non_overlapping_cis_disagree() -> None:
    """Each CI is narrow and above min_effect, yet they exclude each other."""
    reps = [_replicate(0, primary=(5.0, 6.0)), _replicate(1, primary=(9.0, 11.0)),
            _replicate(2, primary=(5.5, 6.5))]  # fmt: skip

    v = assess_arm(ARM, reps)

    assert (v.verdict, v.reasons[0].code) == ("inconclusive", "replicates_disagree")


def test_one_ineligible_screen_blocks_verification() -> None:
    reps = _three()
    reps[1] = _replicate(1, eligible=False)

    assert assess_arm(ARM, reps).verdict == "inconclusive"


@pytest.mark.parametrize(
    "verdict",
    [
        RuleVerdict(arm=ARM, verdict="rejected", gate=5, reasons=[Reason(code="regression")]),
        RuleVerdict(arm=ARM, verdict="inconclusive", gate=6,
                    reasons=[Reason(code="effect_not_significant")]),
        RuleVerdict(arm=ARM, verdict="inconclusive", gate=5,
                    reasons=[Reason(code="insufficient_evidence")]),
    ],
)  # fmt: skip
def test_any_other_replicate_verdict_blocks_verification(verdict: RuleVerdict) -> None:
    reps = _three()
    reps[2] = _replicate(2, verdict=verdict)

    assert assess_arm(ARM, reps).verdict == "inconclusive"


def test_replicates_must_be_independent() -> None:
    same_seed = [_replicate(i, config=_config(i, seed=7)) for i in range(3)]
    same_id = [_replicate(0) for _ in range(3)]

    assert "seed" in assess_arm(ARM, same_seed).reasons[0].detail
    assert "experiment" in assess_arm(ARM, same_id).reasons[0].detail


@pytest.mark.parametrize(
    ("field", "make"),
    [
        ("environment", lambda: _replicate(2, env="f" * 64)),
        ("sql", lambda: _replicate(2, config=_config(2, arms=[_arm(ddl="CREATE INDEX ON t (b)")]))),
        ("thresholds", lambda: _replicate(2, config=_config(2, min_effect=1.5))),
        ("query", lambda: _replicate(2, config=_config(2, baseline_query="SELECT 1"))),
        ("param sets", lambda: _replicate(2, config=_config(
            2, param_sets=[ParamSetSpec(name="hot", values=[9]),
                           ParamSetSpec(name="cold", values=[2])]))),
    ],
)  # fmt: skip
def test_replicates_must_be_comparable(field: str, make: Any) -> None:
    reps = _three()
    reps[2] = make()

    v = assess_arm(ARM, reps)

    assert v.verdict == "inconclusive"
    assert field in v.reasons[0].detail


def test_prerecorded_evidence_never_counts() -> None:
    reps = _three()
    reps[0] = _replicate(0, provenance="prerecorded")

    assert "prerecorded" in assess_arm(ARM, reps).reasons[0].detail


def test_bench1_results_never_count() -> None:
    reps = _three()
    old = reps[0].result.model_copy(
        update={"engine_version": "bench@1", "schema_version": 1, "noise_screens": None}
    )
    reps[0] = Replicate(config=reps[0].config, result=old)

    assert "bench@1" in assess_arm(ARM, reps).reasons[0].detail


def test_a_possible_regression_in_any_replicate_blocks_verification() -> None:
    clean = RuleVerdict(arm=ARM, verdict="verified", gate=None, reasons=[])
    reps = _three()
    reps[1] = _replicate(1, verdict=clean, cold=(0.9, 1.2))  # verified, but cold may regress

    assert assess_arm(ARM, reps).verdict == "inconclusive"


def test_three_clean_verifications_are_plainly_verified() -> None:
    clean = RuleVerdict(arm=ARM, verdict="verified", gate=None, reasons=[])

    assert assess_arm(ARM, _three(verdict=clean)).verdict == "verified"


def test_replicate_config_is_independent_and_deterministic() -> None:
    base = _config(0, arms=[_arm(), _arm(OTHER)])

    first, again, second = (replicate_config(base, 1, [ARM]), replicate_config(base, 1, [ARM]),
                            replicate_config(base, 2, [ARM]))  # fmt: skip

    assert first == again
    assert len({base.experiment_id, first.experiment_id, second.experiment_id}) == 3
    assert len({base.seed, first.seed, second.seed}) == 3
    assert [c.arm for c in first.candidates] == [ARM]
    keep = {"experiment_id", "seed", "candidates"}
    assert first.model_dump(exclude=keep) == base.model_dump(exclude=keep)
    with pytest.raises(ValueError, match="starts at 1"):
        replicate_config(base, 0, [ARM])
    with pytest.raises(ValueError, match="must be candidates"):
        replicate_config(base, 1, ["oc_cccccccccccc"])


def test_eligible_arms_come_from_screens_and_only_without_a_winner() -> None:
    noisy = _replicate(0).result

    assert eligible_arms(noisy) == [ARM]
    assert eligible_arms(_replicate(0, eligible=False).result) == []
    assert eligible_arms(noisy.model_copy(update={"winner": OTHER})) == []


def test_assess_all_ranks_noise_verified_winners_by_their_worst_lower_bound() -> None:
    def rep(i: int, a: tuple[float, float], b: tuple[float, float]) -> Replicate:
        arms = [_arm(), _arm(OTHER, ddl="CREATE INDEX ON t (b)")]
        cfg = _config(i, arms=arms)
        noisy = [NOISY, NOISY.model_copy(update={"arm": OTHER})]
        result = ExperimentResult(
            experiment_id=cfg.experiment_id, environment_digest=ENV, builds=[], measurements=[],
            stats=[_stats(ARM, "hot", *a), _stats(ARM, "cold", 2.0, 3.0),
                   _stats(OTHER, "hot", *b), _stats(OTHER, "cold", 2.0, 3.0)],
            verdicts=noisy, tournament=[], winner=None, order_is_total=False,
            noise_screens=[_screen(ARM), _screen(OTHER)],
        )  # fmt: skip
        return Replicate(config=cfg, result=result)

    reps = [rep(0, (5, 9), (8, 9)), rep(1, (6, 9), (7.5, 9)), rep(2, (5.5, 9), (8, 9))]

    outcome = assess_all(reps)

    assert {v.arm: v.verdict for v in outcome.verdicts} == {
        ARM: "verified_with_noise_warning", OTHER: "verified_with_noise_warning"
    }  # fmt: skip
    assert outcome.winner == OTHER  # worst lower bound 7.5 beats 5.0
    assert outcome.source_experiment_id == reps[0].config.experiment_id
