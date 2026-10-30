"""`python -m querycure.ops <command>`.

- `retention`: run the operational retention sweep once (cron it). Needs DATABASE_RETENTION_URL,
  a DSN for the `qc_retention` role (never the app's URL).
- `verify-integrity`: the restore check (DEPLOYMENT §4c), read-only. The DSN is read from the
  environment variable named by `--url-env` (default DATABASE_URL_DIRECT), never from argv,
  so it does not show up in process listings or shell history.
- `replay-cutover-check`: read-only; lists experiment replays still in flight with the contract
  they were created under (REPLAY_OUTCOME_AUDIT §18.4). Exit 1 while a legacy one is in flight:
  activation waits for it. Same `--url-env` rule."""

import argparse
import asyncio
import json
import os
import sys

from pydantic import SecretStr
from sqlalchemy import text

from querycure.core.config import Settings
from querycure.core.logging import configure_logging, get_logger
from querycure.db.engine import make_engine
from querycure.ops.integrity import verify_integrity
from querycure.ops.retention import sweep
from querycure.replay.cutover import in_flight_replays

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


def _url(settings: Settings, url_env: str) -> str | None:
    # Settings fields first, so `.env` works; any other name is read from the environment.
    secret = getattr(settings, url_env.lower(), None)
    return secret.get_secret_value() if isinstance(secret, SecretStr) else os.environ.get(url_env)


async def _replay_cutover_check(url_env: str) -> int:
    settings = Settings()
    configure_logging(level=settings.log_level)
    url = _url(settings, url_env)
    if not url:
        print(f"Set {url_env} (a direct, non-pooled DSN).", file=sys.stderr)
        return 2
    engine = make_engine(url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            replays = await in_flight_replays(conn)
            await conn.rollback()
    finally:
        await engine.dispose()
    legacy = [r for r in replays if r.contract == "legacy"]
    print(
        json.dumps(
            {
                "ready": not legacy,
                "in_flight": len(replays),
                "legacy_in_flight": len(legacy),
                "replays": [
                    {
                        "attempt_id": str(r.attempt_id),
                        "replay_run_id": str(r.replay_run_id),
                        "attempt_status": r.attempt_status,
                        "run_status": r.run_status,
                        "contract": r.contract,
                    }
                    for r in replays[:MAX_LISTED_FAILURES]
                ],
            },
            indent=1,
        )
    )
    return 1 if legacy else 0


async def _verify_integrity(url_env: str) -> int:
    settings = Settings()
    configure_logging(level=settings.log_level)
    url = _url(settings, url_env)
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
    cutover = sub.add_parser(
        "replay-cutover-check", help="list in-flight experiment replays and their contract"
    )
    cutover.add_argument("--url-env", default="DATABASE_URL_DIRECT")
    args = parser.parse_args()
    if args.command == "verify-integrity":
        sys.exit(asyncio.run(_verify_integrity(args.url_env)))
    if args.command == "replay-cutover-check":
        sys.exit(asyncio.run(_replay_cutover_check(args.url_env)))
    sys.exit(asyncio.run(_retention()))


if __name__ == "__main__":
    main()
