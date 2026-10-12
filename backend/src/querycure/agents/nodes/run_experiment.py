"""run_experiment (deterministic node, AGENT_SYSTEM §2): the approved tournament in the sandbox.

The benchmark engine is synchronous and runs in one worker thread; `DbHooks` bridges its
persistence and progress calls back to the event loop and the metadata DB. Everything the
engine measures is written as it happens (append-only `benchmark_runs`), so a crashed or
reclaimed job resumes at the first missing block instead of starting over.

Verdicts are the engine's deterministic rule verdicts (ADR-0009); this node only records
them: candidate statuses, an `experiment_result` artifact, `benchmark_metric` and
`correctness_check` evidence, and `verification.completed` events.
"""

import asyncio
import dataclasses
import time
import uuid
from collections.abc import Coroutine
from typing import Any, TypeVar

from langgraph.runtime import Runtime
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.agents.candidates import candidate_arm
from querycure.agents.runtime import RunContext, guarded
from querycure.agents.state import InvestigationState
from querycure.benchmark.engine import (
    ApprovedExperiment,
    BlockRecord,
    State,
)
from querycure.benchmark.engine import run_experiment as run_engine
from querycure.benchmark.schedule import derive_seed
from querycure.core.errors import QueryCureError, RunCancelledError, SandboxUnavailableError
from querycure.core.logging import get_logger
from querycure.db.repositories.optimization import (
    create_experiment,
    get_approval_for_round,
    insert_benchmark_run,
    list_benchmark_runs,
    list_candidates,
    set_candidate_status,
    update_experiment,
)
from querycure.domain.benchmark import (
    BASELINE_ARM,
    ENGINE_VERSION,
    EnvironmentFingerprint,
    ExperimentConfig,
    ExperimentResult,
    ParamSetSpec,
)
from querycure.domain.investigation import Evidence, JsonScalar, NodeError
from querycure.events.emitter import emit
from querycure.events.types import EventType
from querycure.evidence.ids import evidence_id
from querycure.evidence.store import record_evidence
from querycure.replay.artifact_store import link, store_json

log = get_logger(__name__)
T = TypeVar("T")

NODE = "run_experiment"
EXPERIMENT_NAMESPACE = uuid.UUID("5c1e7a3e-0b9d-4f3c-9a51-7d0c2f6b8e41")
_PERSISTED_STATUS: dict[str, str] = {"provisioning": "provisioning"}  # everything else: running
CANCEL_POLL_SECONDS = 0.25


def experiment_id_for(run_id: uuid.UUID, round: int) -> uuid.UUID:
    """Deterministic, so a re-run after a crash finds and resumes the same experiment."""
    return uuid.uuid5(EXPERIMENT_NAMESPACE, f"{run_id}:{round}")


def experiment_seed(run_id: uuid.UUID, round: int) -> int:
    return derive_seed(run_id.int, "experiment", round) % (2**53 - 1)


