"""`python -m querycure.worker`: the separate worker process (ARCHITECTURE: api + worker).

`WORKER_MODE=embedded` runs the same loop inside the API process instead (DEPLOYMENT §1, for a
single-container demo); both paths go through `serve`.
"""

import asyncio
import contextlib
import signal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.core.config import Settings
from querycure.core.errors import ConfigurationError
from querycure.core.logging import configure_logging, get_logger
from querycure.db.engine import make_engine
from querycure.jobs.approvals import expire_approvals
from querycure.jobs.handlers import build_handlers, build_services, dead_job_handler
from querycure.sandbox.provisioner import SandboxBusyError, SandboxProvisioner
from querycure.worker.runner import Worker, WorkerTimings

log = get_logger(__name__)
APPROVAL_SWEEP_SECONDS = 60.0
MAINTENANCE_SECONDS = 300.0


async def sweep_approvals(engine: AsyncEngine, stop: asyncio.Event) -> None:
    """Expired approvals resume their runs, which then end `inconclusive` (AGENT_SYSTEM §8)."""
    while not stop.is_set():
        try:
            await expire_approvals(engine)
        except Exception:
            log.exception("approval_sweep_failed")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), APPROVAL_SWEEP_SECONDS)


def cleanup_sandbox(sandbox: SandboxProvisioner) -> None:
    """Drop clones a crashed worker left behind; skipped while another experiment measures."""
    try:
        with sandbox.lease(timeout_seconds=1.0) as lease:
            lease.cleanup_orphans()
    except SandboxBusyError:
        log.info("sandbox_cleanup_skipped_busy")


async def report_stuck_work(engine: AsyncEngine) -> dict[str, int]:
    """Signals for the debugging playbook (OBSERVABILITY §7): jobs whose lease expired (another
    worker reclaims them on its next claim), and active runs with no live job at all (nothing
    will ever move them; they need an operator)."""
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT (SELECT count(*) FROM jobs WHERE status = 'running' "
                    "AND locked_until < now()) AS expired_leases, "
                    "(SELECT count(*) FROM investigation_runs r WHERE r.status IN "
                    "('queued', 'running', 'cancelling') AND r.deleted_at IS NULL "
                    "AND r.created_at < now() - interval '10 minutes' AND NOT EXISTS ("
                    "SELECT 1 FROM jobs j WHERE j.run_id = r.id "
                    "AND j.status IN ('pending', 'running'))) AS orphaned_runs"
                )
            )
        ).one()
    counts = {"expired_leases": int(row.expired_leases), "orphaned_runs": int(row.orphaned_runs)}
    if any(counts.values()):
        log.warning("stuck_work_detected", **counts)
    return counts


async def maintenance(
    engine: AsyncEngine, sandbox: SandboxProvisioner | None, stop: asyncio.Event
) -> None:
    while not stop.is_set():
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), MAINTENANCE_SECONDS)
        if stop.is_set():
            break
        try:
            await report_stuck_work(engine)
            if sandbox is not None:
                await asyncio.to_thread(cleanup_sandbox, sandbox)
        except Exception:
            log.exception("maintenance_failed")


def build_worker(
    engine: AsyncEngine, settings: Settings
) -> tuple[Worker, SandboxProvisioner | None]:
    services = build_services(engine, settings)
    worker = Worker(
        engine,
        build_handlers(services),
        on_dead=dead_job_handler(services),
        concurrency=settings.worker_concurrency or 1,
        timings=WorkerTimings(
            lease_seconds=settings.worker_lease_seconds,
            heartbeat_seconds=settings.worker_heartbeat_seconds,
            poll_seconds=settings.worker_poll_seconds,
            shutdown_grace_seconds=settings.worker_shutdown_grace_seconds,
        ),
    )
    return worker, services.sandbox


async def serve(worker: Worker, engine: AsyncEngine, sandbox: SandboxProvisioner | None) -> None:
    """The worker loop plus its sweepers; returns after `worker.stop()` and a drained loop."""
    if sandbox is not None:
        await asyncio.to_thread(cleanup_sandbox, sandbox)
    stop = asyncio.Event()
    background = [
        asyncio.create_task(sweep_approvals(engine, stop)),
        asyncio.create_task(maintenance(engine, sandbox, stop)),
    ]
    try:
        await worker.run()
    finally:
        stop.set()
        await asyncio.gather(*background, return_exceptions=True)


async def main() -> None:
    settings = Settings()
    configure_logging(level=settings.log_level)
    if settings.database_url is None:
        raise ConfigurationError("DATABASE_URL is required for the worker")
    engine = make_engine(settings.database_url.get_secret_value(), **settings.engine_options())
    worker, sandbox = build_worker(engine, settings)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.ensure_future(worker.stop()))
    try:
        await serve(worker, engine, sandbox)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
