"""report-builder@2 + report-md@2 (REPLAY_OUTCOME_AUDIT §12.3 to §13.3, Workstream 5).

v2 wraps the frozen v1. Non-replay reports equal v1 except `schema_version`, `builder_version`
and `recommendation.origin`. Experiment-replay reports take their outcome explanation from the
sealed `run.concluded.replay_basis` (the classifier's decision) and never re-classify; the
original recommendation is referenced with `origin: source_run`, and the replay's own engine
winner is only ever a labelled measurement.
"""

import dataclasses
import itertools
from typing import Any

import pytest

from querycure.benchmark.fixtures import load_prerecorded
from querycure.replay.canonical import canonical_json, canonical_text, to_canonical
from querycure.replay.outcome import BASIS_CODES, REPRODUCING_BASES
from querycure.reports import registry
from querycure.reports.builders import v1, v2
from querycure.reports.builders.v2 import ReportContractError
from querycure.reports.inputs import ReportInputs
from querycure.reports.provenance import unlabeled_numbers
from querycure.reports.renderers import md_v1, md_v2
from tests.unit.reports.test_report_v1 import CASES, FINAL, FIXTURES, inputs

FIXTURE = load_prerecorded(FIXTURES / "stale_stats_sf01.json")
ARM = FIXTURE.config.candidates[0].arm
SOURCE_RUN = "00000000-0000-4000-8000-0000000000bb"
SOURCE_EXP = "00000000-0000-4000-8000-0000000000e1"
SOURCE_RESULT = "5a" * 32
OTHER_RESULT = "6b" * 32


def source_recommendation(**over: Any) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "status": "verified",
        "candidate_key": ARM,
        "kind": "create_index",
        "ddl": ["CREATE INDEX qc_i ON orders (customer_id)"],
        "query_sql": None,
        "primary_measurement": {
            "arm": ARM,
            "param_set": "p1",
            "baseline": {"n": 30, "median_ns": 9_000_000, "p95_ns": 9_500_000, "robust_cv": 0.02},
            "candidate": {"n": 30, "median_ns": 3_000_000, "p95_ns": 3_100_000, "robust_cv": 0.02},
            "speedup": 3.0,
            "ci_low": 2.8,
            "ci_high": 3.2,
            "provenance": "measured",
            "evidence_id": "ev_" + "7" * 12,
            "source": {"artifact_sha256": SOURCE_RESULT, "pointer": "/stats/0"},
        },
        "scope": "sandbox",
    }
    rec.update(over)
    return rec


def snapshot(**over: Any) -> dict[str, Any]:
    snap: dict[str, Any] = {
        "schema_version": 1,
        "source_run_id": SOURCE_RUN,
        "source_run_kind": "initial",
        "source_experiment_id": SOURCE_EXP,
        "source_experiment_result_sha256": SOURCE_RESULT,
        "source_experiment_environment_digest": "sha256:" + "9" * 64,
        "source_manifest_sha256": "1" * 64,
        "source_report_json_sha256": "2" * 64,
        "source_builder_version": "report-builder@1",
        "source_final_status": "completed",
        "source_outcome": "verified_recommendation",
        "source_recommendation": source_recommendation(),
    }
    snap.update(over)
    return snap


def comparison(status: str = "reproduced", **over: Any) -> dict[str, Any]:
    pair_status = status if status in v2.PAIR_STATUSES else "inconclusive"
    cmp: dict[str, Any] = {
        "status": status,
        "comparison_mode": "same_environment",
        "failure_code": None,
        "original_experiment_id": SOURCE_EXP,
        "replay_experiment_id": "00000000-0000-4000-8000-0000000000e9",
        "config": {"margin": 1.25, "resamples": 2000, "confidence": 0.95, "seed": 7},
        "pairs": []
        if status in ("not_replayable", "failed")
        else [
            {
                "arm": ARM,
                "param_set": "p1",
                "status": pair_status,
                "code": None,
                "original_speedup": 3.0,
                "replay_speedup": 2.9,
                "drift": 0.97,
                "drift_ci_low": 0.9,
                "drift_ci_high": 1.05,
            }
        ],
        "environment": {"differences": []},
        "winner": {"original": ARM, "replay": ARM},
    }
    cmp.update(over)
    return cmp


