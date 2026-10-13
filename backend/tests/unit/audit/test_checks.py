"""Benchmark Auditor deterministic checks (T4.2, ADR-0009).

Built from the committed experiment fixtures: real samples, split back into the blocks the
engine would have persisted. The auditor may only downgrade verified → inconclusive.
"""

import dataclasses
import uuid
from pathlib import Path
from typing import Any

import pytest

from querycure.audit.checks import (
    ApprovalFacts,
    AuditInputs,
    CandidateFacts,
    audit_experiment,
    records_from_result,
)
from querycure.benchmark.engine import sql_digest
from querycure.benchmark.fixtures import load_prerecorded
from querycure.domain.audit import audited
from querycure.domain.benchmark import (
    ExperimentResult,
    Reason,
    ReplicationResult,
    ReplicationVerdict,
    RuleVerdict,
)
from querycure.plans.parser import parse_plan
from querycure.replay.canonical import canonical_json, to_canonical
from querycure.replay.digest import digest

FIXTURES = Path(__file__).parents[3] / "evals" / "fixtures" / "experiments"


def _load(name: str) -> Any:
    fixture = load_prerecorded(FIXTURES / f"{name}.json")
    # The fixtures are labelled prerecorded; an audited live run would carry measured data.
    return fixture, fixture.result.model_copy(update={"provenance": "measured"})


def inputs(name: str = "stale_stats_sf01", **overrides: Any) -> AuditInputs:
    fixture, result = _load(name)
    config, env = fixture.config, fixture.environment
    env_digest = digest("qc-json-v1", canonical_json(to_canonical(env)))
    result = result.model_copy(update={"environment_digest": env_digest})
    ids = {c.arm: uuid.uuid5(uuid.NAMESPACE_URL, c.arm) for c in config.candidates}
    candidates = {
        c.arm: CandidateFacts(key=c.arm, id=ids[c.arm], kind=c.kind, sql_sha256=sql_digest(c))
        for c in config.candidates
    }
    approval = ApprovalFacts(
        status="approved",
        approved_candidate_ids=frozenset(ids.values()),
        digests={c.arm: sql_digest(c) for c in config.candidates},
        baseline_query=config.baseline_query,
        param_sets=[p.model_dump() for p in config.param_sets],
    )
    base = AuditInputs(
        round=0,
        config=config,
        result=result,
        records=records_from_result(config, result),
        record_provenance=["measured"],
        environment=env,
        environment_digest=env_digest,
        approval=approval,
        candidates=candidates,
    )
    return dataclasses.replace(base, **overrides)


def check(audit: Any, name: str) -> Any:
    return next(c for c in audit.checks if c.name == name)


def test_clean_verified_experiment_passes_and_keeps_its_winner() -> None:
    assessment = audit_experiment(inputs())

    [arm] = assessment.candidates
    assert arm.engine_verdict == "verified"
    assert arm.verdict == "verified"
    assert arm.downgrade_reasons == []
    assert {c.name: c.status for c in arm.checks} == {
        "rescore": "pass",
        "approval": "pass",
        "config": "pass",
        "environment": "pass",
        "provenance": "pass",
        "samples": "pass",
        "param_sets": "pass",
        "dispersion": "pass",
        "correctness": "pass",
        "plan_change": "skip",
        "replication": "skip",
    }
    assert assessment.winner == arm.arm


def _claim_verified(result: ExperimentResult) -> ExperimentResult:
    """A stored result whose verdicts claim more than its own samples support."""
    return result.model_copy(
        update={
            "verdicts": [
                RuleVerdict(arm=v.arm, verdict="verified", reasons=[], gate=None)
                for v in result.verdicts
            ],
            "winner": result.verdicts[0].arm,
        }
    )


def test_stored_verdict_that_samples_do_not_support_is_downgraded() -> None:
    base = inputs("index_regression_sf01")

    audit = audit_experiment(dataclasses.replace(base, result=_claim_verified(base.result)))

    [arm] = audit.candidates
    assert check(arm, "rescore").status == "fail"
    assert arm.engine_verdict == "verified"
    assert arm.verdict == "inconclusive"
    assert any(r.startswith("rescore") for r in arm.downgrade_reasons)
    assert audit.winner is None


def test_rejected_verdict_is_never_changed_even_when_checks_fail() -> None:
    base = inputs("index_regression_sf01")
    approval = dataclasses.replace(base.approval, status="declined")  # type: ignore[type-var]

    [arm] = audit_experiment(dataclasses.replace(base, approval=approval)).candidates

    assert check(arm, "approval").status == "fail"
    assert arm.engine_verdict == arm.verdict == "rejected"


