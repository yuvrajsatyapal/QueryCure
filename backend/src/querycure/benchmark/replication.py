"""`verified_with_noise_warning` by agreement of independent experiments (ADR-0019 §3).

Pure and deterministic: no clock, no I/O, no LLM. A single noisy experiment keeps its
`inconclusive` verdict. An arm whose noise screen is eligible may be re-measured in two more
experiments, each with its own experiment id, seed (schedule and bootstrap draws) and fresh
clones. It is verified with a noise warning only if all three are comparable, each passes on
its own, and their primary-param-set CIs share a common intersection.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from querycure.benchmark.schedule import derive_seed
from querycure.benchmark.tournament import Contender, rank
from querycure.domain.benchmark import (
    ENGINE_VERSION,
    ExperimentConfig,
    ExperimentResult,
    NoiseScreen,
    Reason,
    ReasonCode,
    ReplicationResult,
    ReplicationVerdict,
    RuleVerdict,
    SpeedupStats,
)

REPLICATES = 3
_SEED_LIMIT = 2**53 - 1


@dataclass(frozen=True)
class Replicate:
    config: ExperimentConfig
    result: ExperimentResult


def replicate_config(config: ExperimentConfig, index: int, arms: Sequence[str]) -> ExperimentConfig:
    """The `index`-th replicate (1-based) of `config`, restricted to `arms`.

    Only the experiment id, the seed and the candidate list change: the same approved SQL,
    param sets and thresholds are measured again in new clones.
    """
    if index < 1:
        raise ValueError("replicate index starts at 1 (0 is the original experiment)")
    known = {c.arm for c in config.candidates}
    if not arms or not set(arms) <= known:
        raise ValueError(f"replicate arms must be candidates of the experiment: {list(arms)}")
    return config.model_copy(
        update={
            "experiment_id": uuid.uuid5(config.experiment_id, f"replicate:{index}"),
            "seed": derive_seed(config.seed, "replicate", index) % _SEED_LIMIT,
            "candidates": [c for c in config.candidates if c.arm in arms],
        }
    )


def _screen(result: ExperimentResult, arm: str) -> NoiseScreen | None:
    return next((s for s in result.noise_screens or [] if s.arm == arm), None)


def eligible_arms(result: ExperimentResult) -> list[str]:
    """Arms that may enter replication: no winner, and an eligible noise screen."""
    if result.winner is not None:
        return []
    return [s.arm for s in result.noise_screens or [] if s.eligible]


def _inconclusive(
    arm: str,
    reps: Sequence[Replicate],
    primary: str,
    code: ReasonCode,
    detail: str,
) -> ReplicationVerdict:
    return ReplicationVerdict(
        arm=arm,
        verdict="inconclusive",
        reasons=[Reason(code=code, detail=detail)],
        experiment_ids=[r.config.experiment_id for r in reps],
        primary_param_set=primary,
        ci_low=None,
        ci_high=None,
        max_robust_cv=None,
    )


def _comparability(arm: str, reps: Sequence[Replicate]) -> str | None:
    first = reps[0]
    arm_spec = next(c for c in first.config.candidates if c.arm == arm)
    for r in reps:
        if r.result.provenance != "measured":
            return "prerecorded evidence never counts as a replicate"
        if r.result.engine_version != ENGINE_VERSION:
            return f"replicate scored by {r.result.engine_version}, not {ENGINE_VERSION}"
    if len({r.config.experiment_id for r in reps}) != len(reps):
        return "replicates must be distinct experiments"
    if len({r.config.seed for r in reps}) != len(reps):
        return "replicates must use distinct seeds"
    for r in reps[1:]:
        c, f = r.config, first.config
        spec = next((x for x in c.candidates if x.arm == arm), None)
        mismatches = {
            "environment": r.result.environment_digest != first.result.environment_digest,
            "workload": c.workload_id != f.workload_id,
            "query": c.baseline_query != f.baseline_query,
            "param sets": c.param_sets != f.param_sets,
            "thresholds": (c.min_effect, c.max_regression, c.max_cv, c.max_error_rate)
            != (f.min_effect, f.max_regression, f.max_cv, f.max_error_rate),
            "sql": spec is None
            or (spec.kind, spec.ddl, spec.query) != (arm_spec.kind, arm_spec.ddl, arm_spec.query),
        }
        differing = [k for k, v in mismatches.items() if v]
        if differing:
            return f"replicates are not comparable ({', '.join(differing)} differ)"
    return None


def _passes_alone(
    rep: Replicate, verdict: RuleVerdict, stats: Sequence[SpeedupStats]
) -> str | None:
    screen = _screen(rep.result, verdict.arm)
    noisy_ok = (
        verdict.verdict == "inconclusive" and verdict.gate == 4 and bool(screen and screen.eligible)
    )
    if verdict.verdict != "verified" and not noisy_ok:
        code = verdict.reasons[0].code if verdict.reasons else "none"
        return (
            f"experiment {rep.config.experiment_id}: {verdict.verdict} at gate {verdict.gate} "
            f"({code}) without an eligible noise screen"
        )
    risky = [s.param_set for s in stats if s.ci_low < rep.config.max_regression]
    if risky:
        return f"experiment {rep.config.experiment_id}: possible regression on {', '.join(risky)}"
    return None


def assess_arm(arm: str, reps: Sequence[Replicate]) -> ReplicationVerdict:
    if not reps:
        raise ValueError("no replicates")
    primary = reps[0].config.param_sets[0].name
    present = [r for r in reps if any(v.arm == arm for v in r.result.verdicts)]
    if len(present) < REPLICATES:
        return _inconclusive(
            arm, present, primary, "insufficient_evidence",
            f"{len(present)} of {REPLICATES} independent experiments completed",
        )  # fmt: skip
    if (why := _comparability(arm, present)) is not None:
        return _inconclusive(arm, present, primary, "insufficient_evidence", why)
    lows: list[float] = []
    highs: list[float] = []
    spreads: list[float] = []
    noisy = False
    for r in present:
        verdict = next(v for v in r.result.verdicts if v.arm == arm)
        stats = [s for s in r.result.stats if s.arm == arm]
        if (why := _passes_alone(r, verdict, stats)) is not None:
            return _inconclusive(arm, present, primary, "insufficient_evidence", why)
        p = next((s for s in stats if s.param_set == primary), None)
        if p is None:
            return _inconclusive(
                arm, present, primary, "insufficient_evidence", f"no {primary} statistics"
            )
        lows.append(p.ci_low)
        highs.append(p.ci_high)
        screen = _screen(r.result, arm)
        noisy = noisy or verdict.verdict != "verified"
        if screen is not None and screen.max_robust_cv is not None:
            spreads.append(screen.max_robust_cv)
    if max(lows) > min(highs):
        return _inconclusive(
            arm, present, primary, "replicates_disagree",
            "primary CIs share no common value: "
            + ", ".join(f"[{lo:.3f}, {hi:.3f}]" for lo, hi in zip(lows, highs, strict=True)),
        )  # fmt: skip
    reasons = (
        [
            Reason(
                code="insufficient_evidence",
                detail=f"sample dispersion exceeded max_cv (robust CV up to "
                f"{max(spreads) if spreads else float('nan'):.2f}); verified by agreement of "
                f"{len(present)} independent experiments",
            )
        ]
        if noisy
        else []
    )
    return ReplicationVerdict(
        arm=arm,
        verdict="verified_with_noise_warning" if noisy else "verified",
        reasons=reasons,
        experiment_ids=[r.config.experiment_id for r in present],
        primary_param_set=primary,
        ci_low=min(lows),
        ci_high=max(highs),
        max_robust_cv=max(spreads) if spreads else None,
    )


def assess_all(reps: Sequence[Replicate]) -> ReplicationResult:
    """Every arm that entered replication (the second experiment's candidates)."""
    if len(reps) < 1:
        raise ValueError("no replicates")
    source = reps[0]
    arms = (
        [c.arm for c in reps[1].config.candidates]
        if len(reps) > 1
        else eligible_arms(source.result)
    )
    verdicts = [assess_arm(a, reps) for a in arms]
    specs = {c.arm: c for c in source.config.candidates}
    builds = {b.arm: b for b in source.result.builds}
    contenders = [
        Contender(
            arm=v.arm,
            verdict="verified" if v.verdict != "inconclusive" else "inconclusive",
            primary_ci_low=v.ci_low,
            kind=specs[v.arm].kind,
            index_size_bytes=builds[v.arm].index_size_bytes if v.arm in builds else 0,
            write_overhead=specs[v.arm].write_overhead,
        )
        for v in verdicts
    ]
    _, winner = rank(contenders)
    return ReplicationResult(
        source_experiment_id=source.config.experiment_id,
        replicates_required=REPLICATES,
        verdicts=verdicts,
        winner=winner,
    )
