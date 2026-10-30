"""report-builder@2 (REPLAY_ENGINE §7, REPLAY_OUTCOME_AUDIT §12.3 to §13.3): report schema 2.

Wraps the frozen `report-builder@1` and adds `recommendation.origin` (`run` | `source_run`).
Every other report is v1 plus those three fields. An experiment replay also gets
`replay_result`, its own headline and next steps, and a recommendation that is either the
source run's (only when the sealed basis says the replay reproduced it) or none:

- The decision is read, never made: `run.concluded.replay_basis` holds the classifier's
  sealed result (`replay/outcome.py`). Titles, headlines and claims are table lookups keyed
  by its code. The replay's own engine winner is shown as a labelled measurement only.
- Records that contradict the basis (a favourable outcome without the reproducing basis, a
  basis that disagrees with the comparison or snapshot, an unknown code) raise
  `ReportContractError`, so a contradictory report is never sealed.

Pure: same inputs, same bytes. Every number in text sits on a line with a provenance label.
"""

from typing import Any

from querycure.reports.builders import v1
from querycure.reports.inputs import ReportInputs

BUILDER_VERSION = "report-builder@2"
REPORT_SCHEMA_VERSION = 2
REPLAY = "experiment_replay"
PAIR_STATUSES = ("reproduced", "reproduced_with_drift", "inconclusive", "not_reproduced")
MEASUREMENT_LABEL = "replay measurement, not a verification"
BASIS_KEYS = frozenset({"code", "source_outcome", "comparison_status", "comparison_mode"})
RECOMMENDATION_KEYS = (
    "status", "candidate_key", "kind", "ddl", "query_sql", "primary_measurement", "scope"
)  # fmt: skip

# Mirrors replay/outcome.py (the classifier). Kept here so the frozen builder never imports
# a module that can change: a new basis code is a new builder version.
REPRODUCING = frozenset({"reproduced_source_recommendation", "reproduced_source_no_action"})
UNAVAILABLE = frozenset(
    {
        "comparison_missing",
        "comparison_not_replayable",
        "comparison_unrecognized",
        "source_snapshot_missing",
        "source_snapshot_mismatch",
    }
)
NOT_CHECKED = frozenset(
    {
        "source_recommendation_missing",
        "recommendation_from_other_experiment",
        "recommended_candidate_not_compared",
    }
)
REMEASUREMENT = frozenset({"source_not_verified", "source_not_completed", "source_is_replay"})
# Codes the classifier reaches only after `comparison.status == "reproduced"` (rule 5) and,
# all but the first, only in the same environment (rule 6).
AFTER_REPRODUCED = frozenset(
    {"cross_environment", "source_noise_warning"} | REPRODUCING | NOT_CHECKED | REMEASUREMENT
)
BASIS_CODES = frozenset(
    {
        "comparison_failed",
        "comparison_reproduced_with_drift",
        "comparison_inconclusive",
        "comparison_not_reproduced",
    }
    | UNAVAILABLE
    | AFTER_REPRODUCED
)