def test_inconclusive_is_never_upgraded() -> None:
    [arm] = audit_experiment(inputs("orders_ecommerce_sf1_composite_index")).candidates

    assert arm.engine_verdict == arm.verdict == "inconclusive"
    assert check(arm, "rescore").status == "pass"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda a: dataclasses.replace(a, digests={k: "0" * 64 for k in a.digests}),
        lambda a: dataclasses.replace(a, approved_candidate_ids=frozenset()),
        lambda a: dataclasses.replace(a, status="pending"),
    ],
    ids=["digest_mismatch", "not_in_decision", "not_decided"],
)
def test_approval_must_pin_exactly_the_measured_sql(mutate: Any) -> None:
    base = inputs()
    [arm] = audit_experiment(dataclasses.replace(base, approval=mutate(base.approval))).candidates

    assert check(arm, "approval").status == "fail"
    assert arm.verdict == "inconclusive"


def test_missing_approval_fails() -> None:
    [arm] = audit_experiment(inputs(approval=None)).candidates

    assert check(arm, "approval").status == "fail"


def test_candidate_digest_must_match_the_config_arm() -> None:
    base = inputs()
    key = next(iter(base.candidates))
    tampered = {key: dataclasses.replace(base.candidates[key], sql_sha256="f" * 64)}

    [arm] = audit_experiment(dataclasses.replace(base, candidates=tampered)).candidates

    assert check(arm, "approval").status == "fail"


def test_config_must_match_what_was_approved() -> None:
    base = inputs()
    approval = dataclasses.replace(base.approval, baseline_query="SELECT 1")  # type: ignore[type-var]

    [arm] = audit_experiment(dataclasses.replace(base, approval=approval)).candidates

    assert check(arm, "config").status == "fail"
    assert arm.verdict == "inconclusive"


@pytest.mark.parametrize(
    "overrides",
    [{"environment_digest": "sha256:other"}, {"environment": None}],
    ids=["digest_mismatch", "missing"],
)
def test_environment_must_be_recorded_and_consistent(overrides: dict[str, Any]) -> None:
    [arm] = audit_experiment(inputs(**overrides)).candidates

    assert check(arm, "environment").status == "fail"
    assert arm.verdict == "inconclusive"


def test_prerecorded_samples_never_count_in_a_live_audit() -> None:
    base = inputs()
    prerecorded = base.result.model_copy(update={"provenance": "prerecorded"})

    for variant in (
        dataclasses.replace(base, result=prerecorded),
        dataclasses.replace(base, record_provenance=["measured", "prerecorded"]),
    ):
        [arm] = audit_experiment(variant).candidates
        assert check(arm, "provenance").status == "fail"
        assert arm.verdict == "inconclusive"


def test_fewer_samples_than_configured_is_a_warning() -> None:
    base = inputs()
    config = base.config.model_copy(update={"measured_runs": 60})

    [arm] = audit_experiment(dataclasses.replace(base, config=config)).candidates

    assert check(arm, "samples").status == "warn"
    assert arm.verdict == "verified"


def _with_stats(result: ExperimentResult, ps: str, low: float, high: float) -> ExperimentResult:
    stats = [
        s.model_copy(update={"ci_low": low, "ci_high": high}) if s.param_set == ps else s
        for s in result.stats
    ]
    return result.model_copy(update={"stats": stats})


def test_secondary_param_set_without_demonstrated_benefit_is_a_warning() -> None:
    base = inputs()
    secondary = base.config.param_sets[1].name
    result = _with_stats(base.result, secondary, 0.9, 1.4)

    [arm] = audit_experiment(
        dataclasses.replace(base, result=result, records=base.records)
    ).candidates

    assert check(arm, "param_sets").status == "warn"
    # The rescore notices the stored stats no longer match the samples, which is a failure.
    assert check(arm, "rescore").status == "fail"


def test_param_set_contradiction_is_reported_without_rescore() -> None:
    base = inputs()
    secondary = base.config.param_sets[1].name
    result = _with_stats(base.result, secondary, 0.5, 0.8)

    from querycure.audit.checks import param_set_check

    out = param_set_check(base.config, result, base.result.verdicts[0].arm, {}, "verified")
    assert out.status == "fail"
    assert secondary in out.detail


