"""Original vs replay experiment comparison (REPLAY_ENGINE §9). Pure and seeded.

Per candidate and parameter set ("pair"), from the raw integer samples of both experiments:
1. correctness: result fingerprints must match exactly (baseline and candidate);
2. evidence quality: gate 4 (n ≥ 10, robust CV ≤ max_cv) on both sides, else inconclusive;
3. drift D = S_replay / S_original with S = median(baseline) / median(candidate), and a
   percentile-bootstrap 95% CI (all four sample sets resampled independently, 2,000 times,
   seed from sha256(original | replay));
4. classification against the equivalence margin m (default 1.25) and the two verdicts.
The attempt status is the most severe pair; a changed tournament winner is `not_reproduced`.

Absolute latencies are reported side by side and never classify. `comparison_mode` (same vs
cross environment) only changes the wording, never the algorithm (§9.2).
"""

import hashlib
import math
import random
import statistics
from collections.abc import Sequence
from typing import Any, Literal

from querycure.benchmark.rules import MIN_SAMPLES
from querycure.benchmark.stats import summarize
from querycure.domain.benchmark import (
    BASELINE_ARM,
    ArmMeasurement,
    EnvironmentFingerprint,
    ExperimentConfig,
    ExperimentResult,
    RuleVerdict,
)

DEFAULT_MARGIN = 1.25  # D9: ±25% drift in the speed-up ratio
DEFAULT_RESAMPLES = 2_000
PairStatus = Literal["reproduced", "reproduced_with_drift", "inconclusive", "not_reproduced"]
SEVERITY: dict[str, int] = {
    "reproduced": 0,
    "reproduced_with_drift": 1,
    "inconclusive": 2,
    "not_reproduced": 3,
}
PLANNER_SETTINGS = (
    "shared_buffers",
    "work_mem",
    "effective_cache_size",
    "random_page_cost",
    "seq_page_cost",
    "jit",
    "max_parallel_workers_per_gather",
    "default_statistics_target",
)
LIMITATIONS = [
    "Coverage: two experiments are a small sample of environmental variance; reproduced means "
    "consistent in this pair of runs, not portable.",
    "Multiple comparisons: no correction across candidates and parameter sets; the worst pair "
    "decides instead.",
    "Resampling ignores the block pairing within each experiment (ADR-0008).",
    "The margin and bootstrap settings are stored with the result; changing defaults never "
    "changes stored results.",
]


def comparison_seed(original_id: str, replay_id: str) -> int:
    """52 bits of sha256(original | replay): stored in the result, so it must stay within the
    canonical JSON integer range (±(2^53 - 1))."""
    return int(hashlib.sha256(f"{original_id}|{replay_id}".encode()).hexdigest()[:13], 16)


def _resample(rng: random.Random, values: Sequence[int]) -> list[int]:
    n = len(values)
    return [values[int(rng.random() * n)] for _ in range(n)]


def drift_ci(
    orig_base: Sequence[int],
    orig_cand: Sequence[int],
    rep_base: Sequence[int],
    rep_cand: Sequence[int],
    *,
    seed: int,
    resamples: int = DEFAULT_RESAMPLES,
) -> tuple[float, float]:
    rng = random.Random(seed)  # noqa: S311 - reproducibility, not secrecy

    def s(base: Sequence[int], cand: Sequence[int]) -> float:
        return float(statistics.median(_resample(rng, base))) / float(
            statistics.median(_resample(rng, cand))
        )

    ratios = sorted(s(rep_base, rep_cand) / s(orig_base, orig_cand) for _ in range(resamples))
    low = ratios[math.floor(0.025 * resamples)]
    high = ratios[math.ceil(0.975 * resamples) - 1]
    return low, high


def _quality(m: ArmMeasurement | None, max_cv: float) -> str | None:
    """Gate 4 for one arm: None when fine, else why not."""
    if m is None or len(m.latencies_ns) < MIN_SAMPLES:
        return f"n={0 if m is None else len(m.latencies_ns)}"
    rcv = summarize(m.latencies_ns).robust_cv
    if rcv is None or rcv > max_cv:
        return "robust CV " + ("undefined" if rcv is None else f"{rcv:.2f}")
    return None


def _same_print(a: ArmMeasurement | None, b: ArmMeasurement | None) -> bool:
    if a is None or b is None or a.fingerprint is None or b.fingerprint is None:
        return False
    return (a.fingerprint.rows, a.fingerprint.multiset, a.fingerprint.ordered) == (
        b.fingerprint.rows,
        b.fingerprint.multiset,
        b.fingerprint.ordered,
    )


def _primary_code(v: RuleVerdict) -> str | None:
    return v.reasons[0].code if v.reasons else None


def _major(pg_version: str) -> str:
    return pg_version[:-4] if pg_version.isdigit() and len(pg_version) > 4 else pg_version