def basis(code: str, cmp: dict[str, Any] | None, source_outcome: str | None) -> dict[str, Any]:
    return {
        "code": code,
        "source_outcome": source_outcome,
        "comparison_status": None if cmp is None else cmp["status"],
        "comparison_mode": None if cmp is None else cmp["comparison_mode"],
    }


def replay_inputs(
    code: str | None,
    *,
    outcome: str | None,
    cmp: dict[str, Any] | None = None,
    snap: dict[str, Any] | None = None,
    final_status: str = "completed",
    error: dict[str, Any] | None = None,
    snapshot_error: str | None = None,
    basis_override: Any = ...,
    experiment: bool = True,
) -> ReportInputs:
    """A replay run as finalize_run would load it: no candidates, hypotheses or LLM calls of
    its own, one experiment that replays the source's, the comparison, the snapshot, and the
    sealed basis in `run.concluded`."""
    base = inputs(
        kind="experiment_replay",
        outcome=outcome,
        final_status=final_status,
        stop_reason=None if final_status == "completed" else final_status,
        comparison=cmp,
        with_experiment=experiment,
    )
    conclusion = dict(base.conclusion or {})
    conclusion.update({"synthesis_summary": "", "materiality": None, "error": error})
    sealed = basis(code, cmp, (snap or {}).get("source_outcome")) if code else None
    if basis_override is not ...:
        sealed = basis_override
    if sealed is not None:
        conclusion["replay_basis"] = sealed
    return dataclasses.replace(
        base,
        run={**base.run, "run_number": 3, "parent_run_id": SOURCE_RUN},
        conclusion=conclusion,
        errors=[],
        evidence=[e for e in base.evidence if e.kind == "benchmark_metric"],
        findings=[],
        hypotheses=[],
        candidates=[],
        verifications=[],
        llm_calls=[],
        experiments=[{**e, "replay_of_experiment_id": SOURCE_EXP} for e in base.experiments],
        replay_of={"experiment_id": SOURCE_EXP, "run_id": SOURCE_RUN},
        replay_source=snap,
        replay_source_error=snapshot_error,
    )


def build(inp: ReportInputs) -> dict[str, Any]:
    return v2.build_report(inp, **FINAL)  # type: ignore[arg-type]


def render(r: dict[str, Any]) -> str:
    return md_v2.render_markdown(r)


