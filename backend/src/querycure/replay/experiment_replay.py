"""Experiment replay (REPLAY_ENGINE §8.2, §9): re-measure an approved experiment, no LLM.

Start (API, one transaction): preconditions → a new `experiment_replay` run under the same
investigation (parent = source run) → an `approval_requests` row decided by the confirming user
for exactly the source's approved SQL → a `replay_attempts` row (`queued`) → a job. A failed
precondition records the attempt as `not_replayable` and creates no run.

Execute (worker): the source `ExperimentConfig` unchanged except for `experiment_id` (same
seed, so the same interleaving schedule) runs through the same engine, with the DDL allowlist
and the approved-digest check applied again, and is scored with the *source* experiment's
rules. The new measurements are compared with the original (`replay/comparison.py`), the
comparison is stored as the replay run's content, and the replay run is finalized with its own
manifest. The source run and its records are never touched.
"""

import asyncio
import dataclasses
import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from querycure.agents.nodes.run_experiment import DbHooks, result_evidence
from querycure.benchmark.engine import ApprovedExperiment, EngineOptions, run_experiment, sql_digest
from querycure.core.config import Settings
from querycure.core.errors import (
    InvalidStateError,
    QueryCureError,
    RunCancelledError,
    SandboxPolicyError,
    SandboxUnavailableError,
)
from querycure.core.logging import get_logger
from querycure.db.repositories import investigations as inv_repo
from querycure.db.repositories.optimization import (
    create_experiment,
    get_approval_for_round,
    get_experiment_row,
    update_experiment,
)
from querycure.db.repositories.replay import (
    EXPERIMENT_TERMINAL,
    AttemptRow,
    attempt_for_replay_run,
    insert_attempt,
    update_attempt,
)
from querycure.domain.benchmark import (
    ENGINE_VERSION,
    ENGINE_VERSIONS,
    EnvironmentFingerprint,
    ExperimentConfig,
    ExperimentResult,
)
from querycure.domain.budgets import default_budget
from querycure.domain.optimization import APPROVAL_TTL_SECONDS, ApprovalPayload
from querycure.domain.runs import TERMINAL_STATUSES, RunOutcome, RunStatus
from querycure.events.emitter import change_status, emit
from querycure.events.types import EventType
from querycure.evidence.store import record_evidence
from querycure.jobs import queue
from querycure.replay.artifact_store import get_artifact_by_id, link, load_json, store_json
from querycure.replay.comparison import compare_experiments
from querycure.replay.finalize import Conclusion, finalize_run
from querycure.replay.report_replay import verify_report
from querycure.replay.source_snapshot import (
    CapturedSnapshot,
    SourceSnapshotError,
    capture_source_snapshot,
    link_source_snapshot,
)
from querycure.sandbox.provisioner import SandboxProvisioner
from querycure.sql.ddl_allowlist import validate_candidate
from querycure.workloads.registry import WorkloadRef

log = get_logger(__name__)
NODE = "experiment_replay"
REPLAY_NAMESPACE = uuid.UUID("0f6f1b0e-6d3b-4c55-8f0e-5d2a3c9b7e11")
REPORT_OK = ("verified", "verified_stored_only")
# Allowed attempt transitions (REPLAY_ENGINE §8.2); terminal states come from any active one.
_FROM: dict[str, tuple[str, ...]] = {"running": ("queued", "running"), "comparing": ("running",)}


@dataclass(frozen=True)
class Precondition:
    code: str | None
    detail: str = ""
    config: ExperimentConfig | None = None
    payload: ApprovalPayload | None = None
    source_run_id: uuid.UUID | None = None
    investigation_id: uuid.UUID | None = None
    snapshot: CapturedSnapshot | None = None


def replay_experiment_id(replay_run_id: uuid.UUID) -> uuid.UUID:
    """Deterministic, so a reclaimed job resumes the same experiment."""
    return uuid.uuid5(REPLAY_NAMESPACE, str(replay_run_id))


