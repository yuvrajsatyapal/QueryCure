"""Experiment-replay comparison classification (T4.7, REPLAY_ENGINE §9).

The original is a committed real experiment (stale_stats, verified under bench@1); replays are
derived from its samples so each classification row of §9.1 is reached on purpose.
"""

from pathlib import Path
from typing import Any

import pytest

from querycure.benchmark.fixtures import load_prerecorded
from querycure.domain.benchmark import (
    BuildResult,
    ExperimentResult,
    Reason,
    RuleVerdict,
)
from querycure.replay.comparison import classify_environment, compare_experiments

FIXTURES = Path(__file__).parents[3] / "evals" / "fixtures" / "experiments"
FIX = load_prerecorded(FIXTURES / "stale_stats_sf01.json")
ARM = FIX.config.candidates[0].arm


def scaled(result: ExperimentResult, arm: str, factor: float) -> ExperimentResult:
    """The arm's samples multiplied by `factor` (slower when > 1)."""
    ms = [
        m.model_copy(update={"latencies_ns": [int(x * factor) for x in m.latencies_ns]})
        if m.arm == arm
        else m
        for m in result.measurements
    ]
    return result.model_copy(update={"measurements": ms})


def with_verdict(
    result: ExperimentResult, verdict: str, code: str | None = None
) -> ExperimentResult:
    reasons = [Reason(code=code)] if code else []  # type: ignore[arg-type]
    return result.model_copy(
        update={
            "verdicts": [
                RuleVerdict(
                    arm=ARM,
                    verdict=verdict,
                    reasons=reasons,  # type: ignore[arg-type]
                    gate=None if verdict == "verified" else 6,
                )
            ],
        }
    )


def compare(replay: ExperimentResult, **kw: Any) -> dict[str, Any]:
    params: dict[str, Any] = {
        "original_id": str(FIX.config.experiment_id),
        "replay_id": "replay-1",
        "config": FIX.config,
        "original": FIX.result,
        "replay": replay,
        "original_env": FIX.environment,
        "replay_env": FIX.environment,
        "original_env_digest": "sha256:a",
        "replay_env_digest": "sha256:a",
        "replay_engine": "bench@1",
        "resamples": 400,
        **kw,
    }
    return compare_experiments(**params)


def test_identical_replay_is_reproduced_in_the_same_environment() -> None:
    out = compare(FIX.result)

    assert out["status"] == "reproduced"
    assert out["failure_code"] is None
    assert out["comparison_mode"] == "same_environment"
    assert {p["status"] for p in out["pairs"]} == {"reproduced"}
    # Same samples: the point drift is exactly 1; the four sets are resampled independently,
    # so the interval has width, but it lies inside the margin.
    assert all(p["drift"] == pytest.approx(1.0) for p in out["pairs"])
    assert all(0.8 <= p["drift_ci_low"] <= 1.0 <= p["drift_ci_high"] <= 1.25 for p in out["pairs"])
    assert out["environment"]["differences"] == []


def test_candidate_twice_as_slow_is_reproduced_with_drift() -> None:
    out = compare(scaled(FIX.result, ARM, 2.0))

    assert {p["status"] for p in out["pairs"]} == {"reproduced_with_drift"}
    assert all(p["drift_ci_high"] < 0.8 for p in out["pairs"])
    assert out["status"] == "reproduced_with_drift"


def test_drift_straddling_the_margin_is_undetermined() -> None:
    out = compare(scaled(FIX.result, ARM, 1.25))  # D = 0.8: right on the bound

    assert out["status"] == "inconclusive"
    assert out["failure_code"] == "drift_undetermined"


def test_different_rows_are_not_reproduced() -> None:
    ms = [
        m.model_copy(update={"fingerprint": m.fingerprint.model_copy(update={"multiset": "x"})})
        if m.arm == ARM and m.fingerprint
        else m
        for m in FIX.result.measurements
    ]
    out = compare(FIX.result.model_copy(update={"measurements": ms}))

    assert (out["status"], out["failure_code"]) == ("not_reproduced", "result_fingerprint_changed")


