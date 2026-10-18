"""Operational metrics in the Prometheus text format (OBSERVABILITY §5, Phase 5).

Computed from the metadata database on each scrape, so the numbers survive restarts, cover
every worker, and need no metrics library or sidecar: queue depth, dead and retried jobs,
expired leases (stuck jobs), active and finished runs, run duration, replay outcomes, and
finalization failures. OTel export is deferred (it would add dependencies); these are the
signals the debugging playbook names.

Since 2026-10-18 it also reports live workers (presence rows with their source digest),
model-call outcomes, the server's free daily allowance, metadata connections and experiment
failures by code, so a dead worker, an exhausted quota or a failing sandbox shows without logs.

Access: open in the local profile; elsewhere only with `Authorization: Bearer $METRICS_TOKEN`,
and a 404 (not a 401) without it, so the endpoint's existence is not advertised.
"""

import hmac
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import text

from querycure.api.deps import EngineDep, SettingsDep
from querycure.core.config import FREE_ROUTER, Profile, Settings
from querycure.core.errors import NotFoundError
from querycure.llm.rate_limit import NOT_DISPATCHED_CODES

router = APIRouter(tags=["internal"])
CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

_QUERIES: dict[str, str] = {
    "jobs": "SELECT kind, status, count(*) AS n FROM jobs GROUP BY kind, status",
    "stuck": (
        "SELECT kind, count(*) AS n FROM jobs WHERE status = 'running' "
        "AND locked_until < now() GROUP BY kind"
    ),
    "retried": "SELECT kind, count(*) AS n FROM jobs WHERE attempts > 1 GROUP BY kind",
    "oldest_pending": (
        "SELECT COALESCE(EXTRACT(EPOCH FROM now() - min(run_after)), 0) AS s FROM jobs "
        "WHERE status = 'pending' AND run_after <= now()"
    ),
    "runs": (
        "SELECT status, COALESCE(outcome, 'none') AS outcome, count(*) AS n "
        "FROM investigation_runs WHERE deleted_at IS NULL GROUP BY status, outcome"
    ),
    "durations": (
        "SELECT COALESCE(outcome, 'none') AS outcome, count(*) AS n, "
        "COALESCE(sum(EXTRACT(EPOCH FROM finished_at - started_at)), 0) AS s "
        "FROM investigation_runs WHERE finished_at IS NOT NULL AND started_at IS NOT NULL "
        "GROUP BY outcome"
    ),
    "unsealed": (
        "SELECT count(*) AS n FROM investigation_runs WHERE status IN "
        "('completed', 'failed', 'cancelled') AND finalized_at IS NULL "
        "AND created_at > now() - interval '30 days'"
    ),
    "workers": (
        "SELECT worker_id, source_digest, COALESCE(bench_path, 'none') AS bench_path, "
        "EXTRACT(EPOCH FROM now() - last_seen_at) AS age, stopped_at IS NOT NULL AS stopped "
        "FROM worker_heartbeats WHERE deleted_at IS NULL "
        "AND last_seen_at > now() - interval '1 day'"
    ),
    "llm_calls": (
        "SELECT status, COALESCE(error->>'code', 'none') AS code, count(*) AS n "
        "FROM agent_executions WHERE created_at > now() - interval '1 day' "
        "GROUP BY status, error->>'code'"
    ),
    # The server's free allowance (ADR-0016): same rule as DailyQuota for runs without BYOK.
    "free_today": (
        "SELECT count(*) AS n FROM agent_executions e "
        "JOIN investigation_runs r ON r.id = e.run_id "
        "WHERE e.created_at >= date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' "
        "AND (e.requested_model LIKE :free_suffix OR e.requested_model = :free_router) "
        "AND r.llm_credential_id IS NULL "
        "AND coalesce(e.error->>'code', '') <> ALL(CAST(:local AS TEXT[]))"
    ),
    "connections": (
        "SELECT (SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()) "
        "AS n, current_setting('max_connections')::int AS max"
    ),
    "experiments": (
        "SELECT status, COALESCE(error->>'code', 'none') AS code, count(*) AS n "
        "FROM experiments WHERE created_at > now() - interval '7 days' "
        "GROUP BY status, error->>'code'"
    ),
    "replays": (
        "SELECT kind, status, COALESCE(failure_code, 'none') AS code, count(*) AS n "
        "FROM replay_attempts GROUP BY kind, status, failure_code"
    ),
}