# (case, sealed basis, outcome, comparison, snapshot, final status, expected result)
VERIFIED = snapshot()
INCONCLUSIVE_SOURCE = snapshot(
    source_outcome="inconclusive",
    source_recommendation=source_recommendation(
        status="none", candidate_key=None, kind=None, ddl=[], primary_measurement=None
    ),
)
SCENARIOS: dict[str, dict[str, Any]] = {
    "1_reproduced_original": {
        "code": "reproduced_source_recommendation",
        "outcome": "verified_recommendation",
        "cmp": comparison("reproduced"),
        "snap": VERIFIED,
        "result": "original_reproduced",
    },
    "2_performance_drift": {
        "code": "comparison_reproduced_with_drift",
        "outcome": "inconclusive",
        "cmp": comparison("reproduced_with_drift"),
        "snap": VERIFIED,
        "result": "performance_drift",
    },
    "3_not_reproduced_verdict": {
        "code": "comparison_not_reproduced",
        "outcome": "inconclusive",
        "cmp": comparison("not_reproduced", failure_code="verdict_changed"),
        "snap": VERIFIED,
        "result": "not_reproduced",
    },
    "3_not_reproduced_rows": {
        "code": "comparison_not_reproduced",
        "outcome": "inconclusive",
        "cmp": comparison(
            "not_reproduced",
            failure_code="result_fingerprint_changed",
            pairs=[
                {
                    **comparison()["pairs"][0],
                    "status": "not_reproduced",
                    "code": "result_fingerprint_changed",
                }
            ],
        ),
        "snap": VERIFIED,
        "result": "not_reproduced",
    },
    "4_inconclusive_comparison": {
        "code": "comparison_inconclusive",
        "outcome": "inconclusive",
        "cmp": comparison("inconclusive", failure_code="insufficient_evidence"),
        "snap": VERIFIED,
        "result": "inconclusive",
    },
    "5_cross_environment": {
        "code": "cross_environment",
        "outcome": "inconclusive",
        "cmp": comparison(
            "reproduced",
            comparison_mode="cross_environment",
            environment={
                "differences": [
                    {"field": "cpu_model", "class": "material", "original": "A", "replay": "B"}
                ]
            },
        ),
        "snap": VERIFIED,
        "result": "not_comparable",
    },
    "6_noise_warning_source": {
        "code": "source_noise_warning",
        "outcome": "inconclusive",
        "cmp": comparison("reproduced"),
        "snap": snapshot(
            source_recommendation=source_recommendation(status="verified_with_noise_warning")
        ),
        "result": "not_confirmed",
    },
    "7_other_experiment": {
        "code": "recommendation_from_other_experiment",
        "outcome": "inconclusive",
        "cmp": comparison("reproduced"),
        "snap": snapshot(
            source_recommendation=source_recommendation(
                primary_measurement={
                    **source_recommendation()["primary_measurement"],
                    "source": {"artifact_sha256": OTHER_RESULT, "pointer": "/stats/0"},
                }
            )
        ),
        "result": "not_confirmed",
    },
    "8_inconclusive_source_with_replay_winner": {
        "code": "source_not_verified",
        "outcome": "inconclusive",
        "cmp": comparison("reproduced"),
        "snap": INCONCLUSIVE_SOURCE,
        "result": "not_confirmed",
    },
    "9_no_action_reproduced": {
        "code": "reproduced_source_no_action",
        "outcome": "no_action_needed",
        "cmp": comparison("reproduced"),
        "snap": snapshot(
            source_outcome="no_action_needed",
            source_recommendation=source_recommendation(
                status="none", candidate_key=None, kind=None, ddl=[], primary_measurement=None
            ),
        ),
        "result": "original_reproduced",
    },
    "10_failed_source": {
        "code": "source_not_completed",
        "outcome": "inconclusive",
        "cmp": comparison("reproduced"),
        "snap": snapshot(
            source_final_status="failed",
            source_outcome=None,
            source_recommendation=source_recommendation(
                status="none", candidate_key=None, kind=None, ddl=[], primary_measurement=None
            ),
        ),
        "result": "not_confirmed",
    },
    "11_source_is_replay": {
        "code": "source_is_replay",
        "outcome": "inconclusive",
        "cmp": comparison("reproduced"),
        # an upgraded report-builder@1 replay: verified outcome, empty recommendation
        "snap": snapshot(
            source_run_kind="experiment_replay",
            source_recommendation=source_recommendation(
                status="none", candidate_key=None, kind=None, ddl=[], primary_measurement=None
            ),
        ),
        "result": "not_confirmed",
    },
    "13_candidate_not_compared": {
        "code": "recommended_candidate_not_compared",
        "outcome": "inconclusive",
        "cmp": comparison("reproduced", pairs=[]),
        "snap": VERIFIED,
        "result": "not_confirmed",
    },
    "13_recommendation_missing": {
        "code": "source_recommendation_missing",
        "outcome": "inconclusive",
        "cmp": comparison("reproduced"),
        "snap": snapshot(source_recommendation=source_recommendation(primary_measurement=None)),
        "result": "not_confirmed",
    },
    "14_not_replayable": {
        "code": "comparison_not_replayable",
        "outcome": "inconclusive",
        "cmp": comparison("not_replayable", failure_code="workload_snapshot_changed"),
        "snap": VERIFIED,
        "result": "unavailable",
    },
    "14_comparison_missing": {
        "code": "comparison_missing",
        "outcome": "inconclusive",
        "cmp": None,
        "snap": VERIFIED,
        "result": "unavailable",
    },
    "14_snapshot_missing": {
        "code": "source_snapshot_missing",
        "outcome": "inconclusive",
        "cmp": comparison("reproduced"),
        "snap": None,
        "result": "unavailable",
    },
    "14_snapshot_mismatch": {
        "code": "source_snapshot_mismatch",
        "outcome": "inconclusive",
        "cmp": comparison(
            "reproduced", original_experiment_id="00000000-0000-4000-8000-00000000dead"
        ),
        "snap": VERIFIED,
        "result": "unavailable",
    },
    "14_comparison_unrecognized": {
        "code": "comparison_unrecognized",
        "outcome": "inconclusive",
        "cmp": comparison("exotic"),
        "snap": VERIFIED,
        "result": "unavailable",
    },
    "15_comparison_failed": {
        "code": "comparison_failed",
        "outcome": None,
        "final_status": "failed",
        "error": {"code": "ddl_failed"},
        "cmp": comparison("failed", failure_code="ddl_failed"),
        "snap": VERIFIED,
        "result": "failed",
    },
    "15_execution_failed": {
        "code": None,
        "outcome": None,
        "final_status": "failed",
        "error": {"code": "sandbox_unavailable"},
        "cmp": None,
        "snap": VERIFIED,
        "experiment": False,
        "result": "failed",
    },
    "15_cancelled": {
        "code": None,
        "outcome": None,
        "final_status": "cancelled",
        "cmp": None,
        "snap": VERIFIED,
        "experiment": False,
        "result": "cancelled",
    },
    "unclassified_inconclusive": {
        "code": None,
        "outcome": "inconclusive",
        "cmp": comparison("reproduced"),
        "snap": VERIFIED,
        "result": "unclassified",
    },
}


