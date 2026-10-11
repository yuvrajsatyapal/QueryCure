"""Job-kind → handler registry used by the worker entrypoint."""

from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.core.config import Settings
from querycure.jobs.queue import JobKind
from querycure.worker.runner import Handler


def build_handlers(engine: AsyncEngine, settings: Settings) -> dict[JobKind, Handler]:
    # run_start / run_resume are registered when the investigation graph lands (T2.10).
    del engine, settings
    return {}
