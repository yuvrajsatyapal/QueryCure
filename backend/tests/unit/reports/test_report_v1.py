"""report-builder@1 + report-md@1 (T4.4): pure, deterministic, every number labeled.

Inputs are built from the committed experiment fixtures (real samples), so the reports cover
verified, rejected, inconclusive, noise-warning, prerecorded, partial and replay cases.
"""

import uuid
from pathlib import Path
from typing import Any

import pytest

from querycure.benchmark.engine import sql_digest
from querycure.benchmark.fixtures import load_prerecorded
from querycure.domain.investigation import Evidence, Finding, Hypothesis
from querycure.domain.optimization import CandidateCost, OptimizationCandidate
from querycure.evidence.ids import evidence_id
from querycure.replay.canonical import canonical_json, canonical_text, to_canonical
from querycure.reports.builders.v1 import build_report
from querycure.reports.inputs import ReportInputs
from querycure.reports.provenance import unlabeled_numbers
from querycure.reports.renderers.md_v1 import render_markdown

FIXTURES = Path(__file__).parents[3] / "evals" / "fixtures" / "experiments"
RUN = uuid.UUID("00000000-0000-4000-8000-0000000000aa")
RESULT_SHA = "ab" * 32
FINAL = {
    "finalized_at": "2026-10-13T12:00:00.000000Z",
    "cutoff_seq": 42,
    "events_digest": "sha256:" + "cd" * 32,
}


def _plan_evidence() -> Evidence:
    return Evidence(
        id=evidence_id(RUN, "plan_node", "ef" * 32, "/0/Plan"),
        kind="plan_node",
        artifact_sha256="ef" * 32,
        locator="/0/Plan",
        summary="Seq Scan on orders: 120.5 ms of 121.0 ms, 995000 rows removed by filter",
        data={"self_time_ms": 120.5},
        provenance="imported",
    )


