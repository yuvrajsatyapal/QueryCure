"""Experiment execution (BENCHMARK_ENGINE §2-§8): provision → build → warm → measure →
capture plans → check → score. Pure deterministic Python; never imports `llm` or `agents`.

Runs synchronously in one worker thread. Persistence and progress go through `EngineHooks`
(the caller bridges them to the metadata DB), so this module is testable against a real
sandbox with in-memory hooks.

Safety properties enforced here, not only upstream:
- every candidate is re-validated against the DDL allowlist before any clone exists;
- the caller must pass an `ApprovedExperiment` naming exactly the arms whose SQL a human
  approved (by SQL digest); unapproved arms raise before provisioning;
- clones are dropped and the lease released in every terminal state (success, failure,
  cancellation), and each lease starts by dropping orphans of crashed runs;
- cancellation is checked between blocks and also interrupts the in-flight statement.
"""

import dataclasses
import hashlib
import os
import platform
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from querycure.benchmark.correctness import (
    CorrectnessOutcome,
    Fingerprint,
    compare_results,
    order_is_total,
)
from querycure.benchmark.executor import ArmRunner, Sample, buffers_of
from querycure.benchmark.replication import (
    REPLICATES,
    Replicate,
    assess_all,
    eligible_arms,
    replicate_config,
)
from querycure.benchmark.rules import BlockPair, CandidateEvidence, assess, compute_stats
from querycure.benchmark.schedule import build_schedule
from querycure.benchmark.tournament import Contender, rank
from querycure.core.errors import QueryCureError, RunCancelledError, SandboxPolicyError
from querycure.core.logging import get_logger
from querycure.domain.benchmark import (
    BASELINE_ARM,
    ENGINE_VERSION,
    RESULT_SCHEMA,
    ArmFingerprint,
    ArmMeasurement,
    BuildResult,
    CandidateArm,
    EnvironmentFingerprint,
    ExperimentConfig,
    ExperimentResult,
    NoiseScreen,
    ReplicationResult,
    RuleVerdict,
    SpeedupStats,
    TransportFloor,
    transport_floor,
)
from querycure.replay.canonical import canonical_json, to_canonical
from querycure.replay.digest import digest
from querycure.sandbox.provisioner import SandboxProvisioner
from querycure.sql.ddl_allowlist import AllowedDdl, validate_candidate
from querycure.sql.validator import validate_select
from querycure.workloads.registry import WorkloadRef

log = get_logger(__name__)
INCONSISTENT = "inconsistent"
FLOOR_SAMPLES = 25  # per window (before warm-up, after measurement); about 2-20 ms in total
Phase = Literal["build", "measure", "plan"]
State = Literal[
    "provisioning", "building", "warming", "measuring", "capturing_plans", "checking", "scoring"
]


@dataclass(frozen=True)
class BlockRecord:
    """One append-only `benchmark_runs` row."""

    arm: str
    candidate_id: str | None
    param_set: str
    phase: Phase
    block: int
    latencies_ns: list[int] = field(default_factory=list)
    sample_errors: list[str] = field(default_factory=list)
    rows_returned: int | None = None
    result_fingerprint: str | None = None
    ordered_fingerprint: str | None = None
    truncated: bool = False
    plan: dict[str, Any] | None = None
    buffers: dict[str, int] | None = None
    index_size_bytes: int | None = None
    index_build_ns: int | None = None
    build_error: dict[str, str] | None = None

    @property
    def key(self) -> tuple[str, str, str, int]:
        return (self.arm, self.param_set, self.phase, self.block)


class EngineHooks(Protocol):
    def existing(self) -> list[BlockRecord]: ...
    def persist(self, record: BlockRecord) -> None: ...
    def progress(self, state: State, **details: Any) -> None: ...
    def environment(self, env: EnvironmentFingerprint, env_digest: str) -> None: ...
    def cancelled(self) -> bool: ...


@dataclass(frozen=True)
class ApprovedExperiment:
    """Arms a human approved, each pinned to the SHA-256 of its exact SQL (sql_digest)."""

    approval_request_id: str
    approved_sql: Mapping[str, str]  # arm -> sha256


