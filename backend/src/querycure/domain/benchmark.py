"""Experiment models (BENCHMARK_ENGINE §1). Configs and results are stored as qc-json-v1
artifacts, so every field is always present and raw samples are integer nanoseconds."""

import statistics
import uuid
from collections.abc import Sequence
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

JsonScalar = str | int | float | bool | None
CandidateKind = Literal[
    "create_index", "query_rewrite", "analyze_statistics", "extended_statistics"
]
WriteOverhead = Literal["low", "medium", "high", "unknown"]
Verdict = Literal["verified", "rejected", "inconclusive"]
ReasonCode = Literal[
    "ddl_failed",
    "constraint_violation",
    "unstable_execution",
    "result_mismatch",
    "nondeterministic_order",
    "result_too_large",
    "insufficient_evidence",
    "regression",
    "effect_not_significant",
    "no_improvement",
    "not_measured",
    "replicates_disagree",
]
BASELINE_ARM = "baseline"
# bench@2 (ADR-0019): corroborated regressions and the noise screen. bench@1 rules stay frozen
# in benchmark.rules so stored bench@1 experiments can be re-scored by their own rules.
ENGINE_VERSION = "bench@2"
ENGINE_VERSIONS = ("bench@1", "bench@2")
# Result schema per engine version: schema 2 adds `noise_screens`.
RESULT_SCHEMA = {"bench@1": 1, "bench@2": 2}
# Simpler changes win ties in the tournament (BENCHMARK_ENGINE §8).
SIMPLICITY = {
    "analyze_statistics": 0,
    "extended_statistics": 1,
    "create_index": 2,
    "query_rewrite": 3,
}


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ParamSetSpec(Frozen):
    name: str = Field(pattern=r"^[A-Za-z0-9_\-]{1,40}$")
    values: list[JsonScalar] = Field(max_length=32)
    edge_case: bool = False  # NULL-bearing or empty-result set (required for rewrites)


class CandidateArm(Frozen):
    arm: str = Field(pattern=r"^oc_[0-9a-f]{12}$")  # the candidate key
    candidate_id: uuid.UUID | None
    kind: CandidateKind
    ddl: list[str] = Field(max_length=4)
    query: str | None  # rewrites only; otherwise the baseline query runs on this arm's clone
    write_overhead: WriteOverhead = "unknown"


class ExperimentConfig(Frozen):
    schema_version: Literal[1] = 1
    experiment_id: uuid.UUID
    workload_id: str
    baseline_query: str
    candidates: list[CandidateArm] = Field(min_length=1, max_length=4)
    param_sets: list[ParamSetSpec] = Field(min_length=1, max_length=5)
    warmup_runs: int = Field(default=5, ge=0, le=50)
    measured_runs: int = Field(default=30, ge=10, le=200)
    block_size: int = Field(default=5, ge=1, le=50)
    query_timeout_ms: int = Field(default=10_000, ge=100, le=120_000)
    max_index_bytes: int | None = None
    max_build_ms: int | None = Field(default=120_000, ge=100)
    min_effect: float = Field(default=1.10, gt=1.0)
    max_regression: float = Field(default=0.95, gt=0.0, le=1.0)
    max_cv: float = Field(default=0.25, gt=0.0)
    max_error_rate: float = Field(default=0.10, ge=0.0, lt=1.0)
    row_hash_cap: int = Field(default=100_000, ge=1)
    seed: int = Field(ge=0, le=2**53 - 1)
    cache_mode: Literal["warm"] = "warm"


class EnvironmentFingerprint(Frozen):
    pg_version: str
    pg_settings: dict[str, str]
    sandbox_image_digest: str
    workload_id: str
    workload_data_digest: str
    row_profile: Literal["qc-row-v1"] = "qc-row-v1"
    cpu_arch: str
    cpu_model: str
    cpu_count: int
    memory_bytes: int
    os: str
    container_runtime: str
    autovacuum_disabled_on_clones: bool = True


class BuildResult(Frozen):
    arm: str
    ok: bool
    reason: Literal["ddl_failed", "constraint_violation"] | None = None
    detail: str = ""
    index_size_bytes: int = 0
    build_ns: int = 0


class ArmFingerprint(Frozen):
    rows: int
    multiset: str
    ordered: str
    truncated: bool


class ArmMeasurement(Frozen):
    """All measured samples of one arm under one param set (collected across blocks)."""

    arm: str
    param_set: str
    latencies_ns: list[int]
    failures: list[Literal["timeout", "error"]]
    fingerprint: ArmFingerprint | None  # None when no execution succeeded
    consistent: bool  # every successful execution returned the same fingerprint
    plan_sha256: str | None = None


class LatencySummary(Frozen):
    n: int
    median_ns: float
    p95_ns: int | None
    min_ns: int
    max_ns: int
    iqr_ns: float
    cv: float | None
    robust_cv: float | None


class SpeedupStats(Frozen):
    arm: str
    param_set: str
    baseline: LatencySummary
    candidate: LatencySummary
    speedup: float
    ci_low: float
    ci_high: float


class Reason(Frozen):
    code: ReasonCode
    detail: str = ""