async def check_preconditions(
    conn: AsyncConnection, settings: Settings, experiment_id: uuid.UUID
) -> Precondition:
    """REPLAY_ENGINE §8.2 `not_replayable` codes, checked before any run exists."""
    experiment = await get_experiment_row(conn, experiment_id)
    if experiment is None:  # pragma: no cover - the API checks ownership first
        return Precondition("config_artifact_missing", "experiment not found")
    run = (
        await conn.execute(
            text("SELECT finalized_at, investigation_id FROM investigation_runs WHERE id = :id"),
            {"id": experiment.run_id},
        )
    ).first()
    if run is None:  # only through an integrity bug: the API's ownership query joins the run
        return Precondition(
            "source_integrity_failed", "source run missing", source_run_id=experiment.run_id
        )
    base = {"source_run_id": experiment.run_id, "investigation_id": run.investigation_id}
    if run.finalized_at is None:
        return Precondition("source_not_finalized", "the source run was never finalized", **base)
    verified = await verify_report(conn, experiment.run_id)
    if verified.status not in REPORT_OK:
        return Precondition(
            "source_integrity_failed",
            f"source report replay: {verified.status} ({verified.failure_code})",
            **base,
        )
    if experiment.status != "completed" or experiment.result_artifact_id is None:
        return Precondition(
            "source_experiment_incomplete", f"the source experiment is {experiment.status}", **base
        )
    raw = await load_json(conn, experiment.config_artifact_id)
    if raw is None:
        return Precondition("config_artifact_missing", **base)
    if raw.get("schema_version") != 1:
        return Precondition(
            "unsupported_config_schema", f"schema {raw.get('schema_version')}", **base
        )
    config = ExperimentConfig.model_validate(raw)
    if experiment.row_profile != "qc-row-v1":
        return Precondition("unsupported_row_profile", experiment.row_profile, **base)
    if experiment.engine_version not in ENGINE_VERSIONS:
        return Precondition("unsupported_config_schema", experiment.engine_version, **base)
    try:
        WorkloadRef.parse(config.workload_id)
    except ValueError as exc:
        return Precondition("workload_unavailable", str(exc)[:200], **base)
    for arm in config.candidates:
        try:  # the allowlist is applied again (it also runs inside the engine)
            validate_candidate(
                kind=arm.kind, ddl=list(arm.ddl), query=arm.query, baseline=config.baseline_query
            )
        except QueryCureError as exc:
            return Precondition(
                "unsupported_config_schema", f"{arm.arm} no longer passes: {exc.code}", **base
            )
    approval = await get_approval_for_round(conn, experiment.run_id, experiment.round)
    if approval is None:
        return Precondition("config_artifact_missing", "no source approval", **base)
    approved = {c.key: c for c in approval.payload.candidates}
    for arm in config.candidates:
        if arm.arm not in approved or approved[arm.arm].sql_sha256 != sql_digest(arm):
            return Precondition(
                "source_integrity_failed", f"{arm.arm} differs from what was approved", **base
            )
    result = await get_artifact_by_id(conn, experiment.result_artifact_id)
    if result is None:
        return Precondition("source_integrity_failed", "source experiment result missing", **base)
    try:  # from the digests report replay just verified
        snapshot = await capture_source_snapshot(
            conn,
            source_run_id=experiment.run_id,
            source_experiment_id=experiment.id,
            manifest_sha256=verified.manifest_sha256,
            report_json_sha256=verified.report_json_sha256,
            source_experiment_result_sha256=result.sha256,
            source_arms=[a.arm for a in config.candidates],
        )
    except SourceSnapshotError as exc:
        return Precondition("source_integrity_failed", exc.detail[:200], **base)
    if not settings.feature_sandbox or settings.sandbox_admin_url is None:
        return Precondition("sandbox_disabled", "no live sandbox in this deployment", **base)
    payload = approval.payload.model_copy(
        update={"candidates": [approved[a.arm] for a in config.candidates]}
    )
    return Precondition(None, config=config, payload=payload, snapshot=snapshot, **base)


