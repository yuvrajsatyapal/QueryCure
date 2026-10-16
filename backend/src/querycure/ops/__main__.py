"""`python -m querycure.ops retention`: run the operational retention sweep once (cron it).

Needs DATABASE_RETENTION_URL, a DSN for the `qc_retention` role (never the app's URL)."""

import argparse
import asyncio
import sys

from querycure.core.config import Settings
from querycure.core.logging import configure_logging, get_logger
from querycure.db.engine import make_engine
from querycure.ops.retention import sweep

log = get_logger(__name__)


async def _retention() -> int:
    settings = Settings()
    configure_logging(level=settings.log_level)
    if settings.database_retention_url is None:
        print("Set DATABASE_RETENTION_URL (the qc_retention role).", file=sys.stderr)
        return 2
    engine = make_engine(settings.database_retention_url.get_secret_value())
    try:
        result = await sweep(engine)
    finally:
        await engine.dispose()
    log.info("retention_sweep_done", **result.__dict__)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m querycure.ops")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("retention", help="delete expired sessions, idle buckets, wiped keys")
    parser.parse_args()
    sys.exit(asyncio.run(_retention()))


if __name__ == "__main__":
    main()