def inputs(
    fixture: str = "stale_stats_sf01",
    *,
    outcome: str | None = "verified_recommendation",
    final_status: str = "completed",
    stop_reason: str | None = None,
    status: str | None = None,
    provenance: str = "measured",
    verdict_override: str | None = None,
    kind: str = "initial",
    comparison: dict[str, Any] | None = None,
    with_experiment: bool = True,
) -> ReportInputs:
    exp = load_prerecorded(FIXTURES / f"{fixture}.json")
    result = exp.result.model_copy(update={"provenance": provenance})
    arm = exp.config.candidates[0]
    cid = uuid.uuid5(RUN, arm.arm)
    plan = _plan_evidence()
    metric_ids = []
    evidence = [plan]
    for s in result.stats:
        eid = evidence_id(RUN, "benchmark_metric", RESULT_SHA, f"/stats/{s.arm}/{s.param_set}")
        metric_ids.append(eid)
        evidence.append(
            Evidence(
                id=eid,
                kind="benchmark_metric",
                artifact_sha256=RESULT_SHA,
                locator=f"/stats/{s.arm}/{s.param_set}",
                summary=f"speedup {s.speedup:.2f}x",
                data={"speedup": round(s.speedup, 3)},
                provenance=provenance,
            )  # type: ignore[arg-type]
        )
    rule = result.verdicts[0].verdict
    engine = verdict_override or rule
    hyp_key = "hy_" + "1" * 12
    return ReportInputs(
        run={
            "id": str(RUN),
            "investigation_id": str(uuid.uuid5(RUN, "inv")),
            "run_number": 1,
            "kind": kind,
            "parent_run_id": None,
        },
        investigation={
            "title": "Slow orders page",
            "objective": "Make it fast for 30 users",
            "modes": ["sandbox_benchmark"],
            "workload_id": exp.config.workload_id,
            "live_connection": False,
        },
        conclusion={
            "final_status": final_status,
            "outcome": outcome,
            "stop_reason": stop_reason,
            "synthesis_summary": "The scan over 1000000 rows dominates.",
            "materiality": {
                "verdict": "material",
                "reasons": ["The query took 121 ms."],
                "evidence_ids": [plan.id],
            },
            "no_action_evidence": [],
            "usage": {"llm_calls": 7, "tool_calls": 2},
            "error": None,
        },
        errors=[
            {
                "node": "query_analyzer",
                "code": "AGENT_FAILED",
                "message": "retry 2 failed",
                "recoverable": True,
            }
        ],
        query_sql=exp.config.baseline_query,
        query_sha256="12" * 32,
        param_sets=[p.model_dump() for p in exp.config.param_sets],
        evidence=evidence,
        findings=[
            (
                "fd_" + "2" * 12,
                Finding(
                    agent="query_analyzer",
                    title="Scan 1 dominates",
                    detail="Seq Scan reads 1000000 rows.",
                    severity="high",
                    evidence_ids=[plan.id],
                ),
            )
        ],
        hypotheses=[
            Hypothesis(
                key=hyp_key,
                rank=1,
                statement="Missing index on 2 columns.",
                category="missing_index",
                supporting_evidence=[plan.id],
                confidence="high",
                uncertainty_notes="",
                verification_method="benchmark",
                proposed_by=["query_analyzer"],
            )
        ],
        candidates=[
            OptimizationCandidate(
                id=cid,
                key=arm.arm,
                round=0,
                kind=arm.kind,
                addresses_hypotheses=[hyp_key],
                ddl=list(arm.ddl),
                query_sql=arm.query,
                sql_sha256=sql_digest(arm),
                rollback_sql=None,
                expected_benefit="Avoid the 1 sort",
                risks=[],
                estimated_cost=CandidateCost(),
                status=status or engine,  # type: ignore[arg-type]
            )
        ],
        approvals=[
            {
                "id": str(uuid.uuid5(RUN, "approval")),
                "round": 0,
                "status": "approved",
                "decided_by": "user:1",
                "decided_at": "2026-10-13T11:00:00.000000Z",
                "approved_candidate_ids": [str(cid)],
            }
        ],
        experiments=[]
        if not with_experiment
        else [
            {
                "id": str(exp.config.experiment_id),
                "round": 0,
                "replicate": 0,
                "status": "completed",
                "engine_version": result.engine_version,
                "row_profile": "qc-row-v1",
                "seed": exp.config.seed,
                "environment": exp.environment.model_dump(mode="json"),
                "environment_digest": "sha256:" + "99" * 32,
                "replay_of_experiment_id": None,
                "error": None,
                "config": exp.config.model_dump(mode="json"),
                "result": to_canonical(result),
                "result_sha256": RESULT_SHA,
                "replication": None,
            }
        ],
        verifications=[]
        if not with_experiment
        else [
            {
                "experiment_id": str(exp.config.experiment_id),
                "candidate_key": arm.arm,
                "engine_verdict": engine,
                "verdict": status or engine,
                "auditor_downgraded": (status or engine) != engine,
                "auditor_status": "completed",
                "auditor_prompt_version": "benchmark_auditor@1",
                "auditor_notes": "Checked 2 parameter sets.",
                "checks": [
                    {
                        "name": "samples",
                        "status": "pass",
                        "detail": "30 samples per arm and set",
                        "evidence_ids": metric_ids,
                    }
                ],
                "auditor_concerns": [
                    {
                        "arm": arm.arm,
                        "severity": "warning",
                        "text": "Only 2 sets tested.",
                        "evidence_ids": metric_ids[:1],
                    }
                ],
            }
        ],
        llm_calls=[
            {
                "agent": "query_analyzer",
                "model": "nvidia/x:free",
                "served_by": "Nvidia",
                "prompt_version": "query_analyzer@1",
                "status": "succeeded",
                "calls": 3,
            }
        ],
        comparison=comparison,
    )


CASES = {
    "verified": {},
    "rejected": {"fixture": "index_regression_sf01", "outcome": "inconclusive"},
    "mismatch": {"fixture": "rewrite_trap_sf01", "outcome": "inconclusive"},
    "inconclusive": {"fixture": "orders_ecommerce_sf1_composite_index", "outcome": "inconclusive"},
    "noise_warning": {"verdict_override": "verified_with_noise_warning"},
    "downgraded": {"outcome": "inconclusive", "status": "inconclusive"},
    "prerecorded": {"provenance": "prerecorded"},
    "unbenchmarked": {
        "outcome": "unverified_recommendations",
        "with_experiment": False,
        "status": "proposed",
    },
    "cancelled": {
        "outcome": None,
        "final_status": "cancelled",
        "stop_reason": "cancelled",
        "with_experiment": False,
        "status": "proposed",
    },
}


def report(**kw: Any) -> dict[str, Any]:
    return build_report(inputs(**kw), **FINAL)  # type: ignore[arg-type]