def scenario_inputs(name: str, **extra: Any) -> ReportInputs:
    s = SCENARIOS[name]
    return replay_inputs(
        s["code"],
        outcome=s["outcome"],
        cmp=s["cmp"],
        snap=s["snap"],
        final_status=s.get("final_status", "completed"),
        error=s.get("error"),
        experiment=s.get("experiment", True),
        **extra,
    )


def scenario(name: str) -> dict[str, Any]:
    return build(scenario_inputs(name))


# --- Versioning and registration -------------------------------------------------------


def test_v2_is_registered_but_v1_stays_current() -> None:
    assert registry.BUILDERS[v2.BUILDER_VERSION] is v2.build_report
    assert registry.RENDERERS[md_v2.MD_RENDERER_VERSION] is md_v2.render_markdown
    assert registry.BUILDERS[v1.BUILDER_VERSION] is v1.build_report
    assert registry.RENDERERS[md_v1.MD_RENDERER_VERSION] is md_v1.render_markdown
    assert (registry.CURRENT_BUILDER, registry.CURRENT_RENDERER) == (
        "report-builder@1",
        "report-md@1",
    )
    assert registry.CURRENT_SCHEMA_VERSION == 1
    assert (v2.BUILDER_VERSION, v2.REPORT_SCHEMA_VERSION) == ("report-builder@2", 2)


@pytest.mark.parametrize("case", CASES)
def test_non_replay_v2_equals_v1_except_three_fields(case: str) -> None:
    inp = inputs(**CASES[case])  # type: ignore[arg-type]
    one, two = v1.build_report(inp, **FINAL), v2.build_report(inp, **FINAL)  # type: ignore[arg-type]

    assert two["schema_version"] == 2
    assert two["builder_version"] == "report-builder@2"
    assert two["recommendation"]["origin"] == "run"
    stripped = {**two, "schema_version": 1, "builder_version": "report-builder@1"}
    stripped["recommendation"] = {k: v for k, v in two["recommendation"].items() if k != "origin"}
    assert stripped == one
    assert "replay_result" not in two


@pytest.mark.parametrize("case", CASES)
def test_non_replay_md_v2_differs_from_md_v1_only_in_the_version_line(case: str) -> None:
    inp = inputs(**CASES[case])  # type: ignore[arg-type]
    one = md_v1.render_markdown(v1.build_report(inp, **FINAL)).splitlines()  # type: ignore[arg-type]
    two = render(v2.build_report(inp, **FINAL)).splitlines()  # type: ignore[arg-type]

    assert len(one) == len(two)
    differing = [(a, b) for a, b in zip(one, two, strict=True) if a != b]
    assert len(differing) == 1
    assert "`report-builder@2`, rendered by `report-md@2`, report schema 2" in differing[0][1]


# --- The approved scenarios (§12.3 rows 1to15) -------------------------------------------


@pytest.mark.parametrize("name", SCENARIOS)
def test_scenario_result_and_claim(name: str) -> None:
    r = scenario(name)
    s = SCENARIOS[name]
    rr = r["replay_result"]

    assert r["schema_version"] == 2
    assert rr["result"] == s["result"]
    assert r["outcome"] == s["outcome"]
    assert rr["claims_reproduction"] is (s["code"] in REPRODUCING_BASES)
    assert r["headline"].startswith(rr["title"])
    expected_basis = (
        None
        if s["code"] is None
        else basis(s["code"], s["cmp"], (s["snap"] or {}).get("source_outcome"))
    )
    assert rr["basis"] == expected_basis