def sql_digest(arm: CandidateArm) -> str:
    """Digest of exactly what will run for an arm: its DDL list and rewritten query."""
    body = canonical_json({"ddl": list(arm.ddl), "kind": arm.kind, "query": arm.query})
    return hashlib.sha256(body).hexdigest()


class ApprovalMismatchError(SandboxPolicyError):
    code = "APPROVAL_REQUIRED"
    status = 409


@dataclass(frozen=True)
class EngineOptions:
    lease_timeout_seconds: float = 120.0
    time_budget_seconds: float = 8 * 60
    sandbox_image_digest: str = "unrecorded"
    # Measurement path (ADR-0020): "docker-network" (worker container on sandbox_net) or
    # "docker-relay" (host worker through the loopback relay). Recorded in the fingerprint.
    container_runtime: str = "docker"
    # Test seam only: called inside the timed region of each measured sample.
    noise: Callable[[], None] | None = None
    # Test seam only: like `noise`, but told (arm, param set, block), so tests can inject a
    # disturbance that hits one arm in some blocks (the "misleadingly narrow CI" cases).
    arm_noise: Callable[[str, str, int], None] | None = None


def _host_memory_bytes() -> int:
    try:
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except (ValueError, OSError, AttributeError):
        return 0


def environment_fingerprint(
    *,
    pg_version: str,
    pg_settings: dict[str, str],
    workload_id: str,
    data_digest: str,
    options: EngineOptions,
) -> EnvironmentFingerprint:
    # Hardware fields describe the host running the worker; Docker Desktop's VM may differ.
    return EnvironmentFingerprint(
        pg_version=pg_version,
        pg_settings=pg_settings,
        sandbox_image_digest=options.sandbox_image_digest,
        workload_id=workload_id,
        workload_data_digest=data_digest,
        cpu_arch=platform.machine() or "unknown",
        cpu_model=platform.processor() or "unknown",
        cpu_count=os.cpu_count() or 0,
        memory_bytes=_host_memory_bytes(),
        os=f"{platform.system()} {platform.release()}",
        container_runtime=options.container_runtime,
    )


def _noise_for(
    options: EngineOptions, arm: str, param_set: str, block: int
) -> Callable[[], None] | None:
    hooks = [h for h in (options.noise,) if h is not None]
    if options.arm_noise is not None:
        arm_noise = options.arm_noise
        hooks.append(lambda: arm_noise(arm, param_set, block))
    if not hooks:
        return None

    def run() -> None:
        for h in hooks:
            h()

    return run


def _check_cancel(hooks: EngineHooks) -> None:
    if hooks.cancelled():
        raise RunCancelledError("Experiment cancelled.")


class _Cancellation:
    """Polls hooks.cancelled() from a side thread and interrupts in-flight statements."""

    def __init__(self, hooks: EngineHooks, runners: Sequence[ArmRunner], interval: float = 0.25):
        self._hooks, self._runners, self._interval = hooks, runners, interval
        self._stop = threading.Event()
        self.fired = False
        self._thread = threading.Thread(target=self._watch, daemon=True)

    def _watch(self) -> None:
        while not self._stop.wait(self._interval):
            if self._hooks.cancelled():
                self.fired = True
                for runner in self._runners:
                    runner.cancel()
                return

    def __enter__(self) -> "_Cancellation":
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=5)


def _validate(
    config: ExperimentConfig, approved: ApprovedExperiment
) -> dict[str, list[AllowedDdl]]:
    validate_select(config.baseline_query)
    ddl: dict[str, list[AllowedDdl]] = {}
    for arm in config.candidates:
        expected = approved.approved_sql.get(arm.arm)
        if expected is None or expected != sql_digest(arm):
            raise ApprovalMismatchError(
                f"Arm {arm.arm} has no approval for exactly this SQL; nothing was executed."
            )
        validated = validate_candidate(
            kind=arm.kind, ddl=list(arm.ddl), query=arm.query, baseline=config.baseline_query
        )
        ddl[arm.arm] = validated.ddl
    return ddl


def _fingerprint(samples: Sequence[Sample]) -> tuple[Fingerprint | None, bool]:
    prints = {s.fingerprint for s in samples if s.fingerprint is not None}
    if not prints:
        return None, True
    if len(prints) > 1:
        return None, False
    return next(iter(prints)), True


