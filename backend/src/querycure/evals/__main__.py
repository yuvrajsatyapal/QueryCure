"""`python -m querycure.evals run --suite smoke [--mode replay|record] [--model M]`."""

import argparse
import asyncio
import datetime as dt
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import psycopg

from querycure.core.config import Settings
from querycure.evals.cases import EVALS_DIR, load_cases
from querycure.evals.preflight import FLOOR_SAMPLES, quiet_host
from querycure.evals.recording import model_slug
from querycure.evals.runner import CaseResult, QuotaLedger, RequestCap, check_model, run_case

_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
# The compose metadata service, for evals run inside the worker container (ADR-0020).
_LOCAL_SERVICES = frozenset({"metadata-db"})


def _admin_url(settings: Settings, override: str | None) -> str:
    if override:
        # Evals CREATE and DROP scratch databases: an explicit URL must be local too.
        if urlsplit(override).hostname not in _LOCAL_HOSTS | _LOCAL_SERVICES:
            raise SystemExit(
                "--admin-url must be a local server (127.0.0.1, localhost, ::1 or the compose "
                "service metadata-db): evals create and drop scratch databases there."
            )
        return override
    if settings.database_migration_url is None:
        raise SystemExit("Set DATABASE_MIGRATION_URL (owner role) or pass --admin-url.")
    owner = settings.database_migration_url.get_secret_value()
    # Evals CREATE and DROP scratch databases: never do that implicitly on a hosted server
    # (e.g. Neon) just because .env points the app there.
    if urlsplit(owner).hostname not in _LOCAL_HOSTS:
        raise SystemExit(
            "DATABASE_MIGRATION_URL is not a local server; pass --admin-url to choose where "
            "eval scratch databases are created."
        )
    base, _, _ = owner.partition("?")[0].rpartition("/")
    return f"{base}/postgres"


def _print(results: list[CaseResult]) -> None:
    for r in results:
        if r.passed:
            mark = "XPASS" if r.case.known_failures.get(r.model) else "PASS"
        else:
            mark = "DIVERGED" if r.diverged else "XFAIL" if r.expected_failure else "FAIL"
        print(f"{mark}  {r.case.id}")
        if r.expected_failure:
            print(f"      known baseline failure: {r.expected_failure}")
        if r.error:
            print(f"      error: {r.error}")
        if r.saved is False:
            print(
                "      not saved: the recorded run failed its checks; the existing recording "
                "is kept (--keep-failing saves it anyway)"
            )
        if r.provenance.get("measurements"):
            fixture = r.provenance.get("measurement_fixture_sha256")
            print(
                f"      measurements: {r.provenance['measurements']}"
                + (
                    f" (prerecorded {r.provenance.get('measurement_recorded_on')}, "
                    f"sha256 {fixture[:12]})"
                    if fixture
                    else ""
                )
            )
        if r.score:
            for c in r.score.checks:
                print(f"      {'ok ' if c.passed else 'BAD'} {c.name}: {c.detail}")
            m = r.score.metrics
            print(
                f"      llm_calls={m['llm_calls']} "
                f"tokens={m['input_tokens']}+{m['output_tokens']} tools={m['tool_calls']} "
                f"dropped_claims={m['claims_dropped_by_citation_validator']} "
                f"served={m['served_models']}"
            )
    passed = sum(r.passed for r in results)
    xfail = sum(r.expected_failure is not None for r in results)
    diverged = sum(r.diverged for r in results)
    print(
        f"\n{passed}/{len(results)} cases passed, {xfail} known baseline failure(s), "
        f"{diverged} diverged on live measurements (not passed)"
    )


def _quiet_sandbox(settings: Settings) -> tuple[bool, str]:
    """Round trips to the sandbox before any model request (evals/preflight.py)."""
    if settings.sandbox_admin_url is None:
        return False, "SANDBOX_ADMIN_URL is not set"
    with psycopg.connect(settings.sandbox_admin_url.get_secret_value(), connect_timeout=5) as c:
        c.execute("SELECT 1")
        samples = []
        for _ in range(FLOOR_SAMPLES):
            start = time.perf_counter_ns()
            c.execute("SELECT 1").fetchone()
            samples.append(time.perf_counter_ns() - start)
    return quiet_host(samples, path=settings.bench_path)