async def start_replay(
    conn: AsyncConnection,
    *,
    settings: Settings,
    user_id: uuid.UUID,
    experiment_id: uuid.UUID,
    idempotency: tuple[str, str] | None = None,
) -> AttemptRow:
    """`idempotency` is (key, request hash). The attempt row carries it under a unique index,
    so a concurrent duplicate fails at insert and its whole transaction (replay run, approval,
    job) rolls back; the API then answers with the winner's attempt."""
    key, request_hash = idempotency if idempotency else (None, None)
    pre = await check_preconditions(conn, settings, experiment_id)
    source_run = pre.source_run_id
    if source_run is None:  # pragma: no cover - only for an experiment without a run
        raise InvalidStateError("Experiment has no source run.")
    if pre.code is not None or pre.config is None or pre.payload is None or pre.snapshot is None:
        return await insert_attempt(
            conn,
            user_id=user_id,
            kind="experiment",
            source_run_id=source_run,
            source_experiment_id=experiment_id,
            status="not_replayable",
            failure_code=pre.code,
            result={"detail": pre.detail},
            finished=True,
            idempotency_key=key,
            idempotency_request_hash=request_hash,
        )
    if pre.investigation_id is None:  # pragma: no cover
        raise InvalidStateError("Experiment has no investigation.")
    budget = default_budget(settings.profile).model_dump()
    replay_run: uuid.UUID = (
        await conn.execute(
            text(
                "INSERT INTO investigation_runs (investigation_id, run_number, kind, "
                "parent_run_id, status, budget, usage) VALUES (:inv, (SELECT coalesce("
                "max(run_number), 0) + 1 FROM investigation_runs WHERE investigation_id = :inv), "
                "'experiment_replay', :parent, 'queued', CAST(:budget AS JSONB), '{}') "
                "RETURNING id"
            ),
            {"inv": pre.investigation_id, "parent": source_run, "budget": _json(budget)},
        )
    ).scalar_one()
    config_art = await store_json(conn, kind="experiment_config", value=pre.config)
    await link(
        conn,
        run_id=replay_run,
        artifact_id=config_art.id,
        role="input.experiment_config",
        produced_by="api",
    )
    roles = (
        await conn.execute(
            text(
                "SELECT artifact_id, role FROM run_artifacts WHERE run_id = :run "
                "AND role IN ('input.query', 'input.param_sets')"
            ),
            {"run": source_run},
        )
    ).all()
    for r in roles:
        await link(
            conn, run_id=replay_run, artifact_id=r.artifact_id, role=r.role, produced_by="api"
        )
    # Same transaction as the run: a replay run never exists without its source snapshot.
    await link_source_snapshot(conn, replay_run, pre.snapshot)
    ids = [c.candidate_id for c in pre.payload.candidates]
    approval_id = (
        await conn.execute(
            text(
                "INSERT INTO approval_requests (run_id, user_id, round, kind, payload, status, "
                "decided_by, decided_at, expires_at, decision) VALUES (:run, :user, 0, "
                "'sandbox_execution', CAST(:payload AS JSONB), 'approved', :by, now(), "
                "now() + make_interval(secs => :ttl), CAST(:decision AS JSONB)) RETURNING id"
            ),
            {
                "run": replay_run,
                "user": user_id,
                "payload": pre.payload.model_dump_json(),
                "by": f"user:{user_id}",
                "ttl": APPROVAL_TTL_SECONDS,
                "decision": _json(
                    {
                        "approved_candidate_ids": [str(i) for i in ids],
                        "comment": "Confirmed for experiment replay.",
                    }
                ),
            },
        )
    ).scalar_one()
    attempt = await insert_attempt(
        conn,
        user_id=user_id,
        kind="experiment",
        source_run_id=source_run,
        source_experiment_id=experiment_id,
        replay_run_id=replay_run,
        approval_request_id=approval_id,
        status="queued",
        idempotency_key=key,
        idempotency_request_hash=request_hash,
    )
    await emit(conn, replay_run, EventType.RUN_STATUS_CHANGED, {"from": None, "to": "queued"})
    await emit(
        conn,
        replay_run,
        EventType.REPLAY_STATUS_CHANGED,
        {"replay_attempt_id": str(attempt.id), "from": None, "to": "queued"},
    )
    await queue.enqueue(
        conn,
        kind="experiment_replay",
        run_id=replay_run,
        payload={"replay_attempt_id": str(attempt.id)},
        dedupe_key=f"experiment_replay:{replay_run}",
    )
    return attempt