def _block_record(
    arm: CandidateArm | None, param_set: str, block: int, samples: Sequence[Sample]
) -> BlockRecord:
    fp, consistent = _fingerprint(samples)
    return BlockRecord(
        arm=arm.arm if arm else BASELINE_ARM,
        candidate_id=str(arm.candidate_id) if arm and arm.candidate_id else None,
        param_set=param_set,
        phase="measure",
        block=block,
        latencies_ns=[s.latency_ns for s in samples if s.latency_ns is not None],
        sample_errors=[s.failure for s in samples if s.failure is not None],
        rows_returned=fp.rows if fp else None,
        result_fingerprint=fp.multiset if fp else (None if consistent else INCONSISTENT),
        ordered_fingerprint=fp.ordered if fp else (None if consistent else INCONSISTENT),
        truncated=fp.truncated if fp else False,
    )


def assemble(
    records: Sequence[BlockRecord], arms: Sequence[str], param_sets: Sequence[str]
) -> dict[tuple[str, str], ArmMeasurement]:
    """Fold persisted measure rows (possibly from several attempts) into measurements."""
    grouped: dict[tuple[str, str], list[BlockRecord]] = defaultdict(list)
    for r in records:
        if r.phase == "measure":
            grouped[(r.arm, r.param_set)].append(r)
    out: dict[tuple[str, str], ArmMeasurement] = {}
    for arm in arms:
        for ps in param_sets:
            rows = sorted(grouped.get((arm, ps), []), key=lambda r: r.block)
            prints = {
                (r.rows_returned, r.result_fingerprint, r.ordered_fingerprint, r.truncated)
                for r in rows
                if r.result_fingerprint is not None
            }
            consistent = len(prints) <= 1 and not any(
                r.result_fingerprint == INCONSISTENT for r in rows
            )
            fingerprint = None
            if consistent and prints:
                rows_returned, multiset, ordered, truncated = next(iter(prints))
                fingerprint = ArmFingerprint(
                    rows=rows_returned or 0, multiset=multiset or "", ordered=ordered or "",
                    truncated=truncated,
                )  # fmt: skip
            failures = [f for r in rows for f in r.sample_errors if f in ("timeout", "error")]
            out[(arm, ps)] = ArmMeasurement(
                arm=arm,
                param_set=ps,
                latencies_ns=[x for r in rows for x in r.latencies_ns],
                failures=failures,  # type: ignore[arg-type]
                fingerprint=fingerprint,
                consistent=consistent,
            )
    return out


def assemble_blocks(records: Sequence[BlockRecord], arm: str, param_set: str) -> list[BlockPair]:
    """Interleaved blocks of one candidate vs the baseline, in block order (ADR-0019)."""
    by_block: dict[int, dict[str, list[int]]] = defaultdict(dict)
    for r in records:
        if r.phase == "measure" and r.param_set == param_set and r.arm in (BASELINE_ARM, arm):
            by_block[r.block][r.arm] = list(r.latencies_ns)
    return [(by_block[b].get(BASELINE_ARM, []), by_block[b].get(arm, [])) for b in sorted(by_block)]


def _correctness(
    base: ArmMeasurement, cand: ArmMeasurement, *, has_order: bool, has_limit: bool, total: bool
) -> CorrectnessOutcome:
    if not base.consistent or not cand.consistent:
        who = "baseline" if not base.consistent else "candidate"
        return CorrectnessOutcome(
            "inconclusive", "nondeterministic_order", f"{who} results vary between executions"
        )
    if base.fingerprint is None or cand.fingerprint is None:
        return CorrectnessOutcome("inconclusive", "insufficient_evidence", "no successful run")

    def fp(a: ArmFingerprint) -> Fingerprint:
        return Fingerprint(
            rows=a.rows, multiset=a.multiset, ordered=a.ordered, truncated=a.truncated
        )

    return compare_results(
        fp(base.fingerprint), fp(cand.fingerprint), has_order=has_order, has_limit=has_limit,
        total=total,
    )  # fmt: skip


