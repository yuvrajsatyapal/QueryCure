# Implementation Backlog

IDs `T<phase>.<n>`. Priority: **P0** blocks the phase exit, **P1** needed for phase completeness, **P2** nice-to-have. "Deps" lists task IDs. Acceptance criteria are what a reviewer checks; each task also needs its tests (TDD for deterministic logic).

## Phase 1 — Foundation

| ID | Task | Pri | Deps | Acceptance criteria |
|---|---|---|---|---|
| T1.1 | Repo scaffolding: `backend/` (uv, ruff, mypy, pytest, import-linter), `frontend/` (Next.js, Tailwind, shadcn, Vitest), `infra/docker/compose.yaml` (metadata-db, sandbox-db) | P0 | — | `uv run pytest`, `pnpm build`, `docker compose up` all succeed on a clean clone |
| T1.2 | CI workflow `ci.yml` (lint, types, unit, build) | P0 | T1.1 | Green on main; fails on a deliberate type error |
| T1.3 | `core/`: settings (profiles), structlog + redaction, error types, AES-GCM crypto helper | P0 | T1.1 | Redaction test: secrets never in captured logs; crypto round-trip + tamper tests |
| T1.4 | Alembic baseline: extension, `qc_app`/`qc_retention` roles, `set_updated_at()`, `users`, `sessions`, `database_connections`, `artifacts`, `run_artifacts` | P0 | T1.1 | Upgrade from empty works; conventions per ADR-0006 |
| T1.5 | Session API (`POST /session`, `GET /me`), CSRF middleware, error envelope | P0 | T1.3, T1.4 | Anonymous + local sessions; CSRF negative test |
| T1.6 | `sql/` parser, validator, fingerprint | P0 | T1.1 | Full validator suite (TESTING_STRATEGY §2) |
| T1.7 | `plans/` parser + metrics (PG 13–17 fixtures) | P0 | T1.1 | Loops-aware self time matches hand-computed fixtures |
| T1.8 | Canonicalization profiles (`qc-json-v1`, `qc-text-v1`, `qc-raw-v1`) + artifact store with profile-tagged digests | P0 | T1.4 | Golden-vector suite (REPLAY_ENGINE §2.4) passes on Python 3.12 and 3.13; integrity failure detected; canonicalizer rejects non-primitive input; integration tests for insert/dedupe/concurrent-insert/retrieval run as restricted `qc_app` role (TESTING_STRATEGY §3) |
| T1.9 | `connectors/ssrf_guard.py` | P0 | T1.3 | All SSRF security cases pass |
| T1.10 | Hardened sessions + inspection gateway + catalog templates + capabilities | P0 | T1.6, T1.9 | Integration: restricted role works; superuser refused; DML blocked at validator and at read-only txn; timeouts enforced; unqualified user-defined function (resolved via `search_path`) refused by the `pg_proc` check |
| T1.11 | Statistics redaction (no MCV/histogram values) | P0 | T1.10 | Test asserts gateway output contains no `most_common_vals` |
| T1.12 | Connections API (CRUD + test + explain + schema) | P0 | T1.5, T1.10 | Responses contain no secrets (schema scan test) |
| T1.13 | Inspect API (`/inspect/sql|plan|schema`), upload limits | P0 | T1.6–T1.8 | 413 on oversize, 422 on invalid; artifacts stored |
| T1.14 | Workload generators: `orders_ecommerce`, `rewrite_trap`, `no_benefit` + `GET /workloads` | P0 | T1.1 | Deterministic: same seed → same table checksums |
| T1.15 | Frontend shell: tokens.css, theme toggle, AppShell, nav, API client + case conversion + generated types | P0 | T1.1 | Token classes only; dark/light switch; Vitest for case conversion |
| T1.16 | Connections page | P1 | T1.12, T1.15 | Add/test/delete; capability checklist; SSRF error inline |
| T1.17 | Workspace draft: SqlEditor (CodeMirror), plan upload, PlanTreeTable (param sets editor deferred to Phase 2, see CURRENT_PHASE) | P0 | T1.13, T1.15 | Paste plan → tree renders; keyboard navigation works |
| T1.18 | Basic React Flow plan graph | P1 | T1.17 | Graph and tree show the same nodes; hottest node accented |
| T1.19 | README "Run locally" section verified | P1 | all | Fresh clone instructions tested |