def test_reproduced_original_references_the_source_candidate_with_provenance() -> None:
    r = scenario("1_reproduced_original")
    rec, rr = r["recommendation"], r["replay_result"]

    assert rec["origin"] == "source_run"
    assert rec["source_run_id"] == SOURCE_RUN
    assert rec["candidate_key"] == ARM
    assert rec["status"] == "verified"
    assert rec["primary_measurement"] == source_recommendation()["primary_measurement"]
    assert rr["source_recommendation"]["provenance"] == "source_run"
    assert rr["source"]["provenance"] == "source_run"
    assert rr["original_reproduced"] is True
    assert rr["experiment_match"]["matches"] is True
    assert rr["correctness_reproduced"] is True
    assert rr["performance_reproduced"] is True
    assert rr["material_drift"] is False
    assert rr["environment_comparable"] is True
    assert "verified" not in r["headline"].lower().split("reproduced")[0]
    assert rr["title"] == "Original recommendation reproduced"


@pytest.mark.parametrize("name", [n for n in SCENARIOS if n not in ("1_reproduced_original",)])
def test_no_other_scenario_carries_a_recommendation(name: str) -> None:
    r = scenario(name)

    assert r["recommendation"]["status"] == "none"
    assert r["recommendation"]["candidate_key"] is None
    assert r["recommendation"]["origin"] == "run"
    assert r["replay_result"]["original_reproduced"] is (name == "9_no_action_reproduced")


def test_drift_reports_correctness_held_and_material_drift() -> None:
    rr = scenario("2_performance_drift")["replay_result"]

    assert rr["correctness_reproduced"] is True
    assert rr["performance_reproduced"] is False
    assert rr["material_drift"] is True
    assert rr["comparison_status"] == "reproduced_with_drift"
    assert rr["title"] == "Performance drift detected"


def test_not_reproduced_is_never_described_as_successful() -> None:
    for name in ("3_not_reproduced_verdict", "3_not_reproduced_rows"):
        r = scenario(name)
        text = (r["headline"] + " " + r["replay_result"]["explanation"]).lower()
        assert "not reproduced" in text
        for word in ("successful", "verified", "confirmed by"):
            assert word not in text.replace("not confirmed", "")
    assert scenario("3_not_reproduced_rows")["replay_result"]["correctness_reproduced"] is False


def test_cross_environment_is_never_called_reproduced() -> None:
    r = scenario("5_cross_environment")
    rr = r["replay_result"]

    assert rr["environment_comparable"] is False
    assert rr["material_differences"] == ["cpu_model"]
    assert rr["title"] == "Results not directly comparable"
    assert "reproduced" not in r["headline"].lower().replace("not a reproduction", "")


def test_replay_of_a_replay_never_inherits_verification() -> None:
    r = scenario("11_source_is_replay")

    assert r["outcome"] == "inconclusive"
    assert r["recommendation"]["status"] == "none"
    assert r["replay_result"]["source"]["outcome"] == "verified_recommendation"
    assert r["replay_result"]["source"]["run_kind"] == "experiment_replay"
    assert r["replay_result"]["source_recommendation"] is None


def test_the_replay_engine_winner_is_only_a_labelled_measurement() -> None:
    for name in SCENARIOS:
        r = scenario(name)
        m = r["replay_result"]["replay_measurement"]
        if not SCENARIOS[name].get("experiment", True):
            assert m["engine_winner"] is None
            continue
        assert m["engine_winner"] == FIXTURE.result.winner
        assert m["label"] == "replay measurement, not a verification"
        assert m["provenance"] == "measured"
    # inconclusive source + a replay winner: still no recommendation (the 28-case defect)
    r = scenario("8_inconclusive_source_with_replay_winner")
    assert FIXTURE.result.winner is not None
    assert r["recommendation"]["candidate_key"] is None
    assert r["outcome"] == "inconclusive"