def _verified_index_inputs() -> AuditInputs:
    """stale_stats samples relabelled as an index candidate (digests recomputed)."""
    base = inputs()
    arm = base.config.candidates[0].model_copy(
        update={"kind": "create_index", "ddl": ["CREATE INDEX ON purchases (status)"]}
    )
    config = base.config.model_copy(update={"candidates": [arm]})
    cid = base.candidates[arm.arm].id
    return dataclasses.replace(
        base,
        config=config,
        candidates={arm.arm: CandidateFacts(arm.arm, cid, "create_index", sql_digest(arm))},
        approval=dataclasses.replace(  # type: ignore[type-var]
            base.approval, digests={arm.arm: sql_digest(arm)}
        ),
    )


def _plan(node_type: str, index: str | None = None) -> Any:
    body: dict[str, Any] = {
        "Node Type": node_type,
        "Relation Name": "purchases",
        "Actual Total Time": 1.0,
        "Actual Rows": 1,
        "Actual Loops": 1,
    }
    if index:
        body["Index Name"] = index
    return parse_plan([{"Plan": body, "Execution Time": 1.0}])


def test_verified_index_that_the_plan_never_uses_is_downgraded() -> None:
    base = _verified_index_inputs()
    arm = base.config.candidates[0].arm
    plans = {
        (who, ps.name): _plan("Seq Scan")
        for who in ("baseline", arm)
        for ps in base.config.param_sets
    }

    [audit] = audit_experiment(dataclasses.replace(base, plans=plans)).candidates

    assert check(audit, "plan_change").status == "fail"
    assert audit.verdict == "inconclusive"


def test_verified_index_used_in_the_plan_passes() -> None:
    base = _verified_index_inputs()
    arm = base.config.candidates[0].arm
    plans: dict[tuple[str, str], Any] = {}
    for ps in base.config.param_sets:
        plans[("baseline", ps.name)] = _plan("Seq Scan")
        plans[(arm, ps.name)] = _plan("Index Scan", "purchases_status_idx")

    [audit] = audit_experiment(dataclasses.replace(base, plans=plans)).candidates

    assert check(audit, "plan_change").status == "pass"
    assert "purchases_status_idx" in check(audit, "plan_change").detail
    assert audit.verdict == "verified"


def test_index_plans_missing_skip_the_plan_check() -> None:
    [audit] = audit_experiment(_verified_index_inputs()).candidates

    assert check(audit, "plan_change").status == "skip"
    assert audit.verdict == "verified"


def _replicated(base: AuditInputs, verdict: str) -> AuditInputs:
    arm = base.config.candidates[0].arm
    noisy = base.result.model_copy(
        update={
            "verdicts": [
                RuleVerdict(
                    arm=arm,
                    verdict="inconclusive",
                    reasons=[Reason(code="insufficient_evidence", detail="noisy")],
                    gate=4,
                )
            ],
            "winner": None,
        }
    )
    replication = ReplicationResult(
        engine_version="bench@1",
        source_experiment_id=base.config.experiment_id,
        replicates_required=3,
        verdicts=[
            ReplicationVerdict(
                arm=arm,
                verdict=verdict,  # type: ignore[arg-type]
                reasons=[],
                experiment_ids=[base.config.experiment_id, uuid.uuid4(), uuid.uuid4()],
                primary_param_set=base.config.param_sets[0].name,
                ci_low=1.2,
                ci_high=2.0,
                max_robust_cv=0.4,
            )
        ],
        winner=arm if verdict != "inconclusive" else None,
    )
    return dataclasses.replace(
        base,
        result=noisy,
        replication=replication,
        replicates=[(base.result, base.environment_digest), (base.result, "sha256:elsewhere")],
    )


def test_noise_warning_verdict_is_kept_with_warnings() -> None:
    base = inputs()
    noisy = _replicated(base, "verified_with_noise_warning")
    # The stored primary verdict differs from the samples here; only the replication matters.
    noisy = dataclasses.replace(noisy, records=base.records)

    assessment = audit_experiment(noisy)
    [arm] = assessment.candidates

    assert arm.engine_verdict == "verified_with_noise_warning"
    assert check(arm, "replication").status == "warn"
    assert "different environment" in check(arm, "replication").detail


def test_audited_never_upgrades() -> None:
    assert audited("inconclusive", doubt=False) == "inconclusive"
    assert audited("rejected", doubt=True) == "rejected"
    assert audited("verified", doubt=True) == "inconclusive"
    assert audited("verified_with_noise_warning", doubt=True) == "inconclusive"
    assert audited("verified", doubt=False) == "verified"


def test_assessment_is_deterministic() -> None:
    assert audit_experiment(inputs()).model_dump() == audit_experiment(inputs()).model_dump()
