"""Deterministic verdict gates (BENCHMARK_ENGINE §7, ADR-0009). No LLM, no clock, no I/O.

Gates run in order and the first failure sets the verdict:
1. DDL applied and constraints met        → rejected (ddl_failed | constraint_violation)
2. Failures (timeouts, shared errors) ≤ max_error_rate on both arms
                                            → inconclusive (unstable_execution)
3. Correctness on every param set          → rejected (result_mismatch) or
                                              inconclusive (nondeterministic_order |
                                              result_too_large | insufficient_evidence for
                                              under-tested rewrites)
4a. n ≥ 10 on both arms                    → inconclusive (insufficient_evidence)
5. CI upper ≥ max_regression everywhere     → rejected (regression)
4b. robust CV ≤ max_cv on both arms          → inconclusive (insufficient_evidence)
   (robust CV = IQR / (1.349 · median); 5 runs before 4b, ADR-0018)
6. Primary CI lower ≥ min_effect            → inconclusive (effect_not_significant), or
                                              rejected (no_improvement) when CI upper < 1.0

Error parity sits in gate 3: errors the baseline does not have mean the candidate is wrong,
not noisy, so they are excluded from gate 2's failure rate.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from querycure.benchmark.correctness import CorrectnessOutcome
from querycure.benchmark.schedule import derive_seed
from querycure.benchmark.stats import bootstrap_speedup_ci, speedup, summarize
from querycure.domain.benchmark import (
    ArmMeasurement,
    BuildResult,
    CandidateArm,
    ExperimentConfig,
    LatencySummary,
    Reason,
    ReasonCode,
    RuleVerdict,
    SpeedupStats,
    Verdict,
)

MIN_SAMPLES = 10
REWRITE_MIN_PARAM_SETS = 3


@dataclass(frozen=True)
class CandidateEvidence:
    arm: CandidateArm
    build: BuildResult
    baseline: Mapping[str, ArmMeasurement]  # by param set
    candidate: Mapping[str, ArmMeasurement]
    correctness: Mapping[str, CorrectnessOutcome]


def _summary(samples: list[int]) -> LatencySummary:
    s = summarize(samples)
    return LatencySummary(
        n=s.n,
        median_ns=s.median_ns,
        p95_ns=s.p95_ns,
        min_ns=s.min_ns,
        max_ns=s.max_ns,
        iqr_ns=s.iqr_ns,
        cv=s.cv,
        robust_cv=s.robust_cv,
    )


def compute_stats(ev: CandidateEvidence, config: ExperimentConfig) -> dict[str, SpeedupStats]:
    """Per param set; skipped where either arm has no successful sample."""
    stats: dict[str, SpeedupStats] = {}
    for ps in config.param_sets:
        base, cand = ev.baseline.get(ps.name), ev.candidate.get(ps.name)
        if base is None or cand is None or not base.latencies_ns or not cand.latencies_ns:
            continue
        low, high = bootstrap_speedup_ci(
            base.latencies_ns,
            cand.latencies_ns,
            seed=derive_seed(config.seed, "bootstrap", ev.arm.arm, ps.name),
        )
        stats[ps.name] = SpeedupStats(
            arm=ev.arm.arm,
            param_set=ps.name,
            baseline=_summary(base.latencies_ns),
            candidate=_summary(cand.latencies_ns),
            speedup=speedup(base.latencies_ns, cand.latencies_ns),
            ci_low=low,
            ci_high=high,
        )
    return stats


def _result(arm: str, verdict: Verdict, gate: int, code: ReasonCode, detail: str) -> RuleVerdict:
    return RuleVerdict(
        arm=arm, verdict=verdict, gate=gate, reasons=[Reason(code=code, detail=detail)]
    )


def _failure_rate(m: ArmMeasurement, count_errors: bool) -> float:
    attempts = len(m.latencies_ns) + len(m.failures)
    failed = sum(1 for f in m.failures if f == "timeout" or count_errors)
    return failed / attempts if attempts else 1.0


def _gate2(ev: CandidateEvidence, config: ExperimentConfig) -> str | None:
    for ps in config.param_sets:
        base, cand = ev.baseline.get(ps.name), ev.candidate.get(ps.name)
        if base is None or cand is None:
            return f"{ps.name}: not measured"
        baseline_errors = "error" in base.failures
        for label, m in (("baseline", base), ("candidate", cand)):
            # Candidate-only errors are an error-parity failure (gate 3), not noise.
            rate = _failure_rate(m, count_errors=label == "baseline" or baseline_errors)
            if rate > config.max_error_rate:
                return f"{ps.name}: {label} failed {rate:.0%} of executions"
    return None


def _gate3(
    ev: CandidateEvidence, config: ExperimentConfig, query_has_params: bool
) -> tuple[Verdict, ReasonCode, str] | None:
    inconclusive: tuple[Verdict, ReasonCode, str] | None = None
    for ps in config.param_sets:
        base, cand = ev.baseline[ps.name], ev.candidate[ps.name]
        if "error" in cand.failures and "error" not in base.failures:
            return (
                "rejected",
                "result_mismatch",
                f"{ps.name}: candidate errors where baseline does not",
            )
        outcome = ev.correctness.get(ps.name)
        if outcome is None:
            inconclusive = inconclusive or (
                "inconclusive",
                "insufficient_evidence",
                f"{ps.name}: unchecked",
            )
        elif outcome.status == "mismatch":
            return "rejected", "result_mismatch", f"{ps.name}: {outcome.detail}"
        elif outcome.status == "inconclusive" and inconclusive is None:
            code: ReasonCode = outcome.reason or "insufficient_evidence"  # type: ignore[assignment]
            inconclusive = ("inconclusive", code, f"{ps.name}: {outcome.detail}")
    if inconclusive is not None:
        return inconclusive
    if ev.arm.kind == "query_rewrite" and query_has_params:
        enough = len(config.param_sets) >= REWRITE_MIN_PARAM_SETS
        if not enough or not any(ps.edge_case for ps in config.param_sets):
            return (
                "inconclusive",
                "insufficient_evidence",
                "a rewrite needs >= 3 param sets including an edge case (NULL or empty result)",
            )
    return None


def evaluate(
    ev: CandidateEvidence,
    config: ExperimentConfig,
    stats: Mapping[str, SpeedupStats],
    *,
    query_has_params: bool,
) -> RuleVerdict:
    arm = ev.arm.arm
    if not ev.build.ok:
        return _result(arm, "rejected", 1, ev.build.reason or "ddl_failed", ev.build.detail)
    if (detail := _gate2(ev, config)) is not None:
        return _result(arm, "inconclusive", 2, "unstable_execution", detail)
    if (g3 := _gate3(ev, config, query_has_params)) is not None:
        return _result(arm, g3[0], 3, g3[1], g3[2])
    # Gate 4a: the sample-count floor. Below it a bootstrap CI means nothing.
    for ps in config.param_sets:
        s = stats.get(ps.name)
        if s is None:
            return _result(
                arm, "inconclusive", 4, "insufficient_evidence", f"{ps.name}: no samples"
            )
        for label, summary in (("baseline", s.baseline), ("candidate", s.candidate)):
            if summary.n < MIN_SAMPLES:
                return _result(
                    arm,
                    "inconclusive",
                    4,
                    "insufficient_evidence",
                    f"{ps.name}: {label} n={summary.n}",
                )
    # Gate 5 before the dispersion check (ADR-0018): noise only widens the CI, so a CI entirely
    # below max_regression is real harm and is reported however noisy the other samples are.
    for ps in config.param_sets:
        s = stats[ps.name]
        if s.ci_high < config.max_regression:
            return _result(
                arm,
                "rejected",
                5,
                "regression",
                f"{ps.name}: speedup CI upper {s.ci_high:.3f} < {config.max_regression}",
            )
    # Gate 4b: dispersion. It guards every conclusion that needs precision (verified,
    # no_improvement).
    for ps in config.param_sets:
        s = stats[ps.name]
        for label, summary in (("baseline", s.baseline), ("candidate", s.candidate)):
            spread = summary.robust_cv
            if spread is None or spread > config.max_cv:
                return _result(
                    arm,
                    "inconclusive",
                    4,
                    "insufficient_evidence",
                    f"{ps.name}: {label} robust CV {spread:.2f} > {config.max_cv}"
                    if spread is not None
                    else f"{ps.name}: {label} dispersion undefined",
                )
    primary = stats[config.param_sets[0].name]
    if primary.ci_low >= config.min_effect:
        return RuleVerdict(arm=arm, verdict="verified", gate=None, reasons=[])
    if primary.ci_high < 1.0:
        return _result(
            arm,
            "rejected",
            6,
            "no_improvement",
            f"speedup CI [{primary.ci_low:.3f}, {primary.ci_high:.3f}]",
        )
    return _result(
        arm,
        "inconclusive",
        6,
        "effect_not_significant",
        f"speedup CI [{primary.ci_low:.3f}, {primary.ci_high:.3f}] vs required {config.min_effect}",
    )