def test_absent_optional_evidence_is_stated_not_invented() -> None:
    r = scenario("14_comparison_missing")
    rr = r["replay_result"]
    assert rr["comparison_status"] is None
    assert rr["correctness_reproduced"] is None
    assert rr["performance_reproduced"] is None
    assert rr["material_drift"] is None
    assert rr["environment_comparable"] is None

    r = scenario("14_snapshot_missing")
    rr = r["replay_result"]
    assert rr["source"] is None
    assert rr["source_recommendation"] is None
    assert rr["experiment_match"]["matches"] is None

    r = scenario("15_execution_failed")
    assert r["replay_result"]["failure_code"] == "sandbox_unavailable"
    assert r["replay_result"]["title"] == "Replay failed"


def test_snapshot_error_is_reported_and_never_confirms() -> None:
    inp = replay_inputs(
        "source_snapshot_missing",
        outcome="inconclusive",
        cmp=comparison("reproduced"),
        snap=None,
        snapshot_error="marker requires a source snapshot the replay is missing",
    )
    r = build(inp)

    assert r["replay_result"]["snapshot_error"] == (
        "marker requires a source snapshot the replay is missing"
    )
    assert r["replay_result"]["claims_reproduction"] is False
    assert any("source snapshot" in x for x in r["limitations"])


# --- Fail closed: the report can never contradict the sealed classification ----------------


@pytest.mark.parametrize(
    ("code", "outcome", "snap", "cmp"),
    [
        # a verified outcome needs the reproducing basis
        (
            "comparison_inconclusive",
            "verified_recommendation",
            VERIFIED,
            comparison("inconclusive"),
        ),
        ("reproduced_source_recommendation", "inconclusive", VERIFIED, comparison()),
        ("reproduced_source_no_action", "verified_recommendation", VERIFIED, comparison()),
        # an unknown basis code
        ("looks_good", "inconclusive", VERIFIED, comparison()),
        # the reproducing basis without a snapshot or without a source recommendation
        ("reproduced_source_recommendation", "verified_recommendation", None, comparison()),
        (
            "reproduced_source_recommendation",
            "verified_recommendation",
            INCONCLUSIVE_SOURCE,
            comparison(),
        ),
    ],
)
def test_contradictory_records_refuse_to_build(
    code: str, outcome: str, snap: dict[str, Any] | None, cmp: dict[str, Any]
) -> None:
    with pytest.raises(ReportContractError):
        build(replay_inputs(code, outcome=outcome, cmp=cmp, snap=snap))


def test_basis_that_disagrees_with_the_snapshot_or_comparison_refuses_to_build() -> None:
    cmp = comparison("reproduced")
    wrong_source = {**basis("source_not_verified", cmp, "no_action_needed")}
    wrong_status = {**basis("comparison_inconclusive", cmp, "verified_recommendation")}
    wrong_mode = {**basis("cross_environment", cmp, "verified_recommendation")}
    wrong_mode["comparison_mode"] = "cross_environment"
    for sealed in (wrong_source, wrong_status, wrong_mode):
        with pytest.raises(ReportContractError):
            build(
                replay_inputs(
                    "x",
                    outcome="inconclusive",
                    cmp=cmp,
                    snap=INCONCLUSIVE_SOURCE,
                    basis_override=sealed,
                )
            )


@pytest.mark.parametrize(
    "sealed",
    ["reproduced", None, {"code": "reproduced_source_recommendation"}, {}, ["x"]],
    ids=["string", "null", "partial", "empty", "list"],
)
def test_malformed_basis_refuses_to_build(sealed: Any) -> None:
    inp = replay_inputs(None, outcome="inconclusive", cmp=comparison(), snap=VERIFIED)
    conclusion = {**(inp.conclusion or {}), "replay_basis": sealed}
    with pytest.raises(ReportContractError):
        build(dataclasses.replace(inp, conclusion=conclusion))


def test_missing_basis_with_a_favourable_outcome_refuses_to_build() -> None:
    for outcome in ("verified_recommendation", "no_action_needed", "unverified_recommendations"):
        with pytest.raises(ReportContractError):
            build(replay_inputs(None, outcome=outcome, cmp=comparison(), snap=VERIFIED))


