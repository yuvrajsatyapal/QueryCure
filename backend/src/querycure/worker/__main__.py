"""`python -m querycure.worker`: the separate worker process (ARCHITECTURE: api + worker)."""

import asyncio
import contextlib
import signal

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


async def main() -> None:
    settings = Settings()
    configure_logging(level=settings.log_level)
    if settings.database_url is None:
        raise ConfigurationError("DATABASE_URL is required for the worker")
    engine = make_engine(settings.database_url.get_secret_value())
    services = build_services(engine, settings)
    if services.sandbox is not None:
        await asyncio.to_thread(cleanup_sandbox, services.sandbox)
    worker = Worker(
        engine,
        build_handlers(services),
        on_dead=dead_job_handler(services),
        concurrency=settings.worker_concurrency or 1,
        timings=WorkerTimings(
            lease_seconds=settings.worker_lease_seconds,
            heartbeat_seconds=settings.worker_heartbeat_seconds,
            poll_seconds=settings.worker_poll_seconds,
        ),
    )
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.ensure_future(worker.stop()))
    stop = asyncio.Event()
    sweeper = asyncio.create_task(sweep_approvals(engine, stop))
    try:
        await worker.run()
    finally:
        stop.set()
        await sweeper
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