## Phase 2 — Multi-agent intelligence

| ID | Task | Pri | Deps | Acceptance criteria |
|---|---|---|---|---|
| T2.1 | Migrations: investigations, runs (+`last_event_seq`), events, agent/tool executions, evidence, hypotheses, jobs | P0 | T1.4 | Conventions; `transition_run` enforces state machine; `investigation_events` grants (INSERT/SELECT + sequence USAGE) for `qc_app` with grant tests |
| T2.2 | Job queue (claim/lease/heartbeat/retry/dead-letter/dedupe) + worker entrypoint | P0 | T2.1 | Concurrency test: no double execution; lease reclaim works |
| T2.3 | Event emitter (same-txn insert + NOTIFY) + SSE endpoint with resume + history endpoint | P0 | T2.1 | Exactly-once delivery across reconnect test |
| T2.4 | LLM layer: providers, structured output + repair, env-key fallback, rate-limit backoff | P0 | T1.3 | Fake-model tests for repair and backoff; no keys in logs |
| T2.5 | `InvestigationState`, budgets, budget_guard, cancellation checks | P0 | T2.1 | Budget exhaustion routes to report |
| T2.6 | Nodes: intake, collect_context (deterministic) | P0 | T2.5, T1.10 | Evidence created with deterministic IDs |
| T2.7 | Evidence store + citation validator + fencing | P0 | T2.6 | Uncited claims removed; retry threshold; injection fixture |
| T2.8 | Supervisor plan + synthesize_hypotheses | P0 | T2.7 | Routing unit tests; disagreement kept as separate hypotheses |
| T2.9 | Query Analyzer, Index Strategist, Workload Investigator (+ tools, prompts) | P0 | T2.8 | Eval smoke on 3 workloads |
| T2.10 | Graph assembly with `Send` fan-out + Postgres checkpointer + resume | P0 | T2.9 | Kill/restart test passes |
| T2.11 | Investigations/runs API (create, list, detail, cancel, findings, evidence) | P0 | T2.2, T2.3 | Idempotency-Key behaviour; 404 cross-user |
| T2.12 | Frontend: start run (incl. param sets editor deferred from T1.17), AgentTimeline (SSE → query cache), Findings tab, EvidenceChip → plan highlight | P0 | T2.11 | Playwright with stubbed LLM |
| T2.13 | History page | P1 | T2.11 | Cursor pagination; soft delete + undo |
| T2.14 | Eval runner, recordings format, first 5 cases | P0 | T2.9 | `python -m querycure.evals run --suite smoke` deterministic |

## Phase 3 — Optimization & benchmarking

| ID | Task | Pri | Deps | Acceptance criteria |
|---|---|---|---|---|
| T3.1 | Migrations: candidates, approval_requests, experiments, benchmark_runs | P0 | T2.1 | Migrations apply; `benchmark_runs` append-only grants with grant tests |
| T3.2 | Sandbox provisioner (template build, clone, drop, advisory lock, orphan cleanup) | P0 | T1.14 | No orphan clones after failure tests |
| T3.3 | Remaining workloads: `join_fanout`, `stale_stats`, `index_regression` | P0 | T1.14 | Deterministic |
| T3.4 | Benchmark schedule + timing + cancellation | P0 | T3.2 | Balanced, seeded schedule; cancel within one block; samples stored as integer ns; `EnvironmentFingerprint` captured |
| T3.5 | Correctness fingerprints with `qc-row-v1` (ordered/multiset, ties, truncation) | P0 | T3.4 | Unit + `rewrite_trap` integration; row-profile golden vectors |
| T3.6 | Stats (median, p95 rule, CV, bootstrap CI) | P0 | — | Unit + property tests |
| T3.7 | Verdict gates 1–6 + tournament ranking | P0 | T3.5, T3.6 | Benchmark-engine eval table passes |
| T3.8 | DDL allowlist + candidate SQL validation | P0 | T1.6 | Security tests |
| T3.9 | Optimization Engineer node + prompts + eval cases | P0 | T2.10, T3.8 | Proposes composite index on `orders_ecommerce` |
| T3.10 | Approval gate (interrupt/resume) + approvals API + expiry | P0 | T2.10, T3.1 | No DDL without approval (test); expiry → inconclusive |
| T3.11 | run_experiment node + loop back on rejection (bounded rounds) | P0 | T3.7, T3.10 | Round limit respected |
| T3.12 | UI: ApprovalCard, Tournament tab, Benchmark comparison | P0 | T3.11 | Playwright flow through approval |
| T3.13 | Export prerecorded demo fixtures with provenance | P1 | T3.11 | `provenance=prerecorded` enforced on import |

