# Observability

Status: Planned (structured logging Phase 1, events Phase 2, OpenTelemetry Phase 5).

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
| `qd_runs_total` | counter | outcome, profile |
| `qd_run_duration_seconds` | histogram | outcome |
| `qd_llm_calls_total`, `qd_llm_tokens_total` | counter | provider, model, agent, status |
| `qd_llm_latency_seconds` | histogram | provider, agent |
| `qd_tool_calls_total` | counter | tool, status |
| `qd_structured_output_repairs_total` | counter | agent |
| `qd_citations_removed_total` | counter | agent |
| `qd_jobs_queue_depth` | gauge | kind |
| `qd_job_lease_expired_total` | counter | kind |
| `qd_benchmark_cv` | histogram | workload |
| `qd_security_blocks_total` | counter | control |
| `qd_replay_attempts_total` | counter | kind, status, failure_code |
| `qd_finalization_failures_total` | counter | step |
| `qd_sse_connections` | gauge | — |

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

## 8. Alerting (demo, minimal)

Uptime check on `/readyz`; log-based alert on `level=error` rate spike; daily check of `qd_job_lease_expired_total`. No paging — this is a portfolio deployment.