def _minor(pg_version: str) -> str:
    return pg_version[-4:] if pg_version.isdigit() and len(pg_version) > 4 else ""


def classify_environment(
    original: EnvironmentFingerprint,
    replay: EnvironmentFingerprint,
    *,
    original_engine: str,
    replay_engine: str,
) -> list[dict[str, Any]]:
    """Every differing field with its class (REPLAY_ENGINE §9.3). `container_runtime` holds the
    measurement path since ADR-0020 (round trips about ten times apart), so it is material."""
    o, r = original, replay
    fields: list[tuple[str, str, Any, Any]] = [
        ("workload_id", "precondition", o.workload_id, r.workload_id),
        ("workload_data_digest", "precondition", o.workload_data_digest, r.workload_data_digest),
        ("row_profile", "precondition", o.row_profile, r.row_profile),
        ("pg_major_version", "material", _major(o.pg_version), _major(r.pg_version)),
        ("sandbox_image_digest", "material", o.sandbox_image_digest, r.sandbox_image_digest),
        ("benchmark_engine_version", "material", original_engine, replay_engine),
        ("cpu_arch", "material", o.cpu_arch, r.cpu_arch),
        ("cpu_model", "material", o.cpu_model, r.cpu_model),
        ("cpu_count", "material", o.cpu_count, r.cpu_count),
        ("memory_bytes", "material", o.memory_bytes, r.memory_bytes),
        ("container_runtime", "material", o.container_runtime, r.container_runtime),
        ("pg_minor_version", "minor", _minor(o.pg_version), _minor(r.pg_version)),
        ("os", "minor", o.os, r.os),
    ]
    for name in sorted(set(o.pg_settings) | set(r.pg_settings)):
        cls = "material" if name in PLANNER_SETTINGS else "minor"
        fields.append(
            (f"pg_settings.{name}", cls, o.pg_settings.get(name), r.pg_settings.get(name))
        )
    return [{"field": f, "class": c, "original": a, "replay": b} for f, c, a, b in fields if a != b]


def compare_experiments(
    *,
    original_id: str,
    replay_id: str,
    config: ExperimentConfig,
    original: ExperimentResult,
    replay: ExperimentResult,
    original_env: EnvironmentFingerprint,
    replay_env: EnvironmentFingerprint,
    original_env_digest: str | None,
    replay_env_digest: str | None,
    replay_engine: str,
    margin: float = DEFAULT_MARGIN,
    resamples: int = DEFAULT_RESAMPLES,
) -> dict[str, Any]:
    seed = comparison_seed(original_id, replay_id)
    differences = classify_environment(
        original_env,
        replay_env,
        original_engine=original.engine_version,
        replay_engine=replay_engine,
    )
    base = {
        "comparison_mode": "cross_environment"
        if any(d["class"] == "material" for d in differences)
        else "same_environment",
        "config": {"margin": margin, "resamples": resamples, "confidence": 0.95, "seed": seed},
        "environment": {
            "original": original_env.model_dump(mode="json"),
            "replay": replay_env.model_dump(mode="json"),
            "original_digest": original_env_digest,
            "replay_digest": replay_env_digest,
            "differences": differences,
        },
        "limitations": LIMITATIONS,
    }
    preconditions = [d for d in differences if d["class"] == "precondition"]
    if preconditions:
        code = (
            "unsupported_row_profile"
            if any(d["field"] == "row_profile" for d in preconditions)
            else "workload_snapshot_changed"
        )
        return {
            **base,
            "status": "not_replayable",
            "failure_code": code,
            "pairs": [],
            "winner": {"original": original.winner, "replay": replay.winner},
        }
    built = {b.arm: b.ok for b in original.builds}
    rebuilt = {b.arm: b.ok for b in replay.builds}
    broken = sorted(a for a, ok in built.items() if ok and not rebuilt.get(a, False))
    if broken:
        return {
            **base,
            "status": "failed",
            "failure_code": "ddl_failed",
            "pairs": [],
            "detail": "DDL failed in the replay for " + ", ".join(broken),
            "winner": {"original": original.winner, "replay": replay.winner},
        }

    o_meas = {(m.arm, m.param_set): m for m in original.measurements}
    r_meas = {(m.arm, m.param_set): m for m in replay.measurements}
    o_verdicts = {v.arm: v for v in original.verdicts}
    r_verdicts = {v.arm: v for v in replay.verdicts}
    o_stats = {(s.arm, s.param_set): s for s in original.stats}
    r_stats = {(s.arm, s.param_set): s for s in replay.stats}
    pairs: list[dict[str, Any]] = []
    for arm in config.candidates:
        ov, rv = o_verdicts.get(arm.arm), r_verdicts.get(arm.arm)
        for p in config.param_sets:
            key = (arm.arm, p.name)
            os_, rs = o_stats.get(key), r_stats.get(key)
            pair: dict[str, Any] = {
                "arm": arm.arm,
                "param_set": p.name,
                "original_verdict": ov.verdict if ov else None,
                "replay_verdict": rv.verdict if rv else None,
                "original_speedup": os_.speedup if os_ else None,
                "replay_speedup": rs.speedup if rs else None,
                "original_ci": [os_.ci_low, os_.ci_high] if os_ else None,
                "replay_ci": [rs.ci_low, rs.ci_high] if rs else None,
                "original_medians_ns": [os_.baseline.median_ns, os_.candidate.median_ns]
                if os_
                else None,
                "replay_medians_ns": [rs.baseline.median_ns, rs.candidate.median_ns]
                if rs
                else None,
                "drift": None,
                "drift_ci_low": None,
                "drift_ci_high": None,
            }
            pair_status, pair_code = _classify_pair(
                arm.arm,
                p.name,
                o_meas,
                r_meas,
                ov,
                rv,
                os_,
                rs,
                config,
                margin,
                pair,
                seed=seed,
                resamples=resamples,
            )
            pairs.append({**pair, "status": pair_status, "code": pair_code})
    worst = max(pairs, key=lambda x: SEVERITY[x["status"]], default=None)
    status = worst["status"] if worst else "inconclusive"
    failure = worst["code"] if worst and worst["status"] != "reproduced" else None
    replay_first = replay.tournament[0].arm if replay.tournament else None
    if original.winner is not None and replay_first != original.winner:
        status, failure = "not_reproduced", "winner_changed"
    return {
        **base,
        "status": status,
        "failure_code": failure,
        "pairs": pairs,
        "winner": {"original": original.winner, "replay": replay.winner},
    }


