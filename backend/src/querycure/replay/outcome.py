"""Experiment replay run outcome (REPLAY_OUTCOME_AUDIT §12.3, §13). Pure and deterministic.

A replay re-measures one source experiment. It can confirm what its source investigation
sealed, but never more: it runs no auditor, replication or materiality gate, so its own
engine winner is not an input. Rules are evaluated in order; the first match wins.

    1  no comparison                             -> inconclusive   comparison_missing
    2  comparison failed (execution)             -> failed         comparison_failed
    3  no snapshot                               -> inconclusive   source_snapshot_missing
    4  comparison is of another experiment       -> inconclusive   source_snapshot_mismatch
    5  comparison not `reproduced`               -> inconclusive   comparison_<status>
    6  not same_environment                      -> inconclusive   cross_environment
    7  source is itself a replay                 -> inconclusive   source_is_replay
    8  source did not complete with an outcome   -> inconclusive   source_not_completed
    9  source verified_recommendation:
         recommendation missing or unmeasured -> inconclusive  source_recommendation_missing
         noise warning                        -> inconclusive  source_noise_warning
         measured by another experiment       -> inconclusive  recommendation_from_other_experiment
         candidate absent from the comparison -> inconclusive  recommended_candidate_not_compared
         else                                 -> verified_recommendation
                                                               reproduced_source_recommendation
    10 source no_action_needed                   -> no_action_needed  reproduced_source_no_action
    11 otherwise                                 -> inconclusive   source_not_verified

Not yet called by `experiment_replay._close` (activation is a separate, approved step).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from querycure.domain.runs import RunKind, RunOutcome, RunStatus
from querycure.replay.source_snapshot import ReplaySourceSnapshot

COMPARISON_STATUSES = (
    "reproduced",
    "reproduced_with_drift",
    "inconclusive",
    "not_reproduced",
    "not_replayable",
    "failed",
)
REPRODUCING_BASES = frozenset({"reproduced_source_recommendation", "reproduced_source_no_action"})
BASIS_CODES = frozenset(
    {
        "comparison_missing",
        "comparison_failed",
        "comparison_unrecognized",
        "source_snapshot_missing",
        "source_snapshot_mismatch",
        *(f"comparison_{s}" for s in COMPARISON_STATUSES if s not in ("reproduced", "failed")),
        "cross_environment",
        "source_is_replay",
        "source_not_completed",
        "source_recommendation_missing",
        "source_noise_warning",
        "recommendation_from_other_experiment",
        "recommended_candidate_not_compared",
        "source_not_verified",
        *REPRODUCING_BASES,
    }
)


@dataclass(frozen=True)
class ReplayClassification:
    run_status: RunStatus
    outcome: RunOutcome | None
    basis: str
    source_outcome: RunOutcome | None
    comparison_status: str | None
    comparison_mode: str | None

    @property
    def claims_reproduction(self) -> bool:
        """Whether the replay may say it reproduced its source's conclusion."""
        return self.basis in REPRODUCING_BASES

    def as_basis(self) -> dict[str, Any]:
        return {
            "code": self.basis,
            "source_outcome": None if self.source_outcome is None else self.source_outcome.value,
            "comparison_status": self.comparison_status,
            "comparison_mode": self.comparison_mode,
        }


def classify_replay_outcome(
    snapshot: ReplaySourceSnapshot | None, comparison: Mapping[str, Any] | None
) -> ReplayClassification:
    status = None if comparison is None else comparison.get("status")
    mode = None if comparison is None else comparison.get("comparison_mode")
    source_outcome = None if snapshot is None else snapshot.source_outcome

    def done(basis: str, outcome: RunOutcome = RunOutcome.INCONCLUSIVE) -> ReplayClassification:
        return ReplayClassification(
            RunStatus.COMPLETED, outcome, basis, source_outcome, status, mode
        )

    if comparison is None:
        return done("comparison_missing")
    if status == "failed":
        return ReplayClassification(
            RunStatus.FAILED, None, "comparison_failed", source_outcome, status, mode
        )
    if snapshot is None:
        return done("source_snapshot_missing")
    if comparison.get("original_experiment_id") != snapshot.source_experiment_id:
        return done("source_snapshot_mismatch")
    if status not in COMPARISON_STATUSES:
        return done("comparison_unrecognized")
    if status != "reproduced":
        return done(f"comparison_{status}")
    if mode != "same_environment":
        return done("cross_environment")
    if snapshot.source_run_kind is RunKind.EXPERIMENT_REPLAY:
        return done("source_is_replay")
    if source_outcome is None or snapshot.source_final_status != RunStatus.COMPLETED.value:
        return done("source_not_completed")
    if source_outcome is RunOutcome.VERIFIED_RECOMMENDATION:
        rec = snapshot.source_recommendation
        if (
            rec is None
            or rec.status not in ("verified", "verified_with_noise_warning")
            or rec.candidate_key is None
            or rec.measured_result_sha256 is None
        ):
            return done("source_recommendation_missing")
        if rec.status != "verified":
            return done("source_noise_warning")
        if rec.measured_result_sha256 != snapshot.source_experiment_result_sha256:
            return done("recommendation_from_other_experiment")
        pairs = [p for p in comparison.get("pairs") or [] if p.get("arm") == rec.candidate_key]
        if not pairs or any(p.get("status") != "reproduced" for p in pairs):
            return done("recommended_candidate_not_compared")
        return done("reproduced_source_recommendation", RunOutcome.VERIFIED_RECOMMENDATION)
    if source_outcome is RunOutcome.NO_ACTION_NEEDED:
        return done("reproduced_source_no_action", RunOutcome.NO_ACTION_NEEDED)
    return done("source_not_verified")
