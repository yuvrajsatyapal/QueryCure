# Observability

Status: structured logging (Phase 1), events (Phase 2), and **Phase 5 operations implemented**: correlation IDs, DB-derived metrics, stuck-work detection, graceful drain and retention. **OpenTelemetry tracing/export and LangSmith are deferred**: they need new dependencies, and nothing in Phase 5 required them to ship (see PHASE_5_REPORT).

## 0. Implemented in Phase 5
- **Correlation:** API log lines carry `request_id` (response header `X-Request-ID`). Worker log lines written while a job runs, including the graph, engine and LLM layers, carry `job_id`, `job_kind`, `run_id` and `attempt` (structlog contextvars; `test_operations.py`).
- **Metrics:** `GET /api/v1/internal/metrics`, Prometheus text format, computed from the metadata DB on each scrape:
  - `qc_jobs{kind,status}`, `qc_jobs_lease_expired`, `qc_jobs_retried`, `qc_jobs_oldest_pending_seconds`;
  - `qc_runs{status,outcome}`, `qc_run_duration_seconds_{count,sum}`;
  - `qc_runs_terminal_unsealed` (finalization failures);
  - `qc_replay_attempts{kind,status,failure_code}`;
  - since 2026-10-18:
    - `qc_workers_alive` (seen within 3 heartbeat intervals and not stopped) and `qc_worker_last_seen_seconds{worker_id,source_digest,bench_path}`, from `worker_heartbeats`;
    - `qc_llm_calls_24h{status,error_code}`;
    - `qc_llm_free_requests_today` and `qc_llm_daily_request_limit` (the server allowance, same rule as `DailyQuota`);
    - `qc_db_connections` and `qc_db_max_connections`;
    - `qc_experiments{status,error_code}` (last 7 days).
  - since 2026-10-23, **per API process** (`api/process_metrics.py`; reset on restart, so read them with `qc_process_uptime_seconds`): `qc_http_responses_total{status_class}`, `qc_http_unhandled_errors_total`, `qc_sse_streams_active`, `qc_sse_streams_closed_total{outcome="ended|client_gone|error"}`. Labels are fixed sets (never paths or IDs). The demo runs one API process, so per-process is the whole picture; with several, sum across them.
  It is open in the local profile, and needs `Authorization: Bearer $METRICS_TOKEN` elsewhere (404 otherwise; an empty token counts as unset). In-process counters such as LLM latency histograms are not exported yet; `agent_executions` holds the per-call data.
- **Worker presence (2026-10-18):** every worker process (standalone or embedded) upserts one `worker_heartbeats` row every `WORKER_HEARTBEAT_SECONDS`. The row holds its `source_digest` (SHA-256 of its installed Python sources, which proves which code it runs) and its bench path. A clean shutdown sets `stopped_at`. The digest is also logged at startup (`worker_identity`). Compare it with `python -c "from querycure.worker.heartbeat import source_digest; print(source_digest())"` in the checkout you meant to deploy.
- **Stuck work:** every 5 minutes the worker logs `stuck_work_detected {expired_leases, orphaned_runs}` and drops orphaned sandbox clones.
- **Readiness:** `/readyz` checks the metadata DB and that migrations are at head. It does **not** check the embedded worker: if that task dies, the API stays ready, its heartbeat stops and `qc_workers_alive` drops to 0 within three heartbeat intervals (alert on that, §8). Settings fail fast at startup. In the demo profile that includes: a master key is required, no server model key, no private targets, HTTPS URLs when OAuth sign-in is enabled, and (2026-10-23) CORS origins that are bare https origins (http only on loopback, never `*`), https public URLs, a bare `COOKIE_DOMAIN`, a `METRICS_TOKEN` of at least 32 characters, and the web origin listed in `CORS_ORIGINS`. The API itself also refuses to start without `DATABASE_URL` or `CORS_ORIGINS` (`serving_problems`); the worker and ops commands do not need them.
- **SSE failures (2026-10-23):** a server-side error after a stream has started is logged as `sse_stream_failed {run_id, last_seq}` and counted (`outcome="error"`); the stream then ends so the browser resumes with `Last-Event-ID`. Each database round trip of a stream is shielded from client disconnects (F1 root cause, [report](../reports/PRODUCTION_HARDENING_2026-10-23.md)).
- **No parameter values in error text (2026-10-23):** metadata engines use `hide_parameters=True`, so logged tracebacks of statement errors keep the SQL but not the bound values. PostgreSQL's own message can still quote an input value (e.g. "invalid input syntax for type integer: …"). Groq keys (`gsk_…`) are now masked inside log values too.
- **Timeouts and pools:** metadata connections carry server-side `statement_timeout` and `idle_in_transaction_session_timeout` as startup options; pool size, overflow and timeout are configurable.