def test_no_combination_of_sealed_records_yields_a_contradiction() -> None:
    """Over every basis code x outcome x snapshot x comparison status: the builder either
    refuses or produces a report in which outcome, recommendation, claim and headline agree."""
    snaps = {
        "verified": VERIFIED,
        "inconclusive": INCONCLUSIVE_SOURCE,
        "replay": SCENARIOS["11_source_is_replay"]["snap"],
        "none": None,
    }
    outcomes = ["verified_recommendation", "no_action_needed", "inconclusive",
                "unverified_recommendations"]  # fmt: skip
    statuses = ["reproduced", "reproduced_with_drift", "inconclusive", "not_reproduced",
                "not_replayable"]  # fmt: skip
    built = refused = 0
    for code, outcome, snap_key, status in itertools.product(
        [*sorted(BASIS_CODES - {"comparison_failed"}), None], outcomes, snaps, statuses
    ):
        cmp = comparison(status)
        snap = snaps[snap_key]
        try:
            r = build(replay_inputs(code, outcome=outcome, cmp=cmp, snap=snap))
        except ReportContractError:
            refused += 1
            continue
        built += 1
        rr, rec = r["replay_result"], r["recommendation"]
        verified = r["outcome"] == "verified_recommendation"
        assert verified == (rec["origin"] == "source_run") == (rec["status"] != "none")
        assert verified == (code == "reproduced_source_recommendation")
        assert rr["claims_reproduction"] == (code in REPRODUCING_BASES)
        assert (r["outcome"] == "no_action_needed") == (code == "reproduced_source_no_action")
        if verified:
            assert rec["candidate_key"] == (snap or {})["source_recommendation"]["candidate_key"]
        md = render(r)
        assert "Verified recommendation" not in md
        if not rr["claims_reproduction"]:
            assert "reproduced by replay" not in (r["headline"] + md).lower()
    assert built
    assert refused


# --- Markdown -----------------------------------------------------------------------------


@pytest.mark.parametrize("name", SCENARIOS)
def test_every_number_in_the_replay_markdown_is_labeled(name: str) -> None:
    assert unlabeled_numbers(render(scenario(name))) == []


@pytest.mark.parametrize("name", SCENARIOS)
def test_build_and_render_are_byte_identical_on_rebuild(name: str) -> None:
    first, second = scenario(name), scenario(name)

    assert canonical_json(to_canonical(first)) == canonical_json(to_canonical(second))
    assert canonical_text(render(first)) == canonical_text(render(second))


@pytest.mark.parametrize("name", SCENARIOS)
def test_markdown_has_an_experiment_replay_result_section_consistent_with_json(
    name: str,
) -> None:
    r = scenario(name)
    rr = r["replay_result"]
    md = render(r)

    assert "## Experiment Replay Result" in md
    assert f"> **{rr['title']}.**" in md
    assert "Verified recommendation" not in md
    if rr["basis"] is not None:
        assert f"`{rr['basis']['code']}`" in md
    if rr["source"] is not None:
        assert f"`{SOURCE_RUN}`" in md
    if rr["comparison_status"] is not None:
        assert f"**{rr['comparison_status']}**" in md
    winner = rr["replay_measurement"]["engine_winner"]
    if winner:
        assert "replay measurement, not a verification" in md
    if r["recommendation"]["origin"] == "source_run":
        assert "## Original recommendation" in md
        assert "reproduced by this replay" in md
    else:
        assert "## Original recommendation" not in md
        assert "This replay makes no recommendation of its own." in md


def test_reproduced_markdown_says_reproduced_by_replay_not_verified() -> None:
    md = render(scenario("1_reproduced_original"))

    assert "> **Original recommendation reproduced.**" in md
    assert "verified nothing new" in md
    assert "Original recommendation reproduced: yes (derived)" in md


def test_unconfirmed_original_candidate_is_shown_for_reference_only() -> None:
    md = render(scenario("2_performance_drift"))

    assert "is shown for reference and is not confirmed by this replay" in md
    assert "Original recommendation reproduced: no (derived)" in md


def test_v1_reports_still_render_only_with_md_v1() -> None:
    r = v1.build_report(inputs(), **FINAL)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="schema"):
        md_v2.render_markdown(r)


def test_the_builder_knows_exactly_the_classifier_basis_codes() -> None:
    """v2 mirrors the classifier's codes instead of importing them (a frozen builder must not
    follow a changing module); a new code needs a new builder version."""
    assert v2.BASIS_CODES == BASIS_CODES
    assert v2.REPRODUCING == REPRODUCING_BASES
    assert set(v2.RESULT) == set(v2.TITLE) == set(BASIS_CODES)
