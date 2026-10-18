"""Worker loop: `concurrency` slots, each claiming one job at a time from the Postgres queue.

A heartbeat task runs beside every handler. If it finds the lease gone (another worker
reclaimed the job after this one stalled), the handler is cancelled so the job never runs
twice in parallel. On stop() (SIGTERM), in-flight handlers get `shutdown_grace_seconds` to
finish (still heartbeating); after that they are cancelled and their jobs are left
`running`: the lease expires and another worker resumes them from the last checkpoint.

Every log line written while a job runs carries `job_id`, `job_kind`, `run_id` and `attempt`
(structlog contextvars), including lines from the graph, the engine and the LLM layer.
"""

import asyncio
import contextlib
import uuid
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.core.logging import get_logger
from querycure.jobs import queue
from querycure.jobs.queue import Job, JobKind, ReapedJob

Handler = Callable[[Job], Coroutine[Any, Any, None]]
DeadCallback = Callable[[Job | ReapedJob], Awaitable[None]]

log = get_logger(__name__)


class PermanentJobError(Exception):
    """Retrying cannot help (bad payload, missing run). The job is dead-lettered at once."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class WorkerTimings:
    lease_seconds: int = 60
    heartbeat_seconds: float = 20.0
    poll_seconds: float = 1.0
    shutdown_grace_seconds: float = 0.0  # the process sets WORKER_SHUTDOWN_GRACE_SECONDS


class Worker:
    def __init__(
        self,
        engine: AsyncEngine,
        handlers: Mapping[JobKind, Handler],
        *,
        worker_id: str | None = None,
        concurrency: int = 1,
        timings: WorkerTimings | None = None,
        on_dead: DeadCallback | None = None,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        self._engine = engine
        self._handlers = handlers
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:12]}"
        self._concurrency = concurrency
        self._timings = timings or WorkerTimings()
        self._on_dead = on_dead
        self._stopping = asyncio.Event()

    @property
    def timings(self) -> WorkerTimings:
        return self._timings

    async def run(self) -> None:
        log.info("worker_started", worker_id=self.worker_id, concurrency=self._concurrency)
        async with asyncio.TaskGroup() as group:
            for slot in range(self._concurrency):
                group.create_task(self._slot(slot))
        log.info("worker_stopped", worker_id=self.worker_id)

    async def stop(self) -> None:
        self._stopping.set()

    async def _slot(self, slot: int) -> None:
        while not self._stopping.is_set():
            try:
                job = await self._next_job()
            except Exception:
                log.exception("job_claim_failed", worker_id=self.worker_id, slot=slot)
                job = None
            if job is None:
                await self._idle()
                continue
            await self._execute(job)

    async def _idle(self) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stopping.wait(), self._timings.poll_seconds)

    async def _next_job(self) -> Job | None:
        async with self._engine.begin() as conn:
            reaped = await queue.reap_exhausted(conn)
        for dead in reaped:
            log.warning("job_dead_lettered", job_id=str(dead.id), kind=dead.kind, reason="lease")
            if self._on_dead is not None:
                await self._on_dead(dead)
        async with self._engine.begin() as conn:
            return await queue.claim(
                conn, worker_id=self.worker_id, lease_seconds=self._timings.lease_seconds
            )

    async def _execute(self, job: Job) -> None:
        structlog.contextvars.bind_contextvars(
            job_id=str(job.id),
            job_kind=job.kind,
            run_id=str(job.run_id) if job.run_id else None,
            attempt=job.attempts,
        )
        try:
            await self._execute_bound(job)
        finally:
            structlog.contextvars.unbind_contextvars("job_id", "job_kind", "run_id", "attempt")

    async def _execute_bound(self, job: Job) -> None:
        bound = log.bind(job_id=str(job.id), kind=job.kind, attempt=job.attempts)
        handler = self._handlers.get(job.kind)
        if handler is None:
            bound.error("job_kind_unhandled")
            await self._fail(job, {"code": "UNKNOWN_JOB_KIND"}, retryable=False)
            return

        work = asyncio.create_task(handler(job))
        beat = asyncio.create_task(self._heartbeat(job, work))
        stop_wait = asyncio.create_task(self._stopping.wait())
        try:
            await asyncio.wait({work, stop_wait}, return_when=asyncio.FIRST_COMPLETED)
            if not work.done() and self._timings.shutdown_grace_seconds > 0:
                # Stopping: give the job a bounded chance to reach a terminal state, still
                # heartbeating so the lease does not expire under it.
                bound.info("job_draining", grace_seconds=self._timings.shutdown_grace_seconds)
                await asyncio.wait({work}, timeout=self._timings.shutdown_grace_seconds)
        finally:
            beat.cancel()
            stop_wait.cancel()
        if not work.done():
            # Shutting down: abandon the job to lease expiry; never fail it on our own stop.
            work.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await work
            bound.info("job_abandoned_on_shutdown")
            return

        if work.cancelled():
            bound.warning("job_lease_lost")
            return
        error = work.exception()
        if error is None:
            async with self._engine.begin() as conn:
                await queue.complete(conn, job_id=job.id, worker_id=self.worker_id)
            bound.info("job_done")
        elif isinstance(error, PermanentJobError):
            bound.error("job_failed_permanently", code=error.code)
            await self._fail(job, {"code": error.code}, retryable=False)
        else:
            # Only the exception type is stored: messages can carry DSNs or keys.
            bound.error("job_failed", exc_info=error)
            await self._fail(
                job, {"code": "HANDLER_ERROR", "type": type(error).__name__}, retryable=True
            )

    async def _fail(self, job: Job, error: dict[str, str], *, retryable: bool) -> None:
        async with self._engine.begin() as conn:
            status = await queue.fail(
                conn, job_id=job.id, worker_id=self.worker_id, error=error, retryable=retryable
            )
        if status == "dead" and self._on_dead is not None:
            await self._on_dead(job)

    async def _heartbeat(self, job: Job, work: asyncio.Task[None]) -> None:
        while True:
            await asyncio.sleep(self._timings.heartbeat_seconds)
            try:
                async with self._engine.begin() as conn:
                    held = await queue.heartbeat(
                        conn,
                        job_id=job.id,
                        worker_id=self.worker_id,
                        lease_seconds=self._timings.lease_seconds,
                    )
            except Exception:
                # A transient DB blip: keep working; the lease outlives a few missed beats.
                log.warning("job_heartbeat_failed", job_id=str(job.id), exc_info=True)
                continue
            if not held:
                work.cancel()
                return