@pytest.mark.parametrize("case", CASES)
def test_every_number_in_the_markdown_is_labeled(case: str) -> None:
    md = render_markdown(report(**CASES[case]))

    assert unlabeled_numbers(md) == []


def test_scanner_catches_an_unlabeled_number() -> None:
    assert unlabeled_numbers("- It is 12.5 ms faster") == ["- It is 12.5 ms faster"]
    assert unlabeled_numbers("- 12.5 ms (measured)") == []
    assert unlabeled_numbers("- `ev_0123456789ab` and `12`") == []
    assert unlabeled_numbers("```sql\nSELECT 1\n```") == []


@pytest.mark.parametrize("case", CASES)
def test_build_and_render_are_byte_identical_on_rebuild(case: str) -> None:
    first, second = report(**CASES[case]), report(**CASES[case])

    assert canonical_json(to_canonical(first)) == canonical_json(to_canonical(second))
    assert canonical_text(render_markdown(first)) == canonical_text(render_markdown(second))


def test_report_schema_fields_are_always_present() -> None:
    keys = set(report())
    for case in CASES.values():
        assert set(report(**case)) == keys
    assert {
        "recommendation",
        "limitations",
        "next_steps",
        "provenance",
        "rounds",
        "replay",
        "missing",
        "events",
        "headline",
    } <= keys


def test_verified_report_recommends_with_measured_provenance_and_sandbox_scope() -> None:
    r = report()
    md = render_markdown(r)

    assert r["recommendation"]["status"] == "verified"
    assert r["recommendation"]["scope"] == "sandbox"
    m = r["recommendation"]["primary_measurement"]
    assert m["provenance"] == "measured"
    assert m["evidence_id"].startswith("ev_")
    assert m["source"] == {"artifact_sha256": RESULT_SHA, "pointer": "/stats/0"}
    assert "Nothing was applied to your database" in md
    assert "not a guarantee for every workload" in md


def test_noise_warning_is_always_spelled_out() -> None:
    r = report(**CASES["noise_warning"])
    md = render_markdown(r)

    assert r["recommendation"]["status"] == "verified_with_noise_warning"
    assert "noise warning" in r["headline"]
    assert any(x.startswith("Noise warning") for x in r["limitations"])
    assert "verified with noise warning" in md


def test_auditor_downgrade_is_shown_and_not_recommended() -> None:
    r = report(**CASES["downgraded"])
    md = render_markdown(r)

    assert r["recommendation"]["candidate_key"] is None
    assert "downgraded by the auditor" in md


def test_inconclusive_report_explains_why() -> None:
    r = report(**CASES["inconclusive"])

    assert r["outcome"] == "inconclusive"
    assert any("inconclusive is not a rejection" in s for s in r["next_steps"])
    assert any("noisy" in s for s in r["next_steps"])


def test_prerecorded_measurements_are_never_presented_as_live() -> None:
    r = report(**CASES["prerecorded"])
    md = render_markdown(r)

    assert r["provenance"]["measurements"] == ["prerecorded"]
    assert "prerecorded demo measurements" in md
    assert "| measured" not in md


def test_partial_report_lists_missing_evidence() -> None:
    r = report(**CASES["cancelled"])
    md = render_markdown(r)

    assert r["partial"] is True
    assert {m["section"] for m in r["missing"]} >= {"benchmark"}
    assert "Partial report" in md
    assert "Missing evidence" in md


def test_replay_comparison_renders_with_labels() -> None:
    comparison = {
        "status": "reproduced",
        "comparison_mode": "same_environment",
        "failure_code": None,
        "pairs": [
            {
                "arm": "oc_0000000000a3",
                "param_set": "purchases",
                "status": "reproduced",
                "code": None,
                "original_speedup": 2.0,
                "replay_speedup": 2.1,
                "drift_ci_low": 0.9,
                "drift_ci_high": 1.2,
            }
        ],
        "environment": {
            "differences": [
                {"field": "os", "class": "minor", "original": "Darwin 25", "replay": "Darwin 26"}
            ]
        },
    }
    r = report(kind="experiment_replay", comparison=comparison)
    md = render_markdown(r)

    assert r["replay"]["comparison"]["status"] == "reproduced"
    assert "Experiment replay" in md
    assert unlabeled_numbers(md) == []
