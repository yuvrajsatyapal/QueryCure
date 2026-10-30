"""Experiment replay run outcome classifier (REPLAY_OUTCOME_AUDIT §12.3, §13).

Pure function of the source snapshot and the stored comparison. Not yet called by `_close`.
"""

import itertools
from typing import Any

import pytest

from querycure.domain.runs import RunKind, RunOutcome, RunStatus
from querycure.replay.outcome import (
    BASIS_CODES,
    REPRODUCING_BASES,
    ReplayClassification,
    classify_replay_outcome,
)
from querycure.replay.source_snapshot import ReplaySourceSnapshot, SourceRecommendation

SRC_RUN = "00000000-0000-4000-8000-000000000001"
SRC_EXP = "00000000-0000-4000-8000-0000000000e1"
OTHER_EXP = "00000000-0000-4000-8000-0000000000e2"
RESULT_SHA = "a" * 64
OTHER_SHA = "b" * 64


def measurement(sha: str | None = RESULT_SHA, arm: str = "c1") -> dict[str, Any]:
    return {
        "arm": arm,
        "param_set": "default",
        "speedup": 3.0,
        "ci_low": 2.5,
        "ci_high": 3.5,
        "provenance": "measured",
        "evidence_id": "ev_benchmark_metric_1",
        "source": None if sha is None else {"artifact_sha256": sha, "pointer": "/stats/0"},
    }


def rec(
    status: str = "verified", *, sha: str | None = RESULT_SHA, key: str | None = "c1"
) -> SourceRecommendation:
    return SourceRecommendation(
        status=status,
        candidate_key=key,
        kind="create_index",
        ddl=["CREATE INDEX i ON t (a)"],
        query_sql=None,
        primary_measurement=None if sha is None and key is None else measurement(sha),
        scope="sandbox",
    )


def snap(
    *,
    outcome: RunOutcome | None = RunOutcome.VERIFIED_RECOMMENDATION,
    final_status: str = "completed",
    kind: RunKind = RunKind.INITIAL,
    recommendation: SourceRecommendation | None = None,
    no_rec: bool = False,
    experiment_id: str = SRC_EXP,
) -> ReplaySourceSnapshot:
    if recommendation is None and not no_rec and outcome is RunOutcome.VERIFIED_RECOMMENDATION:
        recommendation = rec()
    return ReplaySourceSnapshot(
        schema_version=1,
        source_run_id=SRC_RUN,
        source_run_kind=kind,
        source_experiment_id=experiment_id,
        source_experiment_result_sha256=RESULT_SHA,
        source_experiment_environment_digest="sha256:" + "e" * 64,
        source_manifest_sha256="c" * 64,
        source_report_json_sha256="d" * 64,
        source_builder_version="report-builder@1",
        source_final_status=final_status,
        source_outcome=outcome,
        source_recommendation=recommendation,
    )


def comp(
    status: str = "reproduced",
    *,
    mode: str = "same_environment",
    original: str = SRC_EXP,
    arms: tuple[str, ...] = ("c1",),
    code: str | None = None,
) -> dict[str, Any]:
    pair_status = status if status in ("reproduced", "reproduced_with_drift") else "inconclusive"
    return {
        "status": status,
        "failure_code": code,
        "comparison_mode": mode,
        "original_experiment_id": original,
        "replay_experiment_id": "00000000-0000-4000-8000-0000000000f1",
        "pairs": [{"arm": a, "param_set": "default", "status": pair_status} for a in arms],
        "winner": {"original": arms[0] if arms else None, "replay": "c1"},
    }


VERIFIED = RunOutcome.VERIFIED_RECOMMENDATION
INCONCLUSIVE = RunOutcome.INCONCLUSIVE
NO_ACTION = RunOutcome.NO_ACTION_NEEDED
DONE = RunStatus.COMPLETED