def _label(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _line(name: str, value: float, **labels: Any) -> str:
    rendered = ",".join(f'{k}="{_label(v)}"' for k, v in sorted(labels.items()))
    return f"{name}{{{rendered}}} {value:g}" if rendered else f"{name} {value:g}"


def _alive_after(settings: Settings) -> float:
    """Three missed heartbeats mean the worker is gone (crashed, frozen or partitioned)."""
    return 3 * settings.worker_heartbeat_seconds


def _authorized(request: Request, token: str | None, profile: Profile) -> bool:
    if profile is Profile.LOCAL and token is None:
        return True
    if token is None:
        return False
    supplied = request.headers.get("authorization", "")
    return hmac.compare_digest(supplied.encode(), f"Bearer {token}".encode())


@router.get("/internal/metrics", include_in_schema=False)
async def metrics(request: Request, engine: EngineDep, settings: SettingsDep) -> PlainTextResponse:
    token = settings.metrics_token.get_secret_value() if settings.metrics_token else None
    if not _authorized(request, token, settings.profile):
        raise NotFoundError("Not found.")
    params = {
        "local": list(NOT_DISPATCHED_CODES),
        "free_suffix": "%:free",
        "free_router": FREE_ROUTER,
    }
    async with engine.connect() as conn:
        rows = {
            name: (await conn.execute(text(sql), params if ":local" in sql else {})).all()
            for name, sql in _QUERIES.items()
        }
    alive = [w for w in rows["workers"] if not w.stopped and float(w.age) <= _alive_after(settings)]
    out: list[str] = [
        "# HELP qc_jobs Jobs by kind and status.",
        "# TYPE qc_jobs gauge",
        *(_line("qc_jobs", r.n, kind=r.kind, status=r.status) for r in rows["jobs"]),
        "# HELP qc_jobs_lease_expired Running jobs with an expired lease (stuck until reclaimed).",
        "# TYPE qc_jobs_lease_expired gauge",
        *(_line("qc_jobs_lease_expired", r.n, kind=r.kind) for r in rows["stuck"]),
        "# HELP qc_jobs_retried Jobs that needed more than one attempt.",
        "# TYPE qc_jobs_retried gauge",
        *(_line("qc_jobs_retried", r.n, kind=r.kind) for r in rows["retried"]),
        "# HELP qc_jobs_oldest_pending_seconds Age of the oldest due pending job.",
        "# TYPE qc_jobs_oldest_pending_seconds gauge",
        _line("qc_jobs_oldest_pending_seconds", float(rows["oldest_pending"][0].s)),
        "# HELP qc_runs Runs by status and outcome.",
        "# TYPE qc_runs gauge",
        *(_line("qc_runs", r.n, status=r.status, outcome=r.outcome) for r in rows["runs"]),
        "# HELP qc_run_duration_seconds Finished runs: count and total wall-clock seconds.",
        "# TYPE qc_run_duration_seconds summary",
        *(
            _line("qc_run_duration_seconds_count", r.n, outcome=r.outcome)
            for r in rows["durations"]
        ),
        *(
            _line("qc_run_duration_seconds_sum", float(r.s), outcome=r.outcome)
            for r in rows["durations"]
        ),
        "# HELP qc_runs_terminal_unsealed Terminal runs of the last 30 days without a manifest.",
        "# TYPE qc_runs_terminal_unsealed gauge",
        _line("qc_runs_terminal_unsealed", rows["unsealed"][0].n),
        "# HELP qc_workers_alive Workers seen within 3 heartbeat intervals and not stopped.",
        "# TYPE qc_workers_alive gauge",
        _line("qc_workers_alive", len(alive)),
        "# HELP qc_worker_last_seen_seconds Seconds since each worker's last heartbeat (1 day).",
        "# TYPE qc_worker_last_seen_seconds gauge",
        *(
            _line(
                "qc_worker_last_seen_seconds",
                round(float(w.age), 1),
                worker_id=w.worker_id,
                source_digest=w.source_digest[:12],
                bench_path=w.bench_path,
            )
            for w in rows["workers"]
            if not w.stopped
        ),
        "# HELP qc_llm_calls_24h Model calls of the last 24 hours by status and error code.",
        "# TYPE qc_llm_calls_24h gauge",
        *(
            _line("qc_llm_calls_24h", r.n, status=r.status, error_code=r.code)
            for r in rows["llm_calls"]
        ),
        "# HELP qc_llm_free_requests_today Server free-model requests used today (UTC).",
        "# TYPE qc_llm_free_requests_today gauge",
        _line("qc_llm_free_requests_today", rows["free_today"][0].n),
        "# HELP qc_llm_daily_request_limit The configured free daily request limit.",
        "# TYPE qc_llm_daily_request_limit gauge",
        _line("qc_llm_daily_request_limit", settings.llm_daily_request_limit),
        "# HELP qc_db_connections Connections to the metadata database (all roles).",
        "# TYPE qc_db_connections gauge",
        _line("qc_db_connections", rows["connections"][0].n),
        "# HELP qc_db_max_connections The server's max_connections.",
        "# TYPE qc_db_max_connections gauge",
        _line("qc_db_max_connections", rows["connections"][0].max),
        "# HELP qc_experiments Experiments of the last 7 days by status and error code.",
        "# TYPE qc_experiments gauge",
        *(
            _line("qc_experiments", r.n, status=r.status, error_code=r.code)
            for r in rows["experiments"]
        ),
        "# HELP qc_replay_attempts Replay attempts by kind, status and failure code.",
        "# TYPE qc_replay_attempts gauge",
        *(
            _line("qc_replay_attempts", r.n, kind=r.kind, status=r.status, failure_code=r.code)
            for r in rows["replays"]
        ),
    ]
    return PlainTextResponse("\n".join(out) + "\n", media_type=CONTENT_TYPE)