def test_too_few_samples_are_insufficient_evidence() -> None:
    ms = [
        m.model_copy(update={"latencies_ns": m.latencies_ns[:5]}) for m in FIX.result.measurements
    ]
    out = compare(FIX.result.model_copy(update={"measurements": ms}))

    assert (out["status"], out["failure_code"]) == ("inconclusive", "insufficient_evidence")


def test_verified_versus_rejected_is_a_changed_verdict() -> None:
    out = compare(with_verdict(FIX.result, "rejected", "no_improvement"))

    assert (out["status"], out["failure_code"]) == ("not_reproduced", "verdict_changed")


def test_an_inconclusive_side_is_verdict_inconclusive() -> None:
    out = compare(with_verdict(FIX.result, "inconclusive", "effect_not_significant"))

    assert (out["status"], out["failure_code"]) == ("inconclusive", "verdict_inconclusive")


def test_opposite_improvement_directions_are_reversed() -> None:
    stats = [s.model_copy(update={"ci_low": 0.5, "ci_high": 0.8}) for s in FIX.result.stats]
    replay = with_verdict(
        FIX.result.model_copy(update={"stats": stats}), "inconclusive", "insufficient_evidence"
    )

    out = compare(replay)

    assert (out["status"], out["failure_code"]) == ("not_reproduced", "direction_reversed")


def test_a_different_winner_is_not_reproduced_even_if_pairs_agree() -> None:
    out = compare(FIX.result.model_copy(update={"tournament": []}))

    assert {p["status"] for p in out["pairs"]} == {"reproduced"}
    assert (out["status"], out["failure_code"]) == ("not_reproduced", "winner_changed")


def test_changed_workload_data_is_not_replayable() -> None:
    env = FIX.environment.model_copy(update={"workload_data_digest": "sha256:other"})

    out = compare(FIX.result, replay_env=env)

    assert (out["status"], out["failure_code"]) == ("not_replayable", "workload_snapshot_changed")


def test_ddl_that_failed_only_in_the_replay_fails_the_attempt() -> None:
    builds = [BuildResult(arm=ARM, ok=False, reason="ddl_failed", detail="42P07")]
    out = compare(FIX.result.model_copy(update={"builds": builds}))

    assert (out["status"], out["failure_code"]) == ("failed", "ddl_failed")


@pytest.mark.parametrize(
    ("field", "value"),
    [("container_runtime", "docker-network"), ("cpu_count", 64), ("sandbox_image_digest", "x")],
)
def test_material_difference_is_cross_environment_with_the_same_algorithm(
    field: str, value: Any
) -> None:
    env = FIX.environment.model_copy(update={field: value})

    out = compare(FIX.result, replay_env=env)

    assert out["comparison_mode"] == "cross_environment"
    assert out["status"] == "reproduced"  # stored status; the UI words it differently
    assert [d["field"] for d in out["environment"]["differences"]] == [field]


def test_engine_version_difference_is_material() -> None:
    out = compare(FIX.result, replay_engine="bench@2")

    assert out["comparison_mode"] == "cross_environment"
    assert any(d["field"] == "benchmark_engine_version" for d in out["environment"]["differences"])


def test_minor_differences_keep_same_environment() -> None:
    env = FIX.environment.model_copy(
        update={"os": "Linux 6.1", "pg_version": FIX.environment.pg_version[:-1] + "9"}
    )
    diffs = classify_environment(
        FIX.environment, env, original_engine="bench@1", replay_engine="bench@1"
    )

    assert {d["class"] for d in diffs} == {"minor"}
    assert compare(FIX.result, replay_env=env)["comparison_mode"] == "same_environment"


def test_comparison_is_deterministic_and_records_its_config() -> None:
    replay = scaled(FIX.result, ARM, 1.1)
    first, second = compare(replay), compare(replay)

    assert first == second
    assert first["config"]["margin"] == 1.25
    assert first["config"]["resamples"] == 400
    assert len(first["limitations"]) == 4