# One row per §12.3 rule / decision-table case. Expected (run status, outcome, basis).
CASES: list[tuple[str, ReplaySourceSnapshot | None, dict[str, Any] | None, tuple[Any, ...]]] = [
    (
        "verified original, same-env reproduced, matching experiment (row 1)",
        snap(),
        comp(),
        (DONE, VERIFIED, "reproduced_source_recommendation"),
    ),
    (
        "verified original, material drift (row 2, D1)",
        snap(),
        comp("reproduced_with_drift"),
        (DONE, INCONCLUSIVE, "comparison_reproduced_with_drift"),
    ),
    (
        "verified original, not reproduced (row 3, D2)",
        snap(),
        comp("not_reproduced", code="verdict_changed"),
        (DONE, INCONCLUSIVE, "comparison_not_reproduced"),
    ),
    (
        "verified original, winner changed (row 3, D2)",
        snap(),
        comp("not_reproduced", code="winner_changed"),
        (DONE, INCONCLUSIVE, "comparison_not_reproduced"),
    ),
    (
        "verified original, inconclusive comparison (row 4)",
        snap(),
        comp("inconclusive", code="insufficient_evidence"),
        (DONE, INCONCLUSIVE, "comparison_inconclusive"),
    ),
    (
        "verified original, cross-environment reproduced (row 5, D9)",
        snap(),
        comp(mode="cross_environment"),
        (DONE, INCONCLUSIVE, "cross_environment"),
    ),
    (
        "verified original with noise warning (row 6, D8)",
        snap(recommendation=rec("verified_with_noise_warning")),
        comp(),
        (DONE, INCONCLUSIVE, "source_noise_warning"),
    ),
    (
        "verified original, recommendation measured by another experiment (row 7, D11)",
        snap(recommendation=rec(sha=OTHER_SHA)),
        comp(),
        (DONE, INCONCLUSIVE, "recommendation_from_other_experiment"),
    ),
    (
        "inconclusive original, replay engine has a winner (row 8, D4)",
        snap(outcome=INCONCLUSIVE),
        comp(),
        (DONE, INCONCLUSIVE, "source_not_verified"),
    ),
    (
        "inconclusive original, not reproduced (row 8)",
        snap(outcome=INCONCLUSIVE),
        comp("not_reproduced", code="verdict_changed"),
        (DONE, INCONCLUSIVE, "comparison_not_reproduced"),
    ),
    (
        "unverified-recommendations original, reproduced (rule 10)",
        snap(outcome=RunOutcome.UNVERIFIED_RECOMMENDATIONS),
        comp(),
        (DONE, INCONCLUSIVE, "source_not_verified"),
    ),
    (
        "no-action original, same-env reproduced (row 9, D7)",
        snap(outcome=NO_ACTION),
        comp(),
        (DONE, NO_ACTION, "reproduced_source_no_action"),
    ),
    (
        "no-action original, cross-environment (row 9, D7 + D9)",
        snap(outcome=NO_ACTION),
        comp(mode="cross_environment"),
        (DONE, INCONCLUSIVE, "cross_environment"),
    ),
    (
        "no-action original, drift (row 9, D7 + D1)",
        snap(outcome=NO_ACTION),
        comp("reproduced_with_drift"),
        (DONE, INCONCLUSIVE, "comparison_reproduced_with_drift"),
    ),
    (
        "failed original (row 10, D12)",
        snap(outcome=None, final_status="failed"),
        comp(),
        (DONE, INCONCLUSIVE, "source_not_completed"),
    ),
    (
        "cancelled original (row 10, D12)",
        snap(outcome=None, final_status="cancelled"),
        comp(),
        (DONE, INCONCLUSIVE, "source_not_completed"),
    ),
    (
        "replay-of-replay source that sealed verified (row 11, D10)",
        snap(kind=RunKind.EXPERIMENT_REPLAY, no_rec=True),
        comp(),
        (DONE, INCONCLUSIVE, "source_is_replay"),
    ),
    (
        "replay-of-replay source with a recommendation (row 11, D10)",
        snap(kind=RunKind.EXPERIMENT_REPLAY),
        comp(),
        (DONE, INCONCLUSIVE, "source_is_replay"),
    ),
    (
        "reinvestigation source is an investigation (rule 8)",
        snap(kind=RunKind.REINVESTIGATION),
        comp(),
        (DONE, VERIFIED, "reproduced_source_recommendation"),
    ),
    (
        "comparison missing (row 14, D3)",
        snap(),
        None,
        (DONE, INCONCLUSIVE, "comparison_missing"),
    ),
    (
        "compare-time not_replayable (row 14, D3)",
        snap(),
        comp("not_replayable", code="workload_snapshot_changed", arms=()),
        (DONE, INCONCLUSIVE, "comparison_not_replayable"),
    ),
    (
        "snapshot missing (row 14, D3)",
        None,
        comp(),
        (DONE, INCONCLUSIVE, "source_snapshot_missing"),
    ),
    (
        "replay execution failure: DDL failed in the replay (row 15)",
        snap(),
        comp("failed", code="ddl_failed", arms=()),
        (RunStatus.FAILED, None, "comparison_failed"),
    ),
    (
        "comparison of a different source experiment (I14)",
        snap(),
        comp(original=OTHER_EXP),
        (DONE, INCONCLUSIVE, "source_snapshot_mismatch"),
    ),
    (
        "comparison without the original experiment id (I14)",
        snap(),
        {k: v for k, v in comp().items() if k != "original_experiment_id"},
        (DONE, INCONCLUSIVE, "source_snapshot_mismatch"),
    ),
    (
        "verified original without a recommendation (row 13, I14)",
        snap(no_rec=True),
        comp(),
        (DONE, INCONCLUSIVE, "source_recommendation_missing"),
    ),
    (
        "verified original, recommendation status none (row 13, I14)",
        snap(recommendation=rec("none", sha=None, key=None)),
        comp(),
        (DONE, INCONCLUSIVE, "source_recommendation_missing"),
    ),
    (
        "verified original, recommendation without a measured source (row 13, I14)",
        snap(recommendation=rec(sha=None)),
        comp(),
        (DONE, INCONCLUSIVE, "source_recommendation_missing"),
    ),
    (
        "verified original, recommended candidate not in the comparison (I14)",
        snap(recommendation=rec(key="c2")),
        comp(arms=("c1",)),
        (DONE, INCONCLUSIVE, "recommended_candidate_not_compared"),
    ),
    (
        "verified outcome on a non-completed source is inconsistent (I14)",
        snap(final_status="failed"),
        comp(),
        (DONE, INCONCLUSIVE, "source_not_completed"),
    ),
    (
        "unknown comparison status (I14)",
        snap(),
        comp("reproduced_maybe"),
        (DONE, INCONCLUSIVE, "comparison_unrecognized"),
    ),
    (
        "unknown comparison mode (I14)",
        snap(),
        comp(mode="somewhere_else"),
        (DONE, INCONCLUSIVE, "cross_environment"),
    ),
]