def score(
    config: ExperimentConfig,
    builds: Mapping[str, BuildResult],
    records: Sequence[BlockRecord],
    *,
    unique_keys: Mapping[str, Sequence[Sequence[str]]],
    env_digest: str,
    engine_version: str = ENGINE_VERSION,
    total: bool | None = None,
    floor_samples: tuple[Sequence[int], Sequence[int]] | None = None,
) -> ExperimentResult:
    """Correctness → stats → gates → tournament, from persisted rows only (resumable).

    `engine_version` selects the rules; a stored experiment is re-scored with its own.
    `total` replaces the order-totality proof (which needs the sandbox's unique keys) with a
    stored value: the Benchmark Auditor re-scores from persisted rows without a sandbox."""
    meta = validate_select(config.baseline_query).metadata
    if total is None:
        total = order_is_total(config.baseline_query, unique_keys)
    has_order, has_limit = bool(meta.order_by), meta.limit is not None
    ps_names = [p.name for p in config.param_sets]
    arms = [BASELINE_ARM, *(c.arm for c in config.candidates)]
    measured = assemble(records, arms, ps_names)
    verdicts: list[RuleVerdict] = []
    stats: list[SpeedupStats] = []
    screens: list[NoiseScreen] = []
    contenders: list[Contender] = []
    for arm in config.candidates:
        base = {ps: measured[(BASELINE_ARM, ps)] for ps in ps_names}
        cand = {ps: measured[(arm.arm, ps)] for ps in ps_names}
        evidence = CandidateEvidence(
            arm=arm,
            build=builds[arm.arm],
            baseline=base,
            candidate=cand,
            correctness={
                ps: _correctness(base[ps], cand[ps], has_order=has_order, has_limit=has_limit,
                                 total=total)
                for ps in ps_names
            },
            blocks={ps: assemble_blocks(records, arm.arm, ps) for ps in ps_names},
        )  # fmt: skip
        arm_stats = compute_stats(evidence, config)
        verdict, screen = assess(
            evidence, config, arm_stats, query_has_params=meta.parameter_count > 0,
            engine_version=engine_version,
        )  # fmt: skip
        verdicts.append(verdict)
        if screen is not None:
            screens.append(screen)
        stats.extend(arm_stats[ps] for ps in ps_names if ps in arm_stats)
        primary = arm_stats.get(ps_names[0])
        contenders.append(
            Contender(
                arm=arm.arm,
                verdict=verdict.verdict,
                primary_ci_low=primary.ci_low if primary else None,
                kind=arm.kind,
                index_size_bytes=builds[arm.arm].index_size_bytes,
                write_overhead=arm.write_overhead,
            )
        )
    table, winner = rank(contenders)
    floor: TransportFloor | None = None
    if floor_samples is not None and (floor_samples[0] or floor_samples[1]):
        medians = [m.median_ns for s in stats for m in (s.baseline, s.candidate) if m.median_ns > 0]
        floor = transport_floor(
            before=floor_samples[0], after=floor_samples[1], arm_medians_ns=medians
        )
    return ExperimentResult(
        schema_version=RESULT_SCHEMA[engine_version],  # type: ignore[arg-type]
        engine_version=engine_version,
        experiment_id=config.experiment_id,
        environment_digest=env_digest,
        builds=[builds[c.arm] for c in config.candidates],
        measurements=list(measured.values()),
        stats=stats,
        verdicts=verdicts,
        tournament=table,
        winner=winner,
        order_is_total=total,
        noise_screens=screens if RESULT_SCHEMA[engine_version] == 2 else None,
        transport_floor=floor,
    )


