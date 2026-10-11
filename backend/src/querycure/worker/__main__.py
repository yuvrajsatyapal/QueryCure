"""`python -m querycure.worker`: the separate worker process (ARCHITECTURE: api + worker)."""

import asyncio
import signal

from querycure.core.config import Settings
from querycure.core.errors import ConfigurationError
from querycure.core.logging import configure_logging
from querycure.db.engine import make_engine
from querycure.jobs.handlers import build_handlers, build_services, dead_job_handler
from querycure.worker.runner import Worker, WorkerTimings


async def main() -> None:
    settings = Settings()
    configure_logging(level=settings.log_level)
    if settings.database_url is None:
        raise ConfigurationError("DATABASE_URL is required for the worker")
    engine = make_engine(settings.database_url.get_secret_value())
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
        ),
    )
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.ensure_future(worker.stop()))
    try:
        await worker.run()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