def _json(value: Any) -> str:
    return json.dumps(value)


async def _status(
    conn: AsyncConnection, attempt: AttemptRow, to: str, *, run_id: uuid.UUID, **kw: Any
) -> AttemptRow | None:
    froms = _FROM.get(to, ("queued", "running", "comparing"))
    updated = await update_attempt(conn, attempt.id, status=to, from_statuses=froms, **kw)
    if updated is not None and updated.status != attempt.status:
        payload: dict[str, Any] = {
            "replay_attempt_id": str(attempt.id),
            "from": attempt.status,
            "to": to,
        }
        if kw.get("failure_code"):
            payload["failure_code"] = kw["failure_code"]
        await emit(conn, run_id, EventType.REPLAY_STATUS_CHANGED, payload)
    return updated


async def _close(
    engine: AsyncEngine,
    run_id: uuid.UUID,
    attempt: AttemptRow,
    *,
    status: str,
    code: str | None,
    run_status: RunStatus,
    outcome: RunOutcome | None = None,
    result: dict[str, Any] | None = None,
    experiment_id: uuid.UUID | None = None,
) -> None:
    async with engine.begin() as conn:
        current = await _status(
            conn,
            attempt,
            status,
            run_id=run_id,
            failure_code=code,
            result=result,
            replay_experiment_id=experiment_id,
            finished=True,
        )
        if current is None:
            return  # already terminal (e.g. cancelled concurrently)
        run = (
            await conn.execute(
                text("SELECT status, finalized_at FROM investigation_runs WHERE id = :id"),
                {"id": run_id},
            )
        ).one()
        if run.finalized_at is None and RunStatus(run.status) not in TERMINAL_STATUSES:
            await finalize_run(
                conn,
                run_id,
                Conclusion(
                    final_status=run_status,
                    outcome=outcome,
                    stop_reason=None
                    if run_status is RunStatus.COMPLETED
                    else ("cancelled" if run_status is RunStatus.CANCELLED else "failed"),
                    error=None if code is None or status != "failed" else {"code": code},
                ),
            )


def failure_code_for(exc: QueryCureError) -> str:
    if isinstance(exc, SandboxUnavailableError):
        return "sandbox_unavailable"
    if isinstance(exc, SandboxPolicyError):
        return "ddl_failed"
    if "TIMEOUT" in exc.code:
        return "timeout"
    return "internal_error"