async def _run(args: argparse.Namespace) -> int:
    settings = Settings()
    model = args.model or settings.llm_model
    check_model(model, settings)
    cases = [c for c in load_cases() if args.suite in c.suites]
    if args.case:
        cases = [c for c in cases if c.id in set(args.case)]
    cap = None
    if args.mode == "record":
        today = dt.datetime.now(dt.UTC).date().isoformat()
        ledger = QuotaLedger(EVALS_DIR / ".quota", today)
        left = settings.llm_daily_request_limit - ledger.used() - args.used_elsewhere
        if left <= 0:
            print(
                f"Today's free request limit ({settings.llm_daily_request_limit}, "
                "LLM_DAILY_REQUEST_LIMIT) is used up; record again after 00:00 UTC."
            )
            return 2
        if any(c.workload for c in cases) and not args.skip_quiet_check:
            ok, detail = _quiet_sandbox(settings)
            print(f"pre-flight: {detail}")
            if not ok:
                print(
                    "Not recording: a contended host makes Mode C benchmarks inconclusive and "
                    "wastes free requests. Retry when it is quiet (or --skip-quiet-check)."
                )
                return 3
        allowed = min(args.max_requests, left)
        cap = RequestCap(allowed, ledger)
        print(f"recording with at most {allowed} free requests ({left} left today)")
    results: list[CaseResult] = []
    for case in cases:
        result = await run_case(
            case,
            mode=args.mode,
            model=model,
            settings=settings,
            admin_url=_admin_url(settings, args.admin_url),
            cap=cap,
            measurements=args.measurements,
            export_dir=args.export_demo,
            capture_context=args.capture_context,
            keep_failing=args.keep_failing,
        )
        results.append(result)
    _print(results)
    if args.mode == "record" or args.save_results:
        out = EVALS_DIR / "results"
        out.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        path = out / f"{stamp}-{args.suite}-{args.mode}-{model_slug(model)}.json"
        path.write_text(
            json.dumps(
                {
                    "suite": args.suite,
                    "mode": args.mode,
                    "measurements": args.measurements,
                    "requested_model": model,
                    "run_at": stamp,
                    "cases": [
                        {
                            "case": r.case.id,
                            "passed": r.passed,
                            "known_failure": r.expected_failure,
                            "error": r.error,
                            "checks": [
                                {"name": c.name, "passed": c.passed, "detail": c.detail}
                                for c in (r.score.checks if r.score else [])
                            ],
                            "metrics": r.score.metrics if r.score else None,
                            "provenance": r.provenance,
                        }
                        for r in results
                    ],
                },
                indent=2,
            )
            + "\n"
        )
        print(f"results: {path.relative_to(EVALS_DIR.parent)}")
    return 0 if all(r.acceptable for r in results) else 1


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m querycure.evals")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run eval cases")
    run.add_argument("--suite", default="smoke", choices=["smoke", "full"])
    run.add_argument("--mode", default="replay", choices=["replay", "record"])
    run.add_argument("--model", help="model id (default: LLM_MODEL); must be free (ADR-0016)")
    run.add_argument("--case", action="append", help="run only these case ids")
    run.add_argument("--max-requests", type=int, default=40, help="record mode request cap")
    run.add_argument("--admin-url", help="owner URL for creating throwaway databases")
    run.add_argument(
        "--used-elsewhere",
        type=int,
        default=0,
        help="free requests already spent today outside eval recording (e.g. live runs)",
    )
    run.add_argument("--save-results", action="store_true", help="also save replay results")
    run.add_argument(
        "--capture-context",
        action="store_true",
        help="fixture replay: read the sandbox context live and, if every prompt still "
        "matches exactly, store it in the measurement fixture (needs the sandbox)",
    )
    run.add_argument(
        "--keep-failing",
        action="store_true",
        help="record mode: save a recording even when it fails its checks (replaces the "
        "existing one)",
    )
    run.add_argument(
        "--skip-quiet-check",
        action="store_true",
        help="record mode: skip the sandbox round-trip pre-flight (contended host check)",
    )
    run.add_argument(
        "--export-demo",
        type=Path,
        help="replay mode: also write a demo bundle per passing case into this directory",
    )
    run.add_argument(
        "--measurements",
        default="fixture",
        choices=["fixture", "live"],
        help="Mode C replay: prerecorded measurement fixtures (deterministic, default) or a "
        "live re-benchmark (environment-dependent; DIVERGED when measurements differ)",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