## 1. Three audiences, three channels

| Channel | Audience | Storage | Purpose |
|---|---|---|---|
| **Investigation events** | End user (UI timeline), replay | `investigation_events` (metadata DB) | Product-level narrative of a run; durable, replayable |
| **Structured logs** | Developer/operator | stdout JSON → host log drain | Debugging, errors, audit of security decisions |
| **Traces & metrics** | Developer/operator | OTLP → any backend (local: Jaeger/Grafana LGTM container; demo: free tier of a hosted backend, optional) | Latency breakdown, LLM/tool timing, bottlenecks |
| LangSmith (optional) | Developer | LangSmith | Prompt/response inspection during agent development; **disabled by default**, never in demo profile with user data unless the user opts in |

Events are product data and must not depend on the observability stack being up.

## 2. Correlation

Every log line, span, and event carries: `request_id` (API), `run_id`, `investigation_id`, `job_id` (worker), `node`, `agent`, `attempt`. The worker sets these via `structlog.contextvars` and OTel baggage at job start and node entry.

## 3. Logging

- JSON via structlog; fields: `ts` (UTC ISO), `level`, `event`, `logger`, correlation IDs, `duration_ms` where relevant.
- Mandatory redaction processor (see [SECURITY §7](../architecture/SECURITY.md#7-credential--key-management)).
- Security-relevant decisions are logged at `info` with `security=true`: SQL rejected (code, statement type — not the text), SSRF block (resolved IP class, not the full host if user-private), role refused, approval decisions, CSRF failures, rate-limit hits.
- LLM calls log provider, model, prompt version, token counts, latency, outcome — **not** prompt/response bodies (those go to artifacts `agent_output`, and optionally LangSmith).

## 4. Traces (OpenTelemetry)

Instrumentation: FastAPI, SQLAlchemy/psycopg, httpx (LLM providers), plus manual spans:

```
job.run (run_id)
 ├─ graph.node intake
 ├─ graph.node collect_context
 │   ├─ gateway.catalog_query table_stats
 │   └─ gateway.explain
 ├─ graph.node query_analyzer
 │   ├─ llm.call (model, prompt_version, tokens)
 │   └─ tool.call get_plan_node
 ├─ graph.node run_experiment
 │   ├─ sandbox.clone
 │   ├─ benchmark.block (arm order, n)
 │   └─ benchmark.explain_analyze
 └─ graph.node write_report
```

Span attributes never include secrets or full SQL text (use `query_fingerprint`).

## 5. Metrics

| Metric | Type | Labels |
|---|---|---|
| `qc_runs_total` | counter | outcome, profile |
| `qc_run_duration_seconds` | histogram | outcome |
| `qc_llm_calls_total`, `qc_llm_tokens_total` | counter | provider, model, agent, status |
| `qc_llm_latency_seconds` | histogram | provider, agent |
| `qc_tool_calls_total` | counter | tool, status |
| `qc_structured_output_repairs_total` | counter | agent |
| `qc_citations_removed_total` | counter | agent |
| `qc_jobs_queue_depth` | gauge | kind |
| `qc_job_lease_expired_total` | counter | kind |
| `qc_benchmark_cv` | histogram | workload |
| `qc_security_blocks_total` | counter | control |
| `qc_replay_attempts_total` | counter | kind, status, failure_code |
| `qc_finalization_failures_total` | counter | step |
| `qc_sse_connections` | gauge | — |

Exported via OTel metrics; in local profile also viewable via a `/internal/metrics` page in dev builds only.

## 6. Agent traces in the product

The UI timeline is derived from events, not from OTel. For deeper debugging, a dev-only "Agent trace" drawer shows per `agent_executions` row: prompt version, model, token usage, latency, validation errors, repair attempts, and a link to the stored `agent_output` artifact.

## 7. Debugging playbook

| Symptom | Look at |
|---|---|
| Run stuck in `running` | `jobs.locked_until`, worker logs for `job_id`, last `investigation_events.seq`, LangGraph checkpoint timestamp |
| Agent produced nonsense | `agent_executions` (repairs, removed citations), `agent_output` artifact, context summary artifact, prompt version |
| Verdict surprising | `benchmark_runs` per block, CV, environment fingerprint, `verification_results.reasons`, plan artifacts |
| SSE gaps | client `Last-Event-ID`, API logs for LISTEN reconnects, `(run_id, seq)` continuity |
| Slow API | trace for request_id; metadata DB slow query log (`log_min_duration_statement=200ms` in local) |
| Mode B failures | `security=true` logs, capability JSON on connection |
| Nothing is being picked up | `qc_workers_alive` = 0 (no live worker) vs `qc_jobs_oldest_pending_seconds` rising (workers alive but busy or stuck) |
| Runs end `MODEL_UNAVAILABLE` / quota stop | `qc_llm_calls_24h{error_code}` (rate limited, timeout, invalid output, circuit open); `qc_llm_free_requests_today` vs `qc_llm_daily_request_limit` |
| Benchmarks failing | `qc_experiments{status="failed",error_code}` (e.g. `SANDBOX_UNAVAILABLE`, `SANDBOX_BUSY`); worker `benchmark_path_relay` warning; experiment `result.transport_floor` |
| Connection exhaustion | `qc_db_connections` vs `qc_db_max_connections`; pool timeouts in API logs (503 `SERVICE_UNAVAILABLE`) |
| Replay failing | `qc_replay_attempts{status="failed",failure_code}` |

## 8. Alerting (restricted trial, low cost)

No paging: this is a restricted trial. Three free mechanisms cover the failure modes that matter, with nothing to host:

1. **Uptime monitor** (any free HTTP monitor, 1–5 min interval): `GET https://api.<domain>/api/v1/readyz` must return 200 (database reachable, migrations current), and `https://app.<domain>/` must return 200.
2. **Metrics scrape with alert rules** (a hosted Prometheus-compatible free tier that can scrape a URL with a bearer token, or a scheduled job that fetches `/internal/metrics` with `METRICS_TOKEN` and compares values). Never put the token in a URL.

   | Rule | Condition | Severity | Meaning |
   |---|---|---|---|
   | Worker down | `qc_workers_alive == 0` for 2 min | critical | Nothing claims jobs (also covers a crashed embedded worker, which `/readyz` does not see) |
   | Queue backlog | `qc_jobs_oldest_pending_seconds > 300` | warning | Workers alive but saturated or stuck |
   | Stuck jobs | `qc_jobs_lease_expired > 0` for 10 min | warning | A worker died mid-job; the lease reaper should clear it |
   | Dead jobs | `qc_jobs{status="dead"}` increased | warning | A job exhausted its retries |
   | Unsealed runs | `qc_runs_terminal_unsealed > 0` for 10 min | critical | Finalization failed; a report is missing |
   | API errors | `increase(qc_http_responses_total{status_class="5xx"}[10m]) > 5` or `increase(qc_http_unhandled_errors_total[10m]) > 0` | warning | Bugs or an outage (503s are counted as 5xx too) |
   | SSE failures | `increase(qc_sse_streams_closed_total{outcome="error"}[10m]) > 0` | warning | Server-side stream failures (clients reconnect, but it is a bug) |
   | Connections | `qc_db_connections / qc_db_max_connections > 0.8` | warning | Pool or connection leak; Neon free has a low limit |
   | Free quota | `qc_llm_free_requests_today >= qc_llm_daily_request_limit` | info | Expected under BYOK only when the server key is used (local) |

   The per-process counters reset on restart; `increase()` handles that, and a stateless checker should compare against `qc_process_uptime_seconds`.
3. **Log alerts** in the host's log drain: any `unhandled_error`, `sse_stream_failed`, `worker_teardown_timeout` or `stuck_work_detected` with non-zero counts. Logs are JSON on stdout and redacted before they are written (SECURITY §7).
