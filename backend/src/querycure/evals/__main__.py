"""`python -m querycure.evals run --suite smoke [--mode replay|record] [--model M]`."""

import argparse
import asyncio
import datetime as dt
import json
import sys

from querycure.core.config import Settings
from querycure.evals.cases import EVALS_DIR, load_cases
from querycure.evals.recording import model_slug
from querycure.evals.runner import CaseResult, QuotaLedger, RequestCap, check_model, run_case


def _admin_url(settings: Settings, override: str | None) -> str:
    if override:
        return override
    if settings.database_migration_url is None:
        raise SystemExit("Set DATABASE_MIGRATION_URL (owner role) or pass --admin-url.")
    base, _, _ = settings.database_migration_url.get_secret_value().rpartition("/")
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
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