@pytest.mark.parametrize(
    ("snapshot", "comparison", "expected"), [c[1:] for c in CASES], ids=[c[0] for c in CASES]
)
def test_decision_table(
    snapshot: ReplaySourceSnapshot | None,
    comparison: dict[str, Any] | None,
    expected: tuple[Any, ...],
) -> None:
    got = classify_replay_outcome(snapshot, comparison)
    assert (got.run_status, got.outcome, got.basis) == expected
    assert got.basis in BASIS_CODES


def test_basis_records_the_inputs_it_decided_on() -> None:
    got = classify_replay_outcome(snap(), comp())
    assert got.as_basis() == {
        "code": "reproduced_source_recommendation",
        "source_outcome": "verified_recommendation",
        "comparison_status": "reproduced",
        "comparison_mode": "same_environment",
    }
    assert got.claims_reproduction
    missing = classify_replay_outcome(None, None)
    assert missing.as_basis() == {
        "code": "comparison_missing",
        "source_outcome": None,
        "comparison_status": None,
        "comparison_mode": None,
    }
    assert not missing.claims_reproduction


def test_replay_winner_is_not_an_input() -> None:
    """D4: the replay's own engine winner never changes the decision."""
    base = comp()
    for replay_winner in ("c1", "c2", None):
        for source in (snap(), snap(outcome=INCONCLUSIVE), snap(outcome=NO_ACTION)):
            c = {**base, "winner": {"original": None, "replay": replay_winner}}
            assert classify_replay_outcome(source, c) == classify_replay_outcome(source, base)


def test_classification_is_deterministic_and_does_not_mutate_inputs() -> None:
    s, c = snap(), comp()
    before = (s.model_dump(), repr(c))
    results = {classify_replay_outcome(s, c) for _ in range(5)}
    assert len(results) == 1
    assert (s.model_dump(), repr(c)) == before


# --- Invariants over the full input space -------------------------------------------------

STATUSES = (
    "reproduced",
    "reproduced_with_drift",
    "inconclusive",
    "not_reproduced",
    "not_replayable",
    "failed",
    "unknown",
)
MODES = ("same_environment", "cross_environment", "unknown")
OUTCOMES: tuple[RunOutcome | None, ...] = (None, *RunOutcome)
FINAL = ("completed", "failed", "cancelled")
RECS: tuple[SourceRecommendation | None, ...] = (
    None,
    rec(),
    rec("verified_with_noise_warning"),
    rec(sha=OTHER_SHA),
    rec(sha=None),
    rec(key="c2"),
    rec("none", sha=None, key=None),
    rec("unverified", sha=None, key=None),
)


