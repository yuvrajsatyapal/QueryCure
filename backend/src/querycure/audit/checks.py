"""Benchmark Auditor: deterministic checks (T4.2, ADR-0009). Pure; never imports llm/agents.

The engine owns verdicts. The auditor re-reads everything the verdict depends on and looks
for reasons to doubt it:

- `rescore`      the persisted samples, re-scored with the experiment's own engine version,
                 give the stored verdicts and statistics (catches records changed after
                 scoring, or a scoring bug);
- `approval`     the approval was decided, names the candidate, and pins exactly the SQL the
                 experiment ran (candidate digest = approved digest = digest of the config arm);
- `config`       the experiment ran the baseline query and parameter sets the human saw;
- `environment`  the fingerprint is recorded and its digest matches the experiment and result;
- `provenance`   every sample is `measured` (prerecorded data never verifies a live run);
- `samples`      every parameter set has the configured number of samples (time budget cuts);
- `param_sets`   no parameter set contradicts the verdict (wholly slower somewhere);
- `dispersion`   robust CV within `max_cv` on both arms;
- `correctness`  the candidate returned the baseline's rows on every parameter set;
- `plan_change`  a verified index is actually used by the candidate's plans;
- `replication`  replicate experiments ran in the same environment (ADR-0019).

A `fail` on a verified (or verified-with-noise-warning) candidate downgrades it to
`inconclusive`. Nothing here can change a rejected or inconclusive verdict, and nothing can
upgrade (`domain.audit.audited`).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from querycure.benchmark.engine import BlockRecord, score, sql_digest
from querycure.benchmark.rules import MIN_SAMPLES
from querycure.domain.audit import (
    VERIFIED_VERDICTS,
    AuditAssessment,
    AuditCheck,
    AuditCheckName,
    AuditStatus,
    CandidateAudit,
    FinalVerdict,
    audited,
)
from querycure.domain.benchmark import (
    BASELINE_ARM,
    BuildResult,
    EnvironmentFingerprint,
    ExperimentConfig,
    ExperimentResult,
    ReplicationResult,
)
from querycure.plans.diff import diff_plans
from querycure.plans.models import PlanTree
from querycure.replay.canonical import canonical_json, to_canonical
from querycure.replay.digest import digest


@dataclass(frozen=True)
class ApprovalFacts:
    status: str
    approved_candidate_ids: frozenset[Any]
    digests: Mapping[str, str]  # candidate key -> sql_sha256 shown to the human
    baseline_query: str
    param_sets: list[dict[str, Any]]


@dataclass(frozen=True)
class CandidateFacts:
    key: str
    id: Any
    kind: str
    sql_sha256: str


@dataclass(frozen=True)
class AuditInputs:
    round: int
    config: ExperimentConfig
    result: ExperimentResult
    records: Sequence[BlockRecord]
    record_provenance: Sequence[str]
    environment: EnvironmentFingerprint | None
    environment_digest: str | None
    approval: ApprovalFacts | None
    candidates: Mapping[str, CandidateFacts]
    replication: ReplicationResult | None = None
    replicates: Sequence[tuple[ExperimentResult, str | None]] = ()
    plans: Mapping[tuple[str, str], PlanTree] = field(default_factory=dict)
    metric_ids: Mapping[tuple[str, str], str] = field(default_factory=dict)
    correctness_ids: Mapping[tuple[str, str], str] = field(default_factory=dict)


def _check(
    name: AuditCheckName, status: AuditStatus, detail: str = "", ids: Sequence[str] = ()
) -> AuditCheck:
    return AuditCheck(name=name, status=status, detail=detail[:500], evidence_ids=sorted(ids))


def records_from_result(config: ExperimentConfig, result: ExperimentResult) -> list[BlockRecord]:
    """Blocks as the engine persists them, rebuilt from a result's flattened samples (fixtures
    and tests). Failed samples are attached to the first block."""
    out = [
        BlockRecord(
            arm=b.arm,
            candidate_id=None,
            param_set="*",
            phase="build",
            block=0,
            index_size_bytes=b.index_size_bytes,
            index_build_ns=b.build_ns,
            build_error=None if b.ok else {"reason": b.reason or "", "detail": b.detail},
        )
        for b in result.builds
    ]
    size = config.block_size
    for m in result.measurements:
        fp = m.fingerprint
        count = max(1, -(-len(m.latencies_ns) // size))
        for i in range(count):
            out.append(
                BlockRecord(
                    arm=m.arm,
                    candidate_id=None,
                    param_set=m.param_set,
                    phase="measure",
                    block=i,
                    latencies_ns=m.latencies_ns[i * size : (i + 1) * size],
                    sample_errors=list(m.failures) if i == 0 else [],
                    rows_returned=fp.rows if fp else None,
                    result_fingerprint=fp.multiset if fp else None,
                    ordered_fingerprint=fp.ordered if fp else None,
                    truncated=fp.truncated if fp else False,
                )
            )
    return out


def _builds(records: Sequence[BlockRecord]) -> dict[str, BuildResult]:
    out: dict[str, BuildResult] = {}
    for r in records:
        if r.phase != "build" or r.arm in out:
            continue
        error = r.build_error
        reason = (error or {}).get("reason") or None
        out[r.arm] = BuildResult(
            arm=r.arm,
            ok=error is None,
            reason=reason if reason in ("ddl_failed", "constraint_violation") else None,  # type: ignore[arg-type]
            detail=(error or {}).get("detail", ""),
            index_size_bytes=r.index_size_bytes or 0,
            build_ns=r.index_build_ns or 0,
        )
    return out


def _rescored(inputs: AuditInputs) -> ExperimentResult | str:
    builds = _builds(inputs.records)
    missing = [c.arm for c in inputs.config.candidates if c.arm not in builds]
    if missing:
        return f"no persisted build row for {', '.join(missing)}"
    try:
        return score(
            inputs.config,
            builds,
            list(inputs.records),
            unique_keys={},
            env_digest=inputs.result.environment_digest,
            engine_version=inputs.result.engine_version,
            total=inputs.result.order_is_total,
        )
    except (ValueError, KeyError) as exc:
        return f"re-scoring failed: {exc}"


def rescore_check(
    inputs: AuditInputs, rescored: ExperimentResult | str, arm: str, ids: Sequence[str]
) -> AuditCheck:
    if isinstance(rescored, str):
        return _check("rescore", "fail", rescored, ids)
    stored = next(v for v in inputs.result.verdicts if v.arm == arm)
    again = next(v for v in rescored.verdicts if v.arm == arm)
    if stored != again:
        return _check(
            "rescore",
            "fail",
            f"stored verdict {stored.verdict} (gate {stored.gate}) but the persisted samples "
            f"give {again.verdict} (gate {again.gate}) under {inputs.result.engine_version}",
            ids,
        )
    stored_stats = [s for s in inputs.result.stats if s.arm == arm]
    if stored_stats != [s for s in rescored.stats if s.arm == arm]:
        return _check("rescore", "fail", "stored statistics differ from the samples", ids)
    return _check(
        "rescore",
        "pass",
        f"samples re-scored under {inputs.result.engine_version} reproduce the stored verdict",
        ids,
    )


def approval_check(inputs: AuditInputs, arm: str) -> AuditCheck:
    approval, candidate = inputs.approval, inputs.candidates.get(arm)
    if approval is None:
        return _check("approval", "fail", "no approval record for this experiment")
    if approval.status not in ("approved", "partially_approved"):
        return _check("approval", "fail", f"approval status is {approval.status}")
    if candidate is None or candidate.id not in approval.approved_candidate_ids:
        return _check("approval", "fail", f"{arm} is not among the approved candidates")
    config_arm = next(c for c in inputs.config.candidates if c.arm == arm)
    measured = sql_digest(config_arm)
    if not (approval.digests.get(arm) == candidate.sql_sha256 == measured):
        return _check(
            "approval", "fail", "the approved SQL digest differs from the SQL that was measured"
        )
    return _check("approval", "pass", f"approved SQL digest {measured[:12]}… matches the run")


def config_check(inputs: AuditInputs) -> AuditCheck:
    approval = inputs.approval
    if approval is None:
        return _check("config", "fail", "no approval to compare the configuration with")
    if inputs.config.baseline_query != approval.baseline_query:
        return _check("config", "fail", "the measured baseline query is not the approved one")
    config_sets = [p.model_dump() for p in inputs.config.param_sets]
    approved = [{**p, "edge_case": p.get("edge_case", False)} for p in approval.param_sets]
    if config_sets != approved:
        return _check("config", "fail", "the measured parameter sets are not the approved ones")
    return _check("config", "pass", "baseline query and parameter sets match the approval")


def environment_check(inputs: AuditInputs) -> AuditCheck:
    env = inputs.environment
    if env is None or inputs.environment_digest is None:
        return _check("environment", "fail", "no environment fingerprint was recorded")
    computed = digest("qc-json-v1", canonical_json(to_canonical(env)))
    if not (computed == inputs.environment_digest == inputs.result.environment_digest):
        return _check("environment", "fail", "environment digests disagree")
    return _check(
        "environment",
        "pass",
        f"PostgreSQL {env.pg_version}, {env.cpu_arch}, {env.container_runtime}",
    )


def provenance_check(inputs: AuditInputs) -> AuditCheck:
    kinds = {inputs.result.provenance, *inputs.record_provenance}
    if kinds != {"measured"}:
        return _check(
            "provenance",
            "fail",
            f"samples are labelled {', '.join(sorted(kinds))}; only measured samples count",
        )
    return _check("provenance", "pass", "all samples were measured in this run's sandbox")


def _arm_stats(result: ExperimentResult, arm: str) -> list[Any]:
    return [s for s in result.stats if s.arm == arm]


def samples_check(
    config: ExperimentConfig,
    result: ExperimentResult,
    arm: str,
    ids: Sequence[str],
    verdict: FinalVerdict,
) -> AuditCheck:
    stats = _arm_stats(result, arm)
    if not stats:
        return _check("samples", "skip", "no statistics (arm not measured)", ids)
    short = [
        f"{s.param_set} {label} n={summary.n}"
        for s in stats
        for label, summary in (("baseline", s.baseline), ("candidate", s.candidate))
        if summary.n < config.measured_runs
    ]
    tiny = any(min(s.baseline.n, s.candidate.n) < MIN_SAMPLES for s in stats)
    if tiny and verdict in VERIFIED_VERDICTS:
        return _check("samples", "fail", "fewer than the minimum samples: " + "; ".join(short), ids)
    if short:
        return _check(
            "samples",
            "warn",
            f"fewer than the configured {config.measured_runs} samples: " + "; ".join(short),
            ids,
        )
    return _check("samples", "pass", f"{config.measured_runs} samples per arm and set", ids)


def param_set_check(
    config: ExperimentConfig,
    result: ExperimentResult,
    arm: str,
    metric_ids: Mapping[tuple[str, str], str],
    verdict: FinalVerdict,
) -> AuditCheck:
    stats = _arm_stats(result, arm)
    ids = [metric_ids[(arm, s.param_set)] for s in stats if (arm, s.param_set) in metric_ids]
    if not stats:
        return _check("param_sets", "skip", "no statistics", ids)
    slower = [s.param_set for s in stats if s.ci_high < 1.0]
    flat = [s.param_set for s in stats if s.ci_low < 1.0 <= s.ci_high]
    if slower and verdict in VERIFIED_VERDICTS:
        return _check(
            "param_sets", "fail", "verified, yet wholly slower on " + ", ".join(slower), ids
        )
    if slower or flat:
        parts = []
        if slower:
            parts.append("slower on " + ", ".join(slower))
        if flat:
            parts.append("no demonstrated benefit on " + ", ".join(flat))
        return _check("param_sets", "warn", "; ".join(parts), ids)
    return _check("param_sets", "pass", "every parameter set's CI lies above 1", ids)


def dispersion_check(
    config: ExperimentConfig, result: ExperimentResult, arm: str, ids: Sequence[str]
) -> AuditCheck:
    stats = _arm_stats(result, arm)
    if not stats:
        return _check("dispersion", "skip", "no statistics", ids)
    noisy = [
        f"{s.param_set} {label} robust CV "
        + (f"{summary.robust_cv:.2f}" if summary.robust_cv is not None else "undefined")
        for s in stats
        for label, summary in (("baseline", s.baseline), ("candidate", s.candidate))
        if summary.robust_cv is None or summary.robust_cv > config.max_cv
    ]
    if noisy:
        return _check("dispersion", "warn", "above max_cv: " + "; ".join(noisy), ids)
    return _check("dispersion", "pass", f"robust CV within {config.max_cv} everywhere", ids)


def correctness_check(inputs: AuditInputs, arm: str, verdict: FinalVerdict) -> AuditCheck:
    by = {(m.arm, m.param_set): m for m in inputs.result.measurements}
    ids = [
        inputs.correctness_ids[(arm, p.name)]
        for p in inputs.config.param_sets
        if (arm, p.name) in inputs.correctness_ids
    ]
    differ, unknown = [], []
    for p in inputs.config.param_sets:
        base, cand = by.get((BASELINE_ARM, p.name)), by.get((arm, p.name))
        if base is None or cand is None or base.fingerprint is None or cand.fingerprint is None:
            unknown.append(p.name)
            continue
        if (base.fingerprint.rows, base.fingerprint.multiset) != (
            cand.fingerprint.rows,
            cand.fingerprint.multiset,
        ):
            differ.append(p.name)
    verified = verdict in VERIFIED_VERDICTS
    if differ:
        status: AuditStatus = "fail" if verified else "warn"
        return _check("correctness", status, "different rows on " + ", ".join(differ), ids)
    if unknown:
        status = "fail" if verified else "skip"
        return _check("correctness", status, "no fingerprint for " + ", ".join(unknown), ids)
    return _check("correctness", "pass", "same rows as the baseline on every set", ids)


def plan_check(inputs: AuditInputs, arm: str, kind: str, verdict: FinalVerdict) -> AuditCheck:
    if verdict not in VERIFIED_VERDICTS or kind not in ("create_index", "query_rewrite"):
        return _check("plan_change", "skip", "not applicable")
    used: dict[str, list[str]] = {}
    unchanged: list[str] = []
    for p in inputs.config.param_sets:
        before, after = inputs.plans.get((BASELINE_ARM, p.name)), inputs.plans.get((arm, p.name))
        if before is None or after is None:
            continue
        diff = diff_plans(before, after).summary
        used[p.name] = diff.new_indexes_used
        if diff.added == diff.removed == diff.changed == 0:
            unchanged.append(p.name)
    if not used:
        return _check("plan_change", "skip", "no captured plans for this arm")
    if kind == "query_rewrite":
        if len(unchanged) == len(used):
            return _check("plan_change", "warn", "the rewrite left every plan unchanged")
        return _check("plan_change", "pass", "the rewrite changed the plan")
    names = sorted({i for v in used.values() for i in v})
    without = [ps for ps, v in used.items() if not v]
    if not names:
        return _check(
            "plan_change",
            "fail",
            "no captured candidate plan uses a new index; the speed-up "
            "is not explained by the candidate",
        )
    if without:
        return _check(
            "plan_change",
            "warn",
            f"new index {', '.join(names)} used, but not on {', '.join(without)}",
        )
    return _check("plan_change", "pass", f"new index used: {', '.join(names)}")


def replication_check(inputs: AuditInputs, arm: str) -> AuditCheck:
    replication = inputs.replication
    verdict = next((v for v in replication.verdicts if v.arm == arm), None) if replication else None
    if verdict is None:
        return _check("replication", "skip", "not replicated")
    notes = [f"{len(verdict.experiment_ids)} independent experiment(s)"]
    status: AuditStatus = "pass"
    elsewhere = [
        d for _, d in inputs.replicates if d is not None and d != inputs.environment_digest
    ]
    if elsewhere:
        status = "warn"
        notes.append(f"{len(elsewhere)} replicate(s) ran in a different environment")
    if verdict.verdict == "verified_with_noise_warning":
        status = "warn"
        notes.append("noisy measurements; verified only by agreement across experiments")
    return _check("replication", status, "; ".join(notes))


def audit_experiment(inputs: AuditInputs) -> AuditAssessment:
    config, result = inputs.config, inputs.result
    rescored = _rescored(inputs)
    replicated = {v.arm: v for v in (inputs.replication.verdicts if inputs.replication else [])}
    shared = [config_check(inputs), environment_check(inputs), provenance_check(inputs)]
    audits: list[CandidateAudit] = []
    for rule in result.verdicts:
        arm = rule.arm
        engine: FinalVerdict = replicated[arm].verdict if arm in replicated else rule.verdict
        kind = next(c.kind for c in config.candidates if c.arm == arm)
        ids = sorted(
            inputs.metric_ids[(arm, p.name)]
            for p in config.param_sets
            if (arm, p.name) in inputs.metric_ids
        )
        checks = [
            rescore_check(inputs, rescored, arm, ids),
            approval_check(inputs, arm),
            *shared,
            samples_check(config, result, arm, ids, engine),
            param_set_check(config, result, arm, inputs.metric_ids, engine),
            dispersion_check(config, result, arm, ids),
            correctness_check(inputs, arm, engine),
            plan_check(inputs, arm, kind, engine),
            replication_check(inputs, arm),
        ]
        failed = [f"{c.name}: {c.detail}" for c in checks if c.status == "fail"]
        verdict = audited(engine, doubt=bool(failed))
        audits.append(
            CandidateAudit(
                arm=arm,
                candidate_id=inputs.candidates[arm].id if arm in inputs.candidates else None,
                engine_verdict=engine,
                verdict=verdict,
                checks=checks,
                downgrade_reasons=failed if verdict != engine else [],
            )
        )
    return AuditAssessment(
        experiment_id=config.experiment_id,
        round=inputs.round,
        engine_version=result.engine_version,
        candidates=audits,
        winner=pick_winner(result, inputs.replication, {a.arm: a.verdict for a in audits}),
    )


def pick_winner(
    result: ExperimentResult,
    replication: ReplicationResult | None,
    verdicts: Mapping[str, str],
) -> str | None:
    """The engine's preference order, restricted to arms still verified after the audit."""
    order = [
        a for a in (result.winner, replication.winner if replication else None) if a is not None
    ] + [t.arm for t in result.tournament]
    return next((a for a in order if verdicts.get(a) in VERIFIED_VERDICTS), None)