def run_experiment(
    config: ExperimentConfig,
    approved: ApprovedExperiment,
    *,
    provisioner: SandboxProvisioner,
    hooks: EngineHooks,
    options: EngineOptions | None = None,
    engine_version: str = ENGINE_VERSION,
) -> ExperimentResult:
    """`engine_version` selects the scoring rules: experiment replay scores a replay with its
    source experiment's rules (ADR-0019); measurement is always the current engine's."""
    options = options or EngineOptions()
    ddl = _validate(config, approved)  # before any sandbox work
    ref = WorkloadRef.parse(config.workload_id)
    arms: list[CandidateArm | None] = [None, *config.candidates]
    started = time.monotonic()
    hooks.progress("provisioning")
    with provisioner.lease(
        timeout_seconds=options.lease_timeout_seconds, should_cancel=hooks.cancelled
    ) as lease:
        lease.cleanup_orphans()
        template = lease.ensure_template(ref)
        server = lease.server_environment()
        env = environment_fingerprint(
            pg_version=server.pg_version,
            pg_settings=server.pg_settings,
            workload_id=str(ref),
            data_digest=template.data_digest,
            options=options,
        )
        env_digest = digest("qc-json-v1", canonical_json(to_canonical(env)))
        hooks.environment(env, env_digest)
        clones = [lease.create_clone(template, config.experiment_id, i) for i in range(len(arms))]
        runners: list[ArmRunner] = []
        try:
            for clone in clones:
                runners.append(
                    ArmRunner(
                        provisioner.bench_conninfo(
                            clone, statement_timeout_ms=config.query_timeout_ms
                        ),
                        row_cap=config.row_hash_cap,
                    )
                )
            with _Cancellation(hooks, runners) as watch:
                try:
                    return _measure(
                        config,
                        arms,
                        runners,
                        ddl,
                        hooks,
                        options,
                        env_digest,
                        started,
                        engine_version,
                    )
                except RunCancelledError:
                    raise
                finally:
                    if watch.fired:
                        hooks.progress("measuring", cancelled=True)
        finally:
            for runner in runners:
                runner.close()
            for clone in clones:
                lease.drop_clone(clone)


def _measure(
    config: ExperimentConfig,
    arms: list[CandidateArm | None],
    runners: list[ArmRunner],
    ddl: Mapping[str, list[AllowedDdl]],
    hooks: EngineHooks,
    options: EngineOptions,
    env_digest: str,
    started: float,
    engine_version: str = ENGINE_VERSION,
) -> ExperimentResult:
    by_arm = {(a.arm if a else BASELINE_ARM): (a, r) for a, r in zip(arms, runners, strict=True)}
    done = {r.key: r for r in hooks.existing()}
    unique_keys = runners[0].unique_keys()

    # Build: every attempt re-applies DDL to its fresh clone; the first attempt's row is kept.
    hooks.progress("building")
    builds: dict[str, BuildResult] = {}
    for arm, runner in zip(config.candidates, runners[1:], strict=True):
        _check_cancel(hooks)
        build = runner.apply_ddl(
            arm.arm,
            ddl[arm.arm],
            max_build_ms=config.max_build_ms,
            max_index_bytes=config.max_index_bytes,
        )
        builds[arm.arm] = build
        record = BlockRecord(
            arm=arm.arm,
            candidate_id=str(arm.candidate_id) if arm.candidate_id else None,
            param_set="*",
            phase="build",
            block=0,
            index_size_bytes=build.index_size_bytes,
            index_build_ns=build.build_ns,
            build_error=None
            if build.ok
            else {"reason": build.reason or "", "detail": build.detail},
        )
        if record.key not in done:
            hooks.persist(record)
    active = [BASELINE_ARM, *(a for a, b in builds.items() if b.ok)]

    def query_for(arm_name: str) -> str:
        arm = by_arm[arm_name][0]
        return arm.query if arm is not None and arm.query else config.baseline_query

    params = {p.name: list(p.values) for p in config.param_sets}
    floor_before: list[int] = []
    floor_after: list[int] = []
    if len(active) > 1:
        # Transport floor (diagnostic): round trips on the baseline connection, outside every
        # timed sample, once before warm-up and once after measurement.
        floor_before = by_arm[BASELINE_ARM][1].round_trips(FLOOR_SAMPLES)
        hooks.progress("warming")
        for name in active:
            for ps in config.param_sets:
                for _ in range(config.warmup_runs):
                    _check_cancel(hooks)
                    by_arm[name][1].execute(query_for(name), params[ps.name])

        schedule = build_schedule(
            active,
            [p.name for p in config.param_sets],
            measured_runs=config.measured_runs,
            block_size=config.block_size,
            seed=config.seed,
        )
        total_blocks = len(schedule)
        for index, block in enumerate(schedule):
            _check_cancel(hooks)
            if time.monotonic() - started > options.time_budget_seconds:
                hooks.progress("measuring", time_budget_reached=True, block=index)
                break
            missing = [
                a
                for a in block.arm_order
                if (a, block.param_set, "measure", block.block) not in done
            ]
            if not missing:
                continue
            hooks.progress(
                "measuring", param_set=block.param_set, block=index + 1, blocks_total=total_blocks
            )
            for name in block.arm_order:
                if name not in missing:
                    continue
                spec, runner = by_arm[name]
                samples = [
                    runner.execute(
                        query_for(name),
                        params[block.param_set],
                        noise=_noise_for(options, name, block.param_set, block.block),
                    )
                    for _ in range(block.runs)
                ]
                if any(s.failure == "cancelled" for s in samples):
                    raise RunCancelledError("Experiment cancelled.")
                record = _block_record(spec, block.param_set, block.block, samples)
                hooks.persist(record)
                done[record.key] = record

        floor_after = by_arm[BASELINE_ARM][1].round_trips(FLOOR_SAMPLES)
        hooks.progress("capturing_plans")
        for name in active:
            for ps in config.param_sets:
                _check_cancel(hooks)
                key = (name, ps.name, "plan", 0)
                if key in done:
                    continue
                spec, runner = by_arm[name]
                plan = runner.explain_analyze(query_for(name), params[ps.name])
                record = BlockRecord(
                    arm=name,
                    candidate_id=str(spec.candidate_id) if spec and spec.candidate_id else None,
                    param_set=ps.name,
                    phase="plan",
                    block=0,
                    plan=plan,
                    buffers=buffers_of(plan),
                )
                hooks.persist(record)
                done[key] = record

    hooks.progress("checking")
    hooks.progress("scoring")
    return score(
        config,
        builds,
        list(done.values()),
        unique_keys=unique_keys,
        env_digest=env_digest,
        engine_version=engine_version,
        floor_samples=(floor_before, floor_after),
    )


