import logging
import sys
from typing import Any, TextIO

import structlog

from querycure.core.redaction import redaction_processor


def configure_logging(*, level: str = "INFO", stream: TextIO | None = None) -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            redaction_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.PrintLoggerFactory(file=stream or sys.stdout),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str, **initial: Any) -> Any:
    return structlog.get_logger(name, **initial)