def _classify_pair(
    arm: str,
    ps: str,
    o_meas: dict[tuple[str, str], ArmMeasurement],
    r_meas: dict[tuple[str, str], ArmMeasurement],
    ov: RuleVerdict | None,
    rv: RuleVerdict | None,
    os_: Any,
    rs: Any,
    config: ExperimentConfig,
    margin: float,
    pair: dict[str, Any],
    *,
    seed: int,
    resamples: int,
) -> tuple[PairStatus, str | None]:
    for who in (BASELINE_ARM, arm):
        if not _same_print(o_meas.get((who, ps)), r_meas.get((who, ps))):
            return "not_reproduced", "result_fingerprint_changed"
    # Drift is computed whenever every arm has samples (diagnostic); it classifies only after
    # the evidence-quality gate below.
    sides = [m.get((who, ps)) for m in (o_meas, r_meas) for who in (BASELINE_ARM, arm)]
    if all(x is not None and x.latencies_ns for x in sides):
        ob, oc = o_meas[(BASELINE_ARM, ps)], o_meas[(arm, ps)]
        rb, rc = r_meas[(BASELINE_ARM, ps)], r_meas[(arm, ps)]
        s_o = float(statistics.median(ob.latencies_ns)) / float(statistics.median(oc.latencies_ns))
        s_r = float(statistics.median(rb.latencies_ns)) / float(statistics.median(rc.latencies_ns))
        low, high = drift_ci(
            ob.latencies_ns,
            oc.latencies_ns,
            rb.latencies_ns,
            rc.latencies_ns,
            seed=seed ^ hash_pair(arm, ps),
            resamples=resamples,
        )
        pair.update({"drift": s_r / s_o, "drift_ci_low": low, "drift_ci_high": high})
    for side in (o_meas, r_meas):
        for who in (BASELINE_ARM, arm):
            if _quality(side.get((who, ps)), config.max_cv) is not None:
                return "inconclusive", "insufficient_evidence"
    if ov is None or rv is None:
        return "inconclusive", "insufficient_evidence"
    if {ov.verdict, rv.verdict} == {"verified", "rejected"} or (
        ov.verdict == rv.verdict == "rejected" and _primary_code(ov) != _primary_code(rv)
    ):
        return "not_reproduced", "verdict_changed"
    if (
        os_ is not None
        and rs is not None
        and ((os_.ci_low > 1.0 and rs.ci_high < 1.0) or (os_.ci_high < 1.0 and rs.ci_low > 1.0))
    ):
        return "not_reproduced", "direction_reversed"
    if "inconclusive" in (ov.verdict, rv.verdict):
        return "inconclusive", "verdict_inconclusive"
    if ov.verdict != rv.verdict or _primary_code(ov) != _primary_code(rv):
        return "not_reproduced", "verdict_changed"
    if 1 / margin <= low and high <= margin:
        return "reproduced", None
    if high < 1 / margin or low > margin:
        return "reproduced_with_drift", None
    return "inconclusive", "drift_undetermined"


def hash_pair(arm: str, ps: str) -> int:
    """Per-pair seed offset, so pairs do not share a random stream."""
    return int(hashlib.sha256(f"{arm}|{ps}".encode()).hexdigest()[:8], 16)