@dataclass(frozen=True)
class ReplicatedRun:
    """The original experiment, any replicates, and the replication verdicts (None when the
    original needed no replication: a verified winner, or no screen-eligible arm)."""

    replicates: list[Replicate]
    replication: ReplicationResult | None

    @property
    def winner(self) -> str | None:
        if self.replication is not None:
            return self.replication.winner
        return self.replicates[0].result.winner


def run_replicated(
    config: ExperimentConfig,
    approved: ApprovedExperiment,
    *,
    provisioner: SandboxProvisioner,
    hooks_for: Callable[[ExperimentConfig, int], EngineHooks],
    options: EngineOptions | None = None,
    on_result: Callable[[ExperimentConfig, int, ExperimentResult], None] | None = None,
    replicates: int = REPLICATES,
) -> ReplicatedRun:
    """D11 (ADR-0019 §3): the approved experiment, then up to `replicates - 1` independent
    re-measurements of its screen-eligible arms, sharing one time budget.

    Each replicate is a full experiment (own id, seed, clones, approval-digest check). The
    replicates stop early once no arm is still eligible, or when the budget is spent; missing
    replicates leave the arm inconclusive.
    """
    options = options or EngineOptions()
    started = time.monotonic()

    def run(cfg: ExperimentConfig, index: int, budget: float) -> ExperimentResult:
        result = run_experiment(
            cfg,
            approved,
            provisioner=provisioner,
            hooks=hooks_for(cfg, index),
            options=dataclasses.replace(options, time_budget_seconds=budget),
        )
        if on_result is not None:
            on_result(cfg, index, result)
        return result

    first = run(config, 0, options.time_budget_seconds)
    done = [Replicate(config=config, result=first)]
    arms = eligible_arms(first)
    if not arms:
        return ReplicatedRun(replicates=done, replication=None)
    for index in range(1, replicates):
        remaining = options.time_budget_seconds - (time.monotonic() - started)
        still = [
            a
            for a in arms
            if all(
                any(v.arm == a and v.verdict == "verified" for v in r.result.verdicts)
                or a in eligible_arms(r.result.model_copy(update={"winner": None}))
                for r in done
            )
        ]
        if remaining <= 0 or not still:
            break
        cfg = replicate_config(config, index, still)
        try:
            done.append(Replicate(config=cfg, result=run(cfg, index, remaining)))
        except RunCancelledError:
            raise
        except QueryCureError as exc:
            # The approved experiment stands; a failed replicate only means fewer than three,
            # which leaves the arm inconclusive (assess_arm says how many completed).
            log.warning("replicate_failed", experiment_id=str(cfg.experiment_id), code=exc.code)
            break
    return ReplicatedRun(replicates=done, replication=assess_all(done))