class DbHooks:
    """EngineHooks for the worker thread: each call runs a coroutine on the run's loop."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        engine: AsyncEngine,
        run_id: uuid.UUID,
        experiment_id: uuid.UUID,
    ) -> None:
        self._loop = loop
        self._engine = engine
        self._run_id = run_id
        self._experiment_id = experiment_id
        self._cancel_checked = 0.0
        self._cancel = False

    def _call(self, coro: Coroutine[Any, Any, T]) -> T:
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=60)

    def existing(self) -> list[BlockRecord]:
        async def load() -> list[dict[str, Any]]:
            async with self._engine.connect() as conn:
                return await list_benchmark_runs(conn, self._experiment_id)

        return [
            BlockRecord(
                arm=r["arm"],
                candidate_id=str(r["candidate_id"]) if r["candidate_id"] else None,
                param_set=r["param_set"],
                phase=r["phase"],
                block=r["block"],
                latencies_ns=list(r["latencies_ns"]),
                sample_errors=list(r["sample_errors"]),
                rows_returned=r["rows_returned"],
                result_fingerprint=r["result_fingerprint"],
                ordered_fingerprint=r["ordered_fingerprint"],
                truncated=r["truncated"],
                buffers=r["buffers"],
                index_size_bytes=r["index_size_bytes"],
                index_build_ns=r["index_build_ns"],
                build_error=r["build_error"],
            )
            for r in self._call(load())
        ]

    def persist(self, record: BlockRecord) -> None:
        async def write() -> None:
            async with self._engine.begin() as conn:
                plan_id = None
                if record.plan is not None:
                    plan = await store_json(conn, kind="plan_analyze", value=record.plan)
                    await link(
                        conn,
                        run_id=self._run_id,
                        artifact_id=plan.id,
                        role="experiment.plan",
                        produced_by=NODE,
                    )
                    plan_id = plan.id
                await insert_benchmark_run(
                    conn,
                    self._experiment_id,
                    {
                        "candidate_id": uuid.UUID(record.candidate_id)
                        if record.candidate_id
                        else None,
                        "arm": record.arm,
                        "param_set": record.param_set,
                        "phase": record.phase,
                        "block": record.block,
                        "latencies_ns": record.latencies_ns,
                        "sample_errors": record.sample_errors,
                        "rows_returned": record.rows_returned,
                        "result_fingerprint": record.result_fingerprint,
                        "ordered_fingerprint": record.ordered_fingerprint,
                        "truncated": record.truncated,
                        "plan_artifact_id": plan_id,
                        "buffers": record.buffers,
                        "index_size_bytes": record.index_size_bytes,
                        "index_build_ns": record.index_build_ns,
                        "build_error": record.build_error,
                        "provenance": "measured",
                    },
                )

        self._call(write())

    def progress(self, state: State, **details: Any) -> None:
        async def write() -> None:
            async with self._engine.begin() as conn:
                await update_experiment(
                    conn,
                    self._experiment_id,
                    status=_PERSISTED_STATUS.get(state, "running"),
                    started=True,
                )
                await emit(
                    conn,
                    self._run_id,
                    EventType.BENCHMARK_PROGRESS,
                    {"experiment_id": str(self._experiment_id), "state": state, **details},
                )

        self._call(write())

    def environment(self, env: EnvironmentFingerprint, env_digest: str) -> None:
        async def write() -> None:
            async with self._engine.begin() as conn:
                artifact = await store_json(conn, kind="environment", value=env)
                await link(
                    conn,
                    run_id=self._run_id,
                    artifact_id=artifact.id,
                    role="experiment.environment",
                    produced_by=NODE,
                )
                await update_experiment(
                    conn,
                    self._experiment_id,
                    environment=env.model_dump(mode="json"),
                    environment_digest=env_digest,
                )

        self._call(write())

    def cancelled(self) -> bool:
        """Polled between blocks and by the in-flight watcher; at most one query per 250 ms."""
        now = time.monotonic()
        if self._cancel or now - self._cancel_checked < CANCEL_POLL_SECONDS:
            return self._cancel

        async def check() -> bool:
            async with self._engine.connect() as conn:
                row = await conn.execute(
                    text(
                        "SELECT cancel_requested_at IS NOT NULL FROM investigation_runs "
                        "WHERE id = :id"
                    ),
                    {"id": self._run_id},
                )
                return bool(row.scalar_one())

        self._cancel = self._call(check())
        self._cancel_checked = now
        return self._cancel


def _ms(ns: float) -> float:
    return round(ns / 1e6, 3)


def result_evidence(run_id: uuid.UUID, result_sha: str, result: ExperimentResult) -> list[Evidence]:
    """Deterministic evidence from the stored result: every number in a summary is in data."""
    items: list[Evidence] = []
    for s in result.stats:
        data: dict[str, JsonScalar] = {
            "arm": s.arm,
            "param_set": s.param_set,
            "speedup": round(s.speedup, 3),
            "ci_low": round(s.ci_low, 3),
            "ci_high": round(s.ci_high, 3),
            "baseline_median_ms": _ms(s.baseline.median_ns),
            "candidate_median_ms": _ms(s.candidate.median_ns),
            "n_baseline": s.baseline.n,
            "n_candidate": s.candidate.n,
        }
        items.append(
            Evidence(
                id=evidence_id(
                    run_id, "benchmark_metric", result_sha, f"/stats/{s.arm}/{s.param_set}"
                ),
                kind="benchmark_metric",
                artifact_sha256=result_sha,
                locator=f"/stats/{s.arm}/{s.param_set}",
                summary=(
                    f"{s.arm} on {s.param_set}: median {data['baseline_median_ms']} ms -> "
                    f"{data['candidate_median_ms']} ms, speedup {data['speedup']}x "
                    f"(95% CI {data['ci_low']}-{data['ci_high']}x), "
                    f"n={s.baseline.n}/{s.candidate.n}"
                ),
                data=data,
                provenance="measured",
            )
        )
    measured = {(m.arm, m.param_set): m for m in result.measurements}
    param_sets = sorted({m.param_set for m in result.measurements})
    for verdict in result.verdicts:
        for ps in param_sets:
            base, cand = measured.get((BASELINE_ARM, ps)), measured.get((verdict.arm, ps))
            if base is None or cand is None or base.fingerprint is None or cand.fingerprint is None:
                continue
            same = (
                base.fingerprint.rows == cand.fingerprint.rows
                and base.fingerprint.multiset == cand.fingerprint.multiset
            )
            items.append(
                Evidence(
                    id=evidence_id(
                        run_id, "correctness_check", result_sha, f"/correctness/{verdict.arm}/{ps}"
                    ),
                    kind="correctness_check",
                    artifact_sha256=result_sha,
                    locator=f"/correctness/{verdict.arm}/{ps}",
                    summary=(
                        f"{verdict.arm} on {ps}: {'same' if same else 'different'} result rows as "
                        f"the baseline ({cand.fingerprint.rows} vs {base.fingerprint.rows} rows)"
                    ),
                    data={
                        "arm": verdict.arm,
                        "param_set": ps,
                        "same_rows": same,
                        "rows": cand.fingerprint.rows,
                        "baseline_rows": base.fingerprint.rows,
                    },
                    provenance="measured",
                )
            )
    return items


async def _fail(
    ctx: RunContext, experiment_id: uuid.UUID, candidate_ids: list[uuid.UUID], exc: QueryCureError
) -> dict[str, Any]:
    error = NodeError(node=NODE, code=exc.code, message=exc.message[:500], recoverable=True)
    async with ctx.db().begin() as conn:
        await update_experiment(
            conn, experiment_id, status="failed", error={"code": exc.code}, finished=True
        )
        await set_candidate_status(
            conn, ctx.run_id, candidate_ids, "inconclusive",
            reasons=[{"code": "experiment_failed", "detail": exc.code}],
        )  # fmt: skip
    await ctx.events.emit(EventType.ERROR, error.model_dump())
    return {"verification": "failed", "winner": None, "errors": [error.model_dump()]}


@guarded(NODE)
async def run_experiment(state: InvestigationState, runtime: Runtime[RunContext]) -> dict[str, Any]:
    ctx = runtime.context
    round = state.get("optimization_round", 0)
    if state.get("approval_status") not in ("approved", "partially_approved"):
        return {"verification": None, "winner": None}
    experiment_id = experiment_id_for(ctx.run_id, round)
    async with ctx.db().begin() as conn:
        approval = await get_approval_for_round(conn, ctx.run_id, round)
        if approval is None or approval.decision is None:
            return {"verification": None, "winner": None}
        approved_ids = set(approval.decision.approved_candidate_ids)
        candidates = [
            c for c in await list_candidates(conn, ctx.run_id, round=round) if c.id in approved_ids
        ]
        if not candidates:
            return {"verification": None, "winner": None}
        payload = approval.payload
        config = ExperimentConfig(
            experiment_id=experiment_id,
            workload_id=payload.workload_id,
            baseline_query=payload.baseline_query,
            candidates=[candidate_arm(c) for c in candidates],
            param_sets=[ParamSetSpec.model_validate(p) for p in payload.param_sets],
            seed=experiment_seed(ctx.run_id, round),
        )
        config_art = await store_json(conn, kind="experiment_config", value=config)
        await link(
            conn,
            run_id=ctx.run_id,
            artifact_id=config_art.id,
            role="experiment.config",
            produced_by=NODE,
        )
        await create_experiment(
            conn,
            experiment_id=experiment_id,
            run_id=ctx.run_id,
            round=round,
            kind="tournament" if len(candidates) > 1 else "single",
            approval_request_id=approval.id,
            config_artifact_id=config_art.id,
            engine_version=ENGINE_VERSION,
            row_profile="qc-row-v1",
            seed=config.seed,
        )
        await set_candidate_status(
            conn, ctx.run_id, [c.id for c in candidates if c.id], "benchmarked"
        )
    candidate_ids = [c.id for c in candidates if c.id is not None]
    if ctx.sandbox is None:
        return await _fail(
            ctx,
            experiment_id,
            candidate_ids,
            SandboxUnavailableError("No sandbox server is configured for this worker."),
        )

    # Pinned at approval time: the engine refuses any arm whose SQL digest differs.
    approved = ApprovedExperiment(
        approval_request_id=str(approval.id),
        approved_sql={
            c.key: c.sql_sha256 for c in payload.candidates if c.candidate_id in approved_ids
        },
    )
    hooks = DbHooks(asyncio.get_running_loop(), ctx.db(), ctx.run_id, experiment_id)
    options = dataclasses.replace(
        ctx.engine_options, time_budget_seconds=float(ctx.guard.budget.benchmark_seconds)
    )
    try:
        result = await asyncio.to_thread(
            run_engine, config, approved, provisioner=ctx.sandbox, hooks=hooks, options=options
        )
    except RunCancelledError:
        async with ctx.db().begin() as conn:
            await update_experiment(conn, experiment_id, status="cancelled", finished=True)
        raise
    except QueryCureError as exc:
        log.warning("experiment_failed", run_id=str(ctx.run_id), code=exc.code)
        return await _fail(ctx, experiment_id, candidate_ids, exc)

    by_key = {c.key: c for c in candidates}
    async with ctx.db().begin() as conn:
        result_art = await store_json(conn, kind="experiment_result", value=result)
        await link(
            conn,
            run_id=ctx.run_id,
            artifact_id=result_art.id,
            role="experiment.result",
            produced_by=NODE,
        )
        await update_experiment(
            conn, experiment_id, status="completed", result_artifact_id=result_art.id, finished=True
        )
        for verdict in result.verdicts:
            candidate = by_key[verdict.arm]
            reasons = [r.model_dump() for r in verdict.reasons]
            await set_candidate_status(
                conn, ctx.run_id, [candidate.id] if candidate.id else [], verdict.verdict,
                reasons=reasons,
            )  # fmt: skip
            await emit(
                conn,
                ctx.run_id,
                EventType.VERIFICATION_COMPLETED,
                {
                    "experiment_id": str(experiment_id),
                    "candidate_key": verdict.arm,
                    "verdict": verdict.verdict,
                    "gate": verdict.gate,
                    "reasons": reasons,
                },
            )
    await record_evidence(
        ctx.db(), ctx.run_id, result_evidence(ctx.run_id, result_art.sha256, result)
    )
    verdicts = {v.verdict for v in result.verdicts}
    text_ = (
        f"Tournament winner: {result.winner} (verified within the tested scope)."
        if result.winner
        else "No candidate was verified: "
        + "; ".join(
            f"{v.arm} {v.verdict} ({v.reasons[0].code})" for v in result.verdicts if v.reasons
        )
    )
    await ctx.events.emit(EventType.AGENT_SUMMARY, {"agent": "benchmark", "text": text_[:600]})
    verification = (
        "verified"
        if result.winner
        else ("rejected" if verdicts == {"rejected"} else "inconclusive")
    )
    return {
        "experiment_ids": [str(experiment_id)],
        "winner": result.winner,
        "verification": verification,
    }