RESULT = {
    "reproduced_source_recommendation": "original_reproduced",
    "reproduced_source_no_action": "original_reproduced",
    "comparison_reproduced_with_drift": "performance_drift",
    "comparison_not_reproduced": "not_reproduced",
    "comparison_inconclusive": "inconclusive",
    "cross_environment": "not_comparable",
    "source_noise_warning": "not_confirmed",
    "comparison_failed": "failed",
    **{c: "unavailable" for c in UNAVAILABLE},
    **{c: "not_confirmed" for c in NOT_CHECKED | REMEASUREMENT},
}
TITLE = {
    "reproduced_source_recommendation": "Original recommendation reproduced",
    "reproduced_source_no_action": "Original no-action conclusion reproduced",
    "comparison_reproduced_with_drift": "Performance drift detected",
    "comparison_not_reproduced": "Original result not reproduced",
    "comparison_inconclusive": "Replay comparison inconclusive",
    "cross_environment": "Results not directly comparable",
    "source_noise_warning": "Noise-warning recommendation not confirmed",
    "comparison_failed": "Replay failed",
    **{c: "No comparison with the original was possible" for c in UNAVAILABLE},
    **{c: "Original recommendation not checked by this replay" for c in NOT_CHECKED},
    **{c: "Re-measurement only" for c in REMEASUREMENT},
}
HEADLINE = {
    "reproduced_source_recommendation": (
        "A new sandbox measurement of the same experiment matched the original within the "
        "equivalence margin. The recommendation was verified by the source investigation; "
        "this replay re-measured one experiment and verified nothing new."
    ),
    "reproduced_source_no_action": (
        "A new sandbox measurement of the same experiment matched the source investigation, "
        "which concluded that no change was needed."
    ),
    "comparison_reproduced_with_drift": (
        "Correctness held, but the speed-up changed beyond the equivalence margin, so the "
        "original result is not confirmed."
    ),
    "comparison_not_reproduced": "{reason}. The original result is not confirmed by this replay.",
    "comparison_inconclusive": (
        "the original result was neither confirmed nor contradicted ({reason})."
    ),
    "cross_environment": (
        "the environments differ in material fields, so this is not a reproduction of the "
        "original setup."
    ),
    "source_noise_warning": (
        "one experiment cannot repeat the original's agreement across three independent "
        "experiments."
    ),
    "source_recommendation_missing": (
        "the source report does not name a measured recommendation to compare."
    ),
    "recommendation_from_other_experiment": (
        "it rests on a different experiment of the source investigation than the one "
        "re-measured here."
    ),
    "recommended_candidate_not_compared": (
        "the recommended candidate is not among the reproduced comparison pairs."
    ),
    "source_not_verified": (
        "the original investigation verified no recommendation, and a replay cannot create one."
    ),
    "source_not_completed": (
        "the original run did not complete, so there is no conclusion to confirm."
    ),
    "source_is_replay": (
        "this replays another replay; only an investigation's own outcome can be confirmed."
    ),
    **{c: "{reason}." for c in UNAVAILABLE},
    "comparison_failed": "{reason}: nothing was compared with the original.",
}
EXPLANATION = {
    "original_reproduced": (
        "The replay confirms what the source investigation concluded, within its scope: one "
        "experiment, re-measured. It ran no diagnosis, candidate generation, auditor, "
        "replication or materiality check."
    ),
    "performance_drift": (
        "The direction and correctness held; the size of the effect did not, so the original "
        "claim is not confirmed."
    ),
    "not_reproduced": (
        "The new measurement contradicts the original. Treat the original result with caution."
    ),
    "inconclusive": ("Inconclusive is not a rejection: a quieter host or more samples may decide."),
    "not_comparable": (
        "Ratios measured in different environments may not transfer, so the replay can only "
        "show consistency across environments."
    ),
    "not_confirmed": (
        "The new measurement is shown for reference; it cannot confirm the original recommendation."
    ),
    "unavailable": (
        "The new measurement is sealed, but the comparison with the original was not "
        "possible or not recorded."
    ),
    "failed": "Nothing was compared with the original.",
    "cancelled": "Nothing was compared with the original.",
    "unclassified": (
        "No replay classification was recorded for this run, so it cannot confirm anything."
    ),
}
COMPARISON_REASON = {
    "insufficient_evidence": "too few samples, or measurements too noisy to decide",
    "drift_undetermined": "the drift interval overlaps the equivalence margin",
    "verdict_inconclusive": "a verdict was inconclusive in the original or the replay",
    "verdict_changed": "the engine verdict changed",
    "direction_reversed": "the speed-up reversed direction",
    "result_fingerprint_changed": "the result rows changed",
    "winner_changed": "a different candidate won the replay tournament",
    "workload_snapshot_changed": "the workload data changed",
    "unsupported_row_profile": "the row profile changed",
    "ddl_failed": "a change could not be applied in the replay sandbox",
}
UNAVAILABLE_REASON = {
    "comparison_missing": "no comparison was recorded",
    "comparison_unrecognized": "the comparison status is not recognised",
    "source_snapshot_missing": "the source snapshot is missing",
    "source_snapshot_mismatch": "the comparison is of a different experiment than the snapshot",
}
NEXT_STEPS = {
    "original_reproduced": [
        "Review the original recommendation's exact SQL and test it on a staging copy of your "
        "own data and workload; a sandbox reproduction is not a guarantee for your workload."
    ],
    "performance_drift": [
        "Replay again on a quieter host before relying on the size of the original effect."
    ],
    "not_reproduced": [
        "Treat the original result with caution; investigate why it changed before acting on it."
    ],
    "inconclusive": [
        "Replay again on a quieter host or with more samples; inconclusive is not a rejection."
    ],
    "not_comparable": [
        "Replay in the original environment to check reproduction of the original setup."
    ],
    "unavailable": ["Start a new replay once the comparison precondition holds."],
    "failed": ["Start a new replay once the failure is resolved."],
    "cancelled": ["Start a new replay to compare with the original."],
    "unclassified": ["Start a new replay to compare with the original."],
}
NOT_CONFIRMED_STEPS = {
    "source_noise_warning": [
        "The original noise-warning verification needs replicates that a replay does not run."
    ],
    "recommendation_from_other_experiment": [
        "Replay the recommendation's own experiment to check it."
    ],
    "recommended_candidate_not_compared": [
        "Replay the recommendation's own experiment to check it."
    ],
    "source_recommendation_missing": ["Review the source investigation's report."],
    "source_not_verified": ["Start a new investigation run to verify a recommendation."],
    "source_not_completed": ["Start a new investigation run to reach a conclusion."],
    "source_is_replay": ["Replay the original investigation's experiment instead."],
}


