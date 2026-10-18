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
  It is open in the local profile, and needs `Authorization: Bearer $METRICS_TOKEN` elsewhere (404 otherwise; an empty token counts as unset). In-process counters such as LLM latency histograms are not exported yet; `agent_executions` holds the per-call data.
- **Worker presence (2026-10-18):** every worker process (standalone or embedded) upserts one `worker_heartbeats` row every `WORKER_HEARTBEAT_SECONDS`. The row holds its `source_digest` (SHA-256 of its installed Python sources, which proves which code it runs) and its bench path. A clean shutdown sets `stopped_at`. The digest is also logged at startup (`worker_identity`). Compare it with `python -c "from querycure.worker.heartbeat import source_digest; print(source_digest())"` in the checkout you meant to deploy.
- **Stuck work:** every 5 minutes the worker logs `stuck_work_detected {expired_leases, orphaned_runs}` and drops orphaned sandbox clones.
- **Readiness:** `/readyz` checks the metadata DB and that migrations are at head. Settings fail fast at startup. In the demo profile that includes: a master key is required, no server model key, no private targets, and HTTPS URLs when GitHub sign-in is enabled.
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

## 8. Alerting (demo, minimal)

Uptime check on `/readyz`; log-based alert on `level=error` rate spike; daily check of `qc_jobs_lease_expired`, `qc_workers_alive` (alert at 0 while jobs are pending) and `qc_llm_free_requests_today` against the limit. No paging — this is a portfolio deployment.
