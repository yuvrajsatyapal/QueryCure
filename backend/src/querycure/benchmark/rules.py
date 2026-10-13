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

Versions (ADR-0019). `bench@1` is frozen exactly as above, so stored bench@1 experiments can be
re-scored by their own rules. `bench@2` changes two things:
- gate 5 rejects only a *corroborated* regression (n >= 20, no failed baseline sample, every
  block below max_regression); a regression that is only indicated is inconclusive at gate 5,
  never verified;
- an arm stopped only by gate 4b gets a noise screen (`NoiseScreen`). It never changes the
  verdict; eligibility only admits the arm to replication (benchmark.replication).
"""

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from querycure.benchmark.correctness import CorrectnessOutcome
from querycure.benchmark.schedule import derive_seed
from querycure.benchmark.stats import bootstrap_speedup_ci, speedup, summarize
from querycure.domain.benchmark import (
    ENGINE_VERSION,
    ENGINE_VERSIONS,
    ArmMeasurement,
    BuildResult,
    CandidateArm,
    ExperimentConfig,
    LatencySummary,
    NoiseCheck,
    NoiseScreen,
    Reason,
    ReasonCode,
    RuleVerdict,
    SpeedupStats,
    Verdict,
)

MIN_SAMPLES = 10
REWRITE_MIN_PARAM_SETS = 3
# bench@2 (ADR-0019). Below 20 a median CI is coarse (ADR-0008); 3 blocks give a sign test.
REGRESSION_MIN_SAMPLES = 20
REGRESSION_MIN_BLOCKS = 3
NOISE_MIN_SAMPLES = 30
NOISE_MIN_BLOCKS = 4

# One interleaved block of a param set: (baseline samples, candidate samples).
BlockPair = tuple[Sequence[int], Sequence[int]]


@dataclass(frozen=True)
class CandidateEvidence:
    arm: CandidateArm
    build: BuildResult
    baseline: Mapping[str, ArmMeasurement]  # by param set
    candidate: Mapping[str, ArmMeasurement]
    correctness: Mapping[str, CorrectnessOutcome]
    # Per param set, measured blocks in order. Required by bench@2's block checks; when absent
    # those checks fail closed.
    blocks: Mapping[str, Sequence[BlockPair]] = field(default_factory=dict)


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


def _block_ratios(ev: CandidateEvidence, ps: str) -> list[float]:
    """median(baseline block) / median(candidate block) for blocks holding both arms."""
    return [
        float(statistics.median(b)) / float(statistics.median(c))
        for b, c in ev.blocks.get(ps, ())
        if b and c and statistics.median(c) > 0
    ]


def _regression_corroboration(
    ev: CandidateEvidence, ps: str, s: SpeedupStats, max_regression: float
) -> str | None:
    """None when an indicated regression is decisive; otherwise why it is not (ADR-0019 §1)."""
    for label, summary in (("baseline", s.baseline), ("candidate", s.candidate)):
        if summary.n < REGRESSION_MIN_SAMPLES:
            return f"{label} n={summary.n} < {REGRESSION_MIN_SAMPLES}"
    if ev.baseline[ps].failures:
        return f"baseline lost {len(ev.baseline[ps].failures)} sample(s) to failures (censored)"
    ratios = _block_ratios(ev, ps)
    if len(ratios) < REGRESSION_MIN_BLOCKS:
        return f"{len(ratios)} measured block(s) < {REGRESSION_MIN_BLOCKS}"
    # A block counts only when it is itself below max_regression: with a no-difference block the
    # ratio is a coin flip around 1.0, so "< 1.0" would corroborate half of all disturbances.
    unconfirmed = sum(1 for r in ratios if r >= max_regression)
    if unconfirmed:
        return (
            f"block ratio >= {max_regression} in {unconfirmed} of {len(ratios)} blocks "
            f"(max {max(ratios):.3f})"
        )
    return None


def _gate5_v2(
    ev: CandidateEvidence, config: ExperimentConfig, stats: Mapping[str, SpeedupStats]
) -> RuleVerdict | None:
    arm = ev.arm.arm
    uncorroborated: list[str] = []
    for ps in config.param_sets:
        s = stats[ps.name]
        if s.ci_high >= config.max_regression:
            continue
        why = _regression_corroboration(ev, ps.name, s, config.max_regression)
        if why is None:
            return _result(
                arm,
                "rejected",
                5,
                "regression",
                f"{ps.name}: speedup CI upper {s.ci_high:.3f} < {config.max_regression}, "
                f"below {config.max_regression} in every block",
            )
        uncorroborated.append(f"{ps.name}: CI upper {s.ci_high:.3f} but {why}")
    if uncorroborated:
        return _result(
            arm,
            "inconclusive",
            5,
            "insufficient_evidence",
            "regression indicated, not corroborated: " + "; ".join(uncorroborated),
        )
    return None


def _quartiles(samples: Sequence[int]) -> tuple[float, float]:
    q1, _, q3 = statistics.quantiles(sorted(samples), n=4, method="inclusive")
    return q1, q3


def noise_screen(
    ev: CandidateEvidence, config: ExperimentConfig, stats: Mapping[str, SpeedupStats]
) -> NoiseScreen:
    """ADR-0019 §2. Every check is computed (no short circuit) so the report can show all."""
    names = [p.name for p in config.param_sets]
    primary = names[0]
    checks: list[NoiseCheck] = []

    small = [
        f"{ps} {label} n={summary.n}"
        for ps in names
        for label, summary in (("baseline", stats[ps].baseline), ("candidate", stats[ps].candidate))
        if summary.n < NOISE_MIN_SAMPLES
    ]
    few_blocks = [
        f"{ps} {len(_block_ratios(ev, ps))} blocks"
        for ps in names
        if len(_block_ratios(ev, ps)) < NOISE_MIN_BLOCKS
    ]
    checks.append(
        NoiseCheck(
            name="n",
            passed=not small and not few_blocks,
            detail="; ".join(small + few_blocks)
            or f"n >= {NOISE_MIN_SAMPLES} and >= {NOISE_MIN_BLOCKS} blocks",
        )
    )
    censored = [
        f"{ps} {label} {len(m.failures)}"
        for ps in names
        for label, m in (("baseline", ev.baseline[ps]), ("candidate", ev.candidate[ps]))
        if m.failures
    ]
    checks.append(
        NoiseCheck(name="censor", passed=not censored,
                   detail="; ".join(censored) or "no failed samples")
    )  # fmt: skip
    risky = [f"{ps} CI low {stats[ps].ci_low:.3f}" for ps in names
             if stats[ps].ci_low < config.max_regression]  # fmt: skip
    checks.append(
        NoiseCheck(
            name="noregress",
            passed=not risky,
            detail="; ".join(risky) or f"every CI lower bound >= {config.max_regression}",
        )
    )
    p = stats[primary]
    checks.append(
        NoiseCheck(
            name="effect",
            passed=p.ci_low >= config.min_effect,
            detail=f"{primary} CI low {p.ci_low:.3f} vs {config.min_effect}",
        )
    )
    base_q1, _ = _quartiles(ev.baseline[primary].latencies_ns)
    _, cand_q3 = _quartiles(ev.candidate[primary].latencies_ns)
    checks.append(
        NoiseCheck(
            name="separation",
            passed=cand_q3 * config.min_effect <= base_q1,
            detail=f"{primary}: candidate Q3 {cand_q3:.0f} ns x {config.min_effect} vs "
            f"baseline Q1 {base_q1:.0f} ns",
        )
    )
    ratios = _block_ratios(ev, primary)
    weak = sum(1 for r in ratios if r < config.min_effect)
    checks.append(
        NoiseCheck(
            name="blocks",
            passed=bool(ratios) and weak == 0,
            detail=f"{primary}: {len(ratios) - weak} of {len(ratios)} blocks >= "
            f"{config.min_effect}" + (f" (min {min(ratios):.3f})" if ratios else ""),
        )
    )
    spreads = [
        x
        for ps in names
        for x in (stats[ps].baseline.robust_cv, stats[ps].candidate.robust_cv)
        if x is not None
    ]
    return NoiseScreen(
        arm=ev.arm.arm,
        eligible=all(c.passed for c in checks),
        checks=checks,
        max_robust_cv=max(spreads) if spreads else None,
    )


def evaluate(
    ev: CandidateEvidence,
    config: ExperimentConfig,
    stats: Mapping[str, SpeedupStats],
    *,
    query_has_params: bool,
    engine_version: str = ENGINE_VERSION,
) -> RuleVerdict:
    return assess(
        ev, config, stats, query_has_params=query_has_params, engine_version=engine_version
    )[0]


def assess(
    ev: CandidateEvidence,
    config: ExperimentConfig,
    stats: Mapping[str, SpeedupStats],
    *,
    query_has_params: bool,
    engine_version: str = ENGINE_VERSION,
) -> tuple[RuleVerdict, NoiseScreen | None]:
    """The verdict, plus the noise screen when bench@2 stopped the arm at gate 4b only."""
    if engine_version not in ENGINE_VERSIONS:
        raise ValueError(f"unknown benchmark engine version {engine_version!r}")
    v2 = engine_version == "bench@2"
    arm = ev.arm.arm
    if not ev.build.ok:
        return _result(arm, "rejected", 1, ev.build.reason or "ddl_failed", ev.build.detail), None
    if (detail := _gate2(ev, config)) is not None:
        return _result(arm, "inconclusive", 2, "unstable_execution", detail), None
    if (g3 := _gate3(ev, config, query_has_params)) is not None:
        return _result(arm, g3[0], 3, g3[1], g3[2]), None
    # Gate 4a: the sample-count floor. Below it a bootstrap CI means nothing.
    for ps in config.param_sets:
        s = stats.get(ps.name)
        if s is None:
            return _result(
                arm, "inconclusive", 4, "insufficient_evidence", f"{ps.name}: no samples"
            ), None
        for label, summary in (("baseline", s.baseline), ("candidate", s.candidate)):
            if summary.n < MIN_SAMPLES:
                return _result(
                    arm,
                    "inconclusive",
                    4,
                    "insufficient_evidence",
                    f"{ps.name}: {label} n={summary.n}",
                ), None
    # Gate 5 before the dispersion check (ADR-0018): noise independent of the arm only widens
    # the CI. bench@2 also requires the regression to be corroborated (ADR-0019 §1).
    if v2:
        if (g5 := _gate5_v2(ev, config, stats)) is not None:
            return g5, None
    else:
        for ps in config.param_sets:
            s = stats[ps.name]
            if s.ci_high < config.max_regression:
                return _result(
                    arm,
                    "rejected",
                    5,
                    "regression",
                    f"{ps.name}: speedup CI upper {s.ci_high:.3f} < {config.max_regression}",
                ), None
    # Gate 4b: dispersion. It guards every conclusion that needs precision (verified,
    # no_improvement).
    for ps in config.param_sets:
        s = stats[ps.name]
        for label, summary in (("baseline", s.baseline), ("candidate", s.candidate)):
            spread = summary.robust_cv
            if spread is None or spread > config.max_cv:
                verdict = _result(
                    arm,
                    "inconclusive",
                    4,
                    "insufficient_evidence",
                    f"{ps.name}: {label} robust CV {spread:.2f} > {config.max_cv}"
                    if spread is not None
                    else f"{ps.name}: {label} dispersion undefined",
                )
                return verdict, noise_screen(ev, config, stats) if v2 else None
    primary = stats[config.param_sets[0].name]
    if primary.ci_low >= config.min_effect:
        return RuleVerdict(arm=arm, verdict="verified", gate=None, reasons=[]), None
    if primary.ci_high < 1.0:
        return _result(
            arm,
            "rejected",
            6,
            "no_improvement",
            f"speedup CI [{primary.ci_low:.3f}, {primary.ci_high:.3f}]",
        ), None
    return _result(
        arm,
        "inconclusive",
        6,
        "effect_not_significant",
        f"speedup CI [{primary.ci_low:.3f}, {primary.ci_high:.3f}] vs required {config.min_effect}",
    ), None