## Phase 4 — Verification & replay

| ID | Task | Pri | Deps | Acceptance criteria |
|---|---|---|---|---|
| T4.1 | Migrations: verification_results, investigation_reports, replay_manifests, replay_attempts, run finalization columns | P0 | T3.1 | Grants for new tables follow the per-table rule; all grant tests pass |
| T4.2 | Benchmark Auditor (downgrade-only) | P0 | T3.7 | Cannot upgrade (unit test); eval downgrade rate tracked |
| T4.3 | Plan diff (structural + metrics) + API + UI diff mode | P0 | T1.7 | Fixture diffs correct |
| T4.4 | Report builder@1 + md renderer@1 (pure, versioned) + MD/JSON export with manifest digest footer + provenance scan | P0 | T4.1 | Unlabeled-number test; byte-identical rebuild test |
| T4.5 | `finalize_run` (atomic): cutoff, `qc-events-v1` digest, report, manifest, status; emitter/repository sealing | P0 | T4.4 | Finalization fault-injection and idempotency tests (TESTING_STRATEGY §3) |
| T4.6 | Report replay attempts: ordered checks, status + failure codes, renderer fallback | P0 | T4.5 | Every code in REPLAY_ENGINE §8.1 reachable from a fixture; zero LLM calls |
| T4.7 | Experiment replay (preconditions, replay run, same seed) + statistical comparison + environment diff | P1 | T4.5, T3.7 | Classification unit tests; same-machine replay of `orders_ecommerce` yields `reproduced` or a documented `inconclusive` |
| T4.8 | Lineage drawer UI + replay page | P1 | T4.5 | "Why?" walks to source artifact |
| T4.9 | Full eval suite run + baseline in phase report | P0 | T4.2 | Metrics recorded |

**Phase 4 status (2026-10-13):** T4.1–T4.9 implemented ([PHASE_4_REPORT](reports/PHASE_4_REPORT.md)). Additionally: the re-investigation start endpoint (owner request; diff stays Post-MVP) and `GET /runs/{id}/verifications`. T4.7's acceptance met as "documented inconclusive" with one `reproduced` pair out of 14 ([analysis/replay_variance](../engineering/analysis/replay_variance/README.md)).

## Phase 5 — Production polish

| ID | Task | Pri | Deps | Acceptance criteria |
|---|---|---|---|---|
| T5.1 | GitHub OAuth + account linking for anonymous data | P0 | T1.5 | OAuth flow tests (mocked provider) |
| T5.2 | BYOK credentials API + settings UI | P0 | T1.3 | Keys never returned; delete wipes ciphertext |
| T5.3 | Rate limiting (token bucket) + concurrency limits | P0 | T2.11 | 429 tests |
| T5.4 | OTel tracing + metrics; LangSmith opt-in | P1 | T2.10 | Trace for one run visible locally |
| T5.5 | Dashboard, landing page, demo gallery (prerecorded + replays) | P0 | T4.6 | Labels for prerecorded data |
| T5.6 | Plan explorer polish (edge weights, diff, mobile) | P1 | T4.3 | — |
| T5.7 | CI: integration, security, evals, e2e, audits | P0 | — | All workflows green |
| T5.8 | Deployment (Vercel, container host, Neon, domains, secrets) | P0 | T5.1–T5.3 | Public URL; README updated |
| T5.9 | Security review vs SECURITY.md; fix findings | P0 | T5.8 | Checklist in phase report |
| T5.10 | Accessibility pass (axe, keyboard, reduced motion) | P1 | T5.5 | axe clean on core pages |