def _space() -> list[tuple[ReplaySourceSnapshot | None, dict[str, Any] | None]]:
    out: list[tuple[ReplaySourceSnapshot | None, dict[str, Any] | None]] = []
    comparisons: list[dict[str, Any] | None] = [None]
    for status, mode, original in itertools.product(STATUSES, MODES, (SRC_EXP, OTHER_EXP)):
        comparisons.append(comp(status, mode=mode, original=original))
    snapshots: list[ReplaySourceSnapshot | None] = [None]
    for kind, outcome, final, r in itertools.product(RunKind, OUTCOMES, FINAL, RECS):
        snapshots.append(
            snap(kind=kind, outcome=outcome, final_status=final, recommendation=r, no_rec=r is None)
        )
    for s, c in itertools.product(snapshots, comparisons):
        out.append((s, c))
    return out


SPACE = _space()


def _results() -> list[
    tuple[ReplaySourceSnapshot | None, dict[str, Any] | None, ReplayClassification]
]:
    return [(s, c, classify_replay_outcome(s, c)) for s, c in SPACE]


RESULTS = _results()


def test_space_is_large() -> None:
    assert len(SPACE) > 10_000


def test_replay_never_upgrades_an_unverified_original() -> None:
    """I1 / I8: the outcome is the source's own outcome or inconclusive, never better."""
    for s, _c, r in RESULTS:
        if r.outcome is None or r.outcome is INCONCLUSIVE:
            continue
        assert s is not None
        assert r.outcome is s.source_outcome
        assert s.source_final_status == "completed"


def test_only_the_fully_eligible_case_verifies() -> None:
    """I7, I10 to I13: verified_recommendation needs every condition of rule 8 at once."""
    hits = 0
    for s, c, r in RESULTS:
        if r.outcome is not VERIFIED:
            continue
        hits += 1
        assert s is not None
        assert c is not None
        assert r.basis == "reproduced_source_recommendation"
        assert c["status"] == "reproduced"
        assert c["comparison_mode"] == "same_environment"
        assert c["original_experiment_id"] == s.source_experiment_id
        assert s.source_run_kind is not RunKind.EXPERIMENT_REPLAY
        assert s.source_outcome is VERIFIED
        assert s.source_final_status == "completed"
        assert s.source_recommendation is not None
        assert s.source_recommendation.status == "verified"
        assert s.source_recommendation.measured_result_sha256 == s.source_experiment_result_sha256
    assert hits > 0


def test_replay_of_replay_never_launders_verification() -> None:
    """I11."""
    for s, _c, r in RESULTS:
        if s is not None and s.source_run_kind is RunKind.EXPERIMENT_REPLAY:
            assert r.outcome in (None, INCONCLUSIVE)
            assert not r.claims_reproduction


def test_drift_and_environment_mismatch_never_reproduce() -> None:
    """D1 / I10."""
    for _s, c, r in RESULTS:
        if c is not None and (
            c["status"] != "reproduced" or c["comparison_mode"] != "same_environment"
        ):
            assert r.outcome in (None, INCONCLUSIVE)
            assert not r.claims_reproduction


def test_missing_provenance_never_defaults_to_verification() -> None:
    """I14."""
    for s, c, r in RESULTS:
        if s is None or c is None:
            assert r.outcome in (None, INCONCLUSIVE)
            assert not r.claims_reproduction
        rec_ = None if s is None else s.source_recommendation
        if rec_ is not None and rec_.measured_result_sha256 is None:
            assert r.outcome is not VERIFIED


def test_only_comparison_failure_fails_the_run() -> None:
    """Execution failures keep their failure; a completed replay always has an outcome."""
    for _s, c, r in RESULTS:
        if r.run_status is RunStatus.FAILED:
            assert c is not None
            assert c["status"] == "failed"
            assert r.outcome is None
        else:
            assert r.run_status is DONE
            assert r.outcome is not None


def test_claims_reproduction_matches_the_reproducing_bases() -> None:
    for _s, _c, r in RESULTS:
        assert r.claims_reproduction == (r.basis in REPRODUCING_BASES)
        assert r.basis in BASIS_CODES