async def execute_experiment_replay(
    engine: AsyncEngine,
    run_id: uuid.UUID,
    *,
    sandbox: SandboxProvisioner | None,
    options: EngineOptions,
    reclaimed: bool,
) -> None:
    async with engine.begin() as conn:
        attempt = await attempt_for_replay_run(conn, run_id)
        status = (
            await conn.execute(
                text("SELECT status FROM investigation_runs WHERE id = :id"), {"id": run_id}
            )
        ).scalar_one()
        if attempt is None or attempt.status in EXPERIMENT_TERMINAL:
            return
        current = RunStatus(status)
        if current in TERMINAL_STATUSES:
            return
        if current is RunStatus.RUNNING and reclaimed:
            await change_status(conn, run_id, RunStatus.QUEUED)
            current = RunStatus.QUEUED
        if current is RunStatus.QUEUED:
            await change_status(conn, run_id, RunStatus.RUNNING)
        updated = await _status(conn, attempt, "running", run_id=run_id)
        attempt = updated or attempt
        source = await get_experiment_row(conn, attempt.source_experiment_id)  # type: ignore[arg-type]
        approval = await get_approval_for_round(conn, run_id, 0)
        if source is None or approval is None or source.result_artifact_id is None:
            raise InvalidStateError("Replay attempt is missing its source or approval.")
        config = ExperimentConfig.model_validate(await load_json(conn, source.config_artifact_id))
        source_result = ExperimentResult.model_validate_json(
            (await get_artifact_by_id(conn, source.result_artifact_id)).content  # type: ignore[union-attr]
        )
        budget_seconds = (
            await conn.execute(
                text("SELECT budget->>'benchmark_seconds' FROM investigation_runs WHERE id = :id"),
                {"id": run_id},
            )
        ).scalar_one()

    experiment_id = replay_experiment_id(run_id)
    replay_config = config.model_copy(update={"experiment_id": experiment_id})
    async with engine.begin() as conn:
        art = await store_json(conn, kind="experiment_config", value=replay_config)
        await link(
            conn, run_id=run_id, artifact_id=art.id, role="experiment.config", produced_by=NODE
        )
        await create_experiment(
            conn,
            experiment_id=experiment_id,
            run_id=run_id,
            round=0,
            kind="tournament" if len(config.candidates) > 1 else "single",
            approval_request_id=approval.id,
            config_artifact_id=art.id,
            engine_version=source.engine_version,
            row_profile=source.row_profile,
            seed=config.seed,
            replay_of_experiment_id=source.id,
        )
    if sandbox is None:
        await _fail(engine, run_id, attempt, experiment_id, "sandbox_unavailable")
        return

    approved = ApprovedExperiment(
        approval_request_id=str(approval.id),
        approved_sql={c.key: c.sql_sha256 for c in approval.payload.candidates},
    )
    loop = asyncio.get_running_loop()
    hooks = DbHooks(loop, engine, run_id, experiment_id)
    seconds = float(budget_seconds) if budget_seconds else options.time_budget_seconds
    run_options = dataclasses.replace(options, time_budget_seconds=seconds)
    try:
        result = await asyncio.to_thread(
            run_experiment,
            replay_config,
            approved,
            provisioner=sandbox,
            hooks=hooks,
            options=run_options,
            engine_version=source.engine_version,
        )
    except RunCancelledError:
        async with engine.begin() as conn:
            await update_experiment(conn, experiment_id, status="cancelled", finished=True)
        await _close(
            engine,
            run_id,
            attempt,
            status="cancelled",
            code="cancelled_by_user",
            run_status=RunStatus.CANCELLED,
            experiment_id=experiment_id,
        )
        return
    except QueryCureError as exc:
        log.warning("experiment_replay_failed", run_id=str(run_id), code=exc.code)
        await _fail(engine, run_id, attempt, experiment_id, failure_code_for(exc))
        return

    async with engine.begin() as conn:
        result_art = await store_json(conn, kind="experiment_result", value=result)
        await link(
            conn,
            run_id=run_id,
            artifact_id=result_art.id,
            role="experiment.result",
            produced_by=NODE,
        )
        await update_experiment(
            conn,
            experiment_id,
            status="completed",
            result_artifact_id=result_art.id,
            finished=True,
        )
        replay_row = await get_experiment_row(conn, experiment_id)
        updated = await _status(conn, attempt, "comparing", run_id=run_id)
        attempt = updated or attempt
    await record_evidence(engine, run_id, result_evidence(run_id, result_art.sha256, result))
    if replay_row is None or replay_row.environment is None:
        raise InvalidStateError("Replay experiment has no environment fingerprint.")
    comparison = compare_experiments(
        original_id=str(source.id),
        replay_id=str(experiment_id),
        config=config,
        original=source_result,
        replay=result,
        original_env=EnvironmentFingerprint.model_validate(source.environment),
        replay_env=EnvironmentFingerprint.model_validate(replay_row.environment),
        original_env_digest=source.environment_digest,
        replay_env_digest=replay_row.environment_digest,
        replay_engine=ENGINE_VERSION,  # measured by the current engine
    )
    comparison = {
        **comparison,
        "original_experiment_id": str(source.id),
        "replay_experiment_id": str(experiment_id),
    }
    async with engine.begin() as conn:
        stored = await store_json(conn, kind="replay_comparison", value=comparison)
        await link(
            conn, run_id=run_id, artifact_id=stored.id, role="replay.comparison", produced_by=NODE
        )
        await emit(
            conn,
            run_id,
            EventType.REPLAY_COMPARED,
            {
                "replay_attempt_id": str(attempt.id),
                "status": comparison["status"],
                "comparison_mode": comparison["comparison_mode"],
                "pairs_summary": {
                    s: sum(1 for p in comparison["pairs"] if p["status"] == s)
                    for s in (
                        "reproduced",
                        "reproduced_with_drift",
                        "inconclusive",
                        "not_reproduced",
                    )
                },
            },
        )
    status_ = comparison["status"]
    failed = status_ == "failed"
    await _close(
        engine,
        run_id,
        attempt,
        status=status_,
        code=comparison.get("failure_code"),
        run_status=RunStatus.FAILED if failed else RunStatus.COMPLETED,
        outcome=None
        if failed
        else (RunOutcome.VERIFIED_RECOMMENDATION if result.winner else RunOutcome.INCONCLUSIVE),
        result=comparison,
        experiment_id=experiment_id,
    )