class ReportContractError(ValueError):
    """The sealed records of a replay contradict its classification basis."""


def _implied(code: str) -> tuple[str, str | None]:
    if code == "comparison_failed":
        return "failed", None
    if code == "reproduced_source_recommendation":
        return "completed", "verified_recommendation"
    if code == "reproduced_source_no_action":
        return "completed", "no_action_needed"
    return "completed", "inconclusive"


def _sealed_basis(
    conclusion: dict[str, Any],
    comparison: dict[str, Any] | None,
    snapshot: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """The sealed basis, checked against every record it was derived from."""
    if "replay_basis" not in conclusion:
        return None
    basis = conclusion["replay_basis"]
    if (
        not isinstance(basis, dict)
        or set(basis) != BASIS_KEYS
        or basis["code"] not in (BASIS_CODES)
    ):
        raise ReportContractError(f"replay basis is malformed: {basis!r}"[:200])
    code = basis["code"]
    if (conclusion.get("final_status"), conclusion.get("outcome")) != _implied(code):
        raise ReportContractError(f"sealed outcome contradicts replay basis {code}")
    status = None if comparison is None else comparison.get("status")
    mode = None if comparison is None else comparison.get("comparison_mode")
    if (basis["comparison_status"], basis["comparison_mode"]) != (status, mode):
        raise ReportContractError("replay basis names another comparison")
    source_outcome = None if snapshot is None else snapshot.get("source_outcome")
    if basis["source_outcome"] != source_outcome:
        raise ReportContractError("replay basis names another source outcome")
    if (code == "comparison_missing") != (comparison is None):
        raise ReportContractError("replay basis disagrees with the recorded comparison")
    named_status = code.startswith("comparison_") and code not in UNAVAILABLE | {
        "comparison_failed"
    }
    if named_status and code != f"comparison_{status}":
        raise ReportContractError("replay basis disagrees with the comparison status")
    if code in AFTER_REPRODUCED and status != "reproduced":
        raise ReportContractError("replay basis requires a reproduced comparison")
    if code in AFTER_REPRODUCED - {"cross_environment"} and mode != "same_environment":
        raise ReportContractError("replay basis requires a same-environment comparison")
    if code == "source_snapshot_missing" and snapshot is not None:
        raise ReportContractError("replay basis says the snapshot is missing")
    needs_snapshot = code not in {"comparison_missing", "comparison_failed",
                                  "source_snapshot_missing"}  # fmt: skip
    if needs_snapshot and snapshot is None:
        raise ReportContractError(f"replay basis {code} requires a source snapshot")
    if (
        code == "source_snapshot_mismatch"
        and snapshot is not None
        and comparison is not None
        and comparison.get("original_experiment_id") == snapshot.get("source_experiment_id")
    ):
        raise ReportContractError("replay basis reports a mismatch that does not exist")
    if code == "reproduced_source_recommendation":
        _check_reproduced(snapshot)
    return basis


def _measured_sha(rec: dict[str, Any] | None) -> str | None:
    source = ((rec or {}).get("primary_measurement") or {}).get("source")
    sha = source.get("artifact_sha256") if isinstance(source, dict) else None
    return sha if isinstance(sha, str) and sha else None


def _check_reproduced(snapshot: dict[str, Any] | None) -> None:
    """The claim needs the source's verified recommendation, measured by this experiment."""
    rec = (snapshot or {}).get("source_recommendation")
    if (
        snapshot is None
        or snapshot.get("source_run_kind") == REPLAY
        or snapshot.get("source_outcome") != "verified_recommendation"
        or not isinstance(rec, dict)
        or rec.get("status") != "verified"
        or rec.get("candidate_key") is None
        or _measured_sha(rec) != snapshot.get("source_experiment_result_sha256")
    ):
        raise ReportContractError("reproduction claimed without a matching verified source")


def _reason(code: str | None, comparison: dict[str, Any] | None, error: Any) -> str:
    if code in UNAVAILABLE_REASON:
        return UNAVAILABLE_REASON[code]
    failure = (comparison or {}).get("failure_code")
    if code == "comparison_failed" or code is None:
        failure = failure or (error or {}).get("code") or "unknown"
        return f"Replay failed ({failure})"
    return COMPARISON_REASON.get(failure or "", failure or "no reason was recorded")


def _headline(title: str, code: str | None, comparison: Any, error: Any, result: str) -> str:
    if code is None:
        tail = {
            "failed": f"{_reason(None, comparison, error)}: nothing was compared with the "
            "original.",
            "cancelled": "the run stopped before a comparison was made.",
            "unclassified": (
                "no replay classification was recorded, so the original result is not confirmed."
            ),
        }[result]
        return tail if result == "failed" else f"{title}: {tail}"
    text = HEADLINE[code].format(reason=_reason(code, comparison, error))
    if code == "comparison_failed":
        return text
    if code == "comparison_not_reproduced":
        return f"{title}: {text}"
    joiner = ". " if code in REPRODUCING or code == "comparison_reproduced_with_drift" else ": "
    return f"{title}{joiner}{text}"


def _performance(comparison: dict[str, Any] | None) -> bool | None:
    status = (comparison or {}).get("status")
    if status == "reproduced":
        return True
    if status == "reproduced_with_drift" or (
        status == "not_reproduced"
        and (comparison or {}).get("failure_code")
        in ("verdict_changed", "direction_reversed", "winner_changed")
    ):
        return False
    return None


def _replay_result(
    report: dict[str, Any], inputs: ReportInputs, basis: dict[str, Any] | None
) -> dict[str, Any]:
    conclusion = inputs.conclusion or {}
    final_status = conclusion.get("final_status")
    comparison, snapshot = inputs.comparison, inputs.replay_source
    code = None if basis is None else basis["code"]
    if code is not None:
        result, title = RESULT[code], TITLE[code]
    elif final_status == "failed":
        result, title = "failed", "Replay failed"
    elif final_status == "cancelled":
        result, title = "cancelled", "Replay cancelled"
    elif conclusion.get("outcome") in (None, "inconclusive"):
        result, title = "unclassified", "Replay not classified"
    else:
        raise ReportContractError("a favourable replay outcome was sealed without a basis")
    pairs = (comparison or {}).get("pairs") or []
    replay_exp = next((e for e in report["rounds"] if e["experiment"]), None)
    replay_exp = None if replay_exp is None else replay_exp["experiment"]
    rec = None if snapshot is None else snapshot.get("source_recommendation")
    source_rec = (
        None
        if not isinstance(rec, dict) or rec.get("candidate_key") is None
        else {**rec, "provenance": "source_run"}
    )
    measured = _measured_sha(rec)
    differences = ((comparison or {}).get("environment") or {}).get("differences") or []
    margin = ((comparison or {}).get("config") or {}).get("margin")
    return {
        "result": result,
        "title": title,
        "claims_reproduction": code in REPRODUCING,
        "original_reproduced": code in REPRODUCING,
        "basis": basis,
        "explanation": EXPLANATION[result],
        "failure_code": (comparison or {}).get("failure_code")
        or (conclusion.get("error") or {}).get("code"),
        "comparison_status": None if comparison is None else comparison.get("status"),
        "comparison_failure_code": None if comparison is None else comparison.get("failure_code"),
        "comparison_mode": None if comparison is None else comparison.get("comparison_mode"),
        "margin": margin,
        "correctness_reproduced": None
        if not pairs
        else all(p.get("code") != "result_fingerprint_changed" for p in pairs),
        "performance_reproduced": _performance(comparison),
        "material_drift": None
        if not pairs
        else any(p.get("status") == "reproduced_with_drift" for p in pairs),
        "environment_comparable": None
        if comparison is None or comparison.get("status") == "not_replayable"
        else comparison.get("comparison_mode") == "same_environment",
        "material_differences": sorted(
            d["field"] for d in differences if d.get("class") in ("material", "precondition")
        ),
        "experiment_match": {
            "replayed_experiment_id": None
            if snapshot is None
            else snapshot.get("source_experiment_id"),
            "replayed_result_sha256": None
            if snapshot is None
            else snapshot.get("source_experiment_result_sha256"),
            "recommendation_result_sha256": measured,
            "matches": None
            if snapshot is None or measured is None
            else measured == snapshot.get("source_experiment_result_sha256"),
        },
        "source": None
        if snapshot is None
        else {
            "run_id": snapshot.get("source_run_id"),
            "run_kind": snapshot.get("source_run_kind"),
            "experiment_id": snapshot.get("source_experiment_id"),
            "final_status": snapshot.get("source_final_status"),
            "outcome": snapshot.get("source_outcome"),
            "manifest_sha256": snapshot.get("source_manifest_sha256"),
            "report_json_sha256": snapshot.get("source_report_json_sha256"),
            "builder_version": snapshot.get("source_builder_version"),
            "provenance": "source_run",
        },
        "source_recommendation": source_rec,
        "replay_measurement": {
            "engine_winner": None if replay_exp is None else replay_exp["winner"],
            "provenance": None if replay_exp is None else replay_exp["provenance"],
            "label": MEASUREMENT_LABEL,
        },
        "snapshot_error": inputs.replay_source_error,
    }


def _replay(report: dict[str, Any], inputs: ReportInputs) -> dict[str, Any]:
    conclusion = inputs.conclusion or {}
    basis = _sealed_basis(conclusion, inputs.comparison, inputs.replay_source)
    rr = _replay_result(report, inputs, basis)
    code = None if basis is None else basis["code"]
    none = {
        "status": "none",
        "candidate_key": None,
        "kind": None,
        "ddl": [],
        "query_sql": None,
        "primary_measurement": None,
        "scope": report["recommendation"]["scope"],
        "origin": "run",
    }
    recommendation = none
    if code == "reproduced_source_recommendation":
        src = (inputs.replay_source or {}).get("source_recommendation") or {}
        recommendation = {
            **{k: src[k] for k in RECOMMENDATION_KEYS},
            "origin": "source_run",
            "source_run_id": (inputs.replay_source or {}).get("source_run_id"),
        }
    limitations = [
        *report["limitations"],
        "A replay re-measures one experiment. It runs no diagnosis, candidate generation, "
        "auditor, replication or materiality check, so it can at most reproduce what the "
        "source investigation verified.",
    ]
    if inputs.replay_source_error:
        limitations.append(
            f"The source snapshot could not be read ({inputs.replay_source_error}); nothing "
            "about the source run is confirmed."
        )
    next_steps = NOT_CONFIRMED_STEPS.get(code or "") or NEXT_STEPS[rr["result"]]
    replay = report["replay"]
    snap = inputs.replay_source
    if snap is not None:
        # From the sealed snapshot, not v1's lookup of the source experiment's row, so a
        # rebuild never depends on the source run still existing.
        replay = {
            **replay,
            "replay_of": {
                "experiment_id": snap["source_experiment_id"],
                "run_id": snap["source_run_id"],
            },
        }
    return {
        **report,
        "replay": replay,
        "headline": _headline(
            rr["title"], code, inputs.comparison, conclusion.get("error"), rr["result"]
        ),
        "recommendation": recommendation,
        "limitations": limitations,
        "next_steps": list(next_steps),
        "replay_result": rr,
    }


def build_report(
    inputs: ReportInputs, *, finalized_at: str, cutoff_seq: int, events_digest: str
) -> dict[str, Any]:
    report = v1.build_report(
        inputs, finalized_at=finalized_at, cutoff_seq=cutoff_seq, events_digest=events_digest
    )
    report = {**report, "schema_version": REPORT_SCHEMA_VERSION, "builder_version": BUILDER_VERSION}
    if inputs.run["kind"] != REPLAY:
        return {**report, "recommendation": {**report["recommendation"], "origin": "run"}}
    return _replay(report, inputs)
