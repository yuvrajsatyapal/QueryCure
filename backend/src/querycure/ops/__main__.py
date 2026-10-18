"""`python -m querycure.ops <command>`.

- `retention`: run the operational retention sweep once (cron it). Needs DATABASE_RETENTION_URL,
  a DSN for the `qc_retention` role (never the app's URL).
- `verify-integrity`: the restore check (DEPLOYMENT §4c), read-only. The DSN is read from the
  environment variable named by `--url-env` (default DATABASE_URL_DIRECT), never from argv,
  so it does not show up in process listings or shell history."""

import argparse
import asyncio
import json
import os
import sys

from pydantic import SecretStr

from querycure.core.config import Settings
from querycure.core.logging import configure_logging, get_logger
from querycure.db.engine import make_engine
from querycure.ops.integrity import verify_integrity
from querycure.ops.retention import sweep

log = get_logger(__name__)

MAX_LISTED_FAILURES = 20


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


async def _verify_integrity(url_env: str) -> int:
    settings = Settings()
    configure_logging(level=settings.log_level)
    # Settings fields first, so `.env` works; any other name is read from the environment.
    secret = getattr(settings, url_env.lower(), None)
    url = secret.get_secret_value() if isinstance(secret, SecretStr) else os.environ.get(url_env)
    if not url:
        print(f"Set {url_env} (a direct, non-pooled DSN).", file=sys.stderr)
        return 2
    engine = make_engine(url)
    try:
        result = await verify_integrity(engine)
    finally:
        await engine.dispose()
    print(
        json.dumps(
            {
                "ok": result.ok,
                "artifacts_checked": result.artifacts_checked,
                "artifact_failures": len(result.artifact_failures),
                "reports_checked": result.reports_checked,
                "report_statuses": result.report_statuses,
                "report_failures": len(result.report_failures),
                "failed_artifact_ids": result.artifact_failures[:MAX_LISTED_FAILURES],
                "failed_run_ids": result.report_failures[:MAX_LISTED_FAILURES],
            },
            indent=1,
        )
    )
    return 0 if result.ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m querycure.ops")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("retention", help="delete expired sessions, idle buckets, wiped keys")
    verify = sub.add_parser(
        "verify-integrity", help="re-verify every artifact and replay every sealed report"
    )
    verify.add_argument("--url-env", default="DATABASE_URL_DIRECT")
    args = parser.parse_args()
    if args.command == "verify-integrity":
        sys.exit(asyncio.run(_verify_integrity(args.url_env)))
    sys.exit(asyncio.run(_retention()))


if __name__ == "__main__":
    main()