async def _fail(
    engine: AsyncEngine,
    run_id: uuid.UUID,
    attempt: AttemptRow,
    experiment_id: uuid.UUID,
    code: str,
) -> None:
    async with engine.begin() as conn:
        await update_experiment(
            conn, experiment_id, status="failed", error={"code": code}, finished=True
        )
    await _close(
        engine,
        run_id,
        attempt,
        status="failed",
        code=code,
        run_status=RunStatus.FAILED,
        experiment_id=experiment_id,
    )


async def mark_replay_failed(engine: AsyncEngine, run_id: uuid.UUID, code: str) -> None:
    """Dead-lettered replay job: the attempt fails too (the run is failed by fail_run)."""
    async with engine.begin() as conn:
        attempt = await attempt_for_replay_run(conn, run_id)
        if attempt is not None and attempt.status not in EXPERIMENT_TERMINAL:
            await update_attempt(
                conn, attempt.id, status="failed", failure_code=code, finished=True
            )


async def cancel_replay_attempt(conn: AsyncConnection, attempt: AttemptRow) -> AttemptRow:
    """Queued: the replay run is sealed as cancelled now. Running: the run is asked to stop and
    the worker cancels the attempt at its next safe point (between blocks)."""
    if attempt.status in EXPERIMENT_TERMINAL or attempt.replay_run_id is None:
        return attempt
    run_id = attempt.replay_run_id
    status = RunStatus(
        (
            await conn.execute(
                text("SELECT status FROM investigation_runs WHERE id = :id FOR UPDATE"),
                {"id": run_id},
            )
        ).scalar_one()
    )
    await inv_repo.mark_cancel_requested(conn, run_id)
    if status is RunStatus.RUNNING:
        await change_status(conn, run_id, RunStatus.CANCELLING)
        return attempt
    if status in TERMINAL_STATUSES or status is RunStatus.CANCELLING:
        return attempt
    updated = await _status(
        conn, attempt, "cancelled", run_id=run_id, failure_code="cancelled_by_user", finished=True
    )
    await finalize_run(
        conn,
        run_id,
        Conclusion(final_status=RunStatus.CANCELLED, outcome=None, stop_reason="cancelled"),
    )
    return updated or attempt