class RuleVerdict(Frozen):
    arm: str
    verdict: Verdict
    reasons: list[Reason]
    gate: int | None  # first failing gate (1-6); None when verified


NoiseCheckName = Literal["n", "censor", "noregress", "effect", "separation", "blocks"]


class NoiseCheck(Frozen):
    name: NoiseCheckName
    passed: bool
    detail: str = ""


class NoiseScreen(Frozen):
    """D11 (ADR-0019 §2): recorded for an arm stopped only by gate 4b. Never changes the verdict;
    `eligible` admits the arm to replication."""

    arm: str
    eligible: bool
    checks: list[NoiseCheck]
    max_robust_cv: float | None


class TournamentEntry(Frozen):
    arm: str
    rank: int
    verdict: Verdict
    primary_ci_low: float | None


# A floor at or above half the fastest arm's median means the measurement is mostly transport
# and harness: speed-ups are compressed toward 1 and sub-ms dispersion is mostly network.
TRANSPORT_DOMINATED_SHARE = 0.5


class TransportFloor(Frozen):
    """Round trips of a bare `SELECT 1` on the baseline arm's connection, before warm-up and
    after measurement (BENCHMARK_ENGINE §4 step 7). It is the part of every timed sample that
    is network, relay and driver rather than query. Diagnostic only: samples, statistics and
    verdicts never use it, and nothing is subtracted."""

    samples: int
    before_median_ns: float | None
    after_median_ns: float | None
    median_ns: float
    iqr_ns: float
    share_of_fastest_arm: float | None
    transport_dominated: bool


def transport_floor(
    *, before: Sequence[int], after: Sequence[int], arm_medians_ns: Sequence[float]
) -> TransportFloor:
    both = [*before, *after]
    if not both:
        raise ValueError("a transport floor needs at least one sample")
    ordered = sorted(both)
    q1, _, q3 = (
        statistics.quantiles(ordered, n=4, method="inclusive")
        if len(ordered) >= 2
        else (ordered[0],) * 3
    )
    median = float(statistics.median(ordered))
    fastest = min((m for m in arm_medians_ns if m > 0), default=None)
    share = median / fastest if fastest else None
    return TransportFloor(
        samples=len(both),
        before_median_ns=float(statistics.median(before)) if before else None,
        after_median_ns=float(statistics.median(after)) if after else None,
        median_ns=median,
        iqr_ns=float(q3 - q1),
        share_of_fastest_arm=round(share, 4) if share is not None else None,
        transport_dominated=share is not None and share >= TRANSPORT_DOMINATED_SHARE,
    )


class ExperimentResult(Frozen):
    schema_version: Literal[1, 2] = 2
    experiment_id: uuid.UUID
    engine_version: str = ENGINE_VERSION
    environment_digest: str
    builds: list[BuildResult]
    measurements: list[ArmMeasurement]
    stats: list[SpeedupStats]
    verdicts: list[RuleVerdict]
    tournament: list[TournamentEntry]
    winner: str | None
    order_is_total: bool
    provenance: Literal["measured", "prerecorded"] = "measured"
    # Schema 2 (bench@2) only. None on schema-1 results and then omitted, so a stored bench@1
    # result re-serializes to its original bytes and digest (ADR-0019 § Compatibility).
    noise_screens: list[NoiseScreen] | None = Field(default=None, exclude_if=lambda v: v is None)
    # Recorded since 2026-10-18 beside bench@2 (ADR-0029); omitted when None, so every stored
    # result re-serializes to its original bytes.
    transport_floor: TransportFloor | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="before")
    @classmethod
    def _schema_default(cls, data: Any) -> Any:
        # Stored results always carry schema_version; new ones follow their engine version.
        if not isinstance(data, dict):
            return data
        engine = data.get("engine_version", ENGINE_VERSION)
        schema = data.get("schema_version", RESULT_SCHEMA.get(engine, 2))
        out = {**data, "schema_version": schema}
        if schema == 2 and out.get("noise_screens") is None:
            out["noise_screens"] = []
        return out

    @model_validator(mode="after")
    def _versions_agree(self) -> Self:
        if RESULT_SCHEMA.get(self.engine_version) != self.schema_version:
            raise ValueError(
                f"result schema {self.schema_version} does not match {self.engine_version}"
            )
        if self.schema_version == 1 and self.noise_screens is not None:
            raise ValueError("noise_screens require result schema 2 (bench@2)")
        return self


ReplicationLabel = Literal["verified", "verified_with_noise_warning", "inconclusive"]


class ReplicationVerdict(Frozen):
    """One candidate across independent experiments (ADR-0019 §3)."""

    arm: str
    verdict: ReplicationLabel
    reasons: list[Reason]
    experiment_ids: list[uuid.UUID]
    primary_param_set: str
    ci_low: float | None  # smallest primary lower bound across replicates
    ci_high: float | None  # largest primary upper bound
    max_robust_cv: float | None


class ReplicationResult(Frozen):
    schema_version: Literal[1] = 1
    engine_version: str = ENGINE_VERSION
    source_experiment_id: uuid.UUID
    replicates_required: int
    verdicts: list[ReplicationVerdict]
    winner: str | None
