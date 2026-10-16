# Feature Inventory

Tiers: **MVP** (Phases 1–4 + MVP-marked Phase 5) · **Post-MVP** (next after MVP, same architecture) · **Advanced** (needs new infra or significant research) · **Future** (ideas, not committed).
FR = functional requirement in [PRD.md](PRD.md). Phase = [ROADMAP.md](../planning/ROADMAP.md).

## Inputs & connections

| ID | Feature | Tier | Phase | FR | Depends on |
|---|---|---|---|---|---|
| F-01 | SQL editor (CodeMirror 6, PG dialect, param sets) | MVP | 1 | FR-1 | — |
| F-02 | JSON plan upload/paste | MVP | 1 | FR-2 | F-10 |
| F-03 | Schema DDL upload → schema snapshot | MVP | 1 | FR-3 | F-09 |
| F-04 | Connection registry + capability detection | MVP | 1 | FR-4 | F-60 |
| F-05 | Demo workloads (`orders_ecommerce`, `join_fanout`, `stale_stats`, `rewrite_trap`, `no_benefit`, `index_regression`) | MVP | 1 (gen), 3 (bench) | FR-5 | — |
| F-06 | Text-format plan parsing | Post-MVP | — | FR-2 | F-10 |
| F-07 | Import `pg_stat_statements` CSV snapshot (offline workload analysis) | Post-MVP | — | — | F-31 |

## Inspection & parsing

| ID | Feature | Tier | Phase | FR | Depends on |
|---|---|---|---|---|---|
| F-09 | SQL parse/validate/fingerprint (SQLGlot) | MVP | 1 | FR-6 | — |
| F-10 | Plan parser + derived metrics | MVP | 1 | FR-8 | — |
| F-11 | Inspection gateway (templated catalog queries, plain EXPLAIN) | MVP | 1 | FR-7 | F-60, F-61 |
| F-12 | Statistics redaction (no MCV/histogram values by default) | MVP | 1 | FR-7 | F-11 |
| F-13 | Plan diff (structural + metric) | MVP | 4 | FR-21 | F-10 |

## Agents & orchestration

| ID | Feature | Tier | Phase | Depends on |
|---|---|---|---|---|
| F-20 | LangGraph supervisor, typed state, budgets, termination | MVP | 2 | F-09, F-10 |
| F-21 | Query Analyzer agent | MVP | 2 | F-20 |
| F-22 | Index Strategist agent | MVP | 2 | F-20 |
| F-23 | Workload Investigator agent (capability-gated) | MVP | 2 | F-20, F-11 |
| F-24 | Optimization Engineer agent | MVP | 3 | F-20, F-40 |
| F-25 | Benchmark Auditor agent | MVP | 4 | F-42 |
| F-26 | Evidence store + citation validator | MVP | 2 | F-20 |
| F-27 | Postgres checkpointing + resume | MVP | 2 | F-20 |
| F-28 | Human approval gate (interrupt/resume) | MVP | 3 | F-27 |
| F-29 | Hypothetical-index pre-screen (HypoPG in sandbox) | Post-MVP | — | F-40 |
| F-30 | Natural-language Q&A over a finished investigation (grounded on evidence) | Post-MVP | — | F-26 |
| F-31 | Multi-query workload investigations (top-N from pg_stat_statements) | Advanced | — | F-23 |

## Benchmarking & verification

| ID | Feature | Tier | Phase | Depends on |
|---|---|---|---|---|
| F-40 | Sandbox provisioner (Docker PG, template DB clones) | MVP | 3 | F-05 |
| F-41 | Benchmark engine (warm-up, interleaving, timeouts, cancellation) | MVP | 3 | F-40 |
| F-42 | Statistics (median, p95, CV, bootstrap CI) | MVP | 3 | F-41 |
| F-43 | Correctness fingerprints (ordered/multiset) | MVP | 3 | F-41 |
| F-44 | Optimization tournament + verdict rules | MVP | 3 (rank), 4 (audit) | F-42, F-43 |
| F-45 | Index size/build-time capture | MVP | 3 | F-41 |
| F-46 | Parameter-sensitivity runs (multiple param sets) | MVP | 3 | F-41 |
| F-47 | Write-overhead micro-benchmark (insert/update throughput, rolled back) | Post-MVP | — | F-41 |
| F-48 | Cold-cache runs (container restart + OS cache drop, local only) | Advanced | — | F-40 |
| F-49 | Concurrent-load benchmarks (pgbench-style mixed workload) | Advanced | — | F-41 |
| F-50 | User-data sandbox via `pg_dump` subset + anonymization | Future | — | F-40 |

## Security

| ID | Feature | Tier | Phase |
|---|---|---|---|
| F-60 | SSRF guard (resolve, block ranges, pin hostaddr) | MVP | 1 |
| F-61 | Session hardening (read-only txn, timeouts) | MVP | 1 |
| F-62 | Prompt-injection fencing + identifier sanitization | MVP | 2 |
| F-63 | Upload validation (size, type, JSON schema) | MVP | 1 |
| F-64 | BYOK encryption at rest (AES-256-GCM) | MVP | 5 |
| F-65 | Rate limiting (per session/IP, Postgres-backed token bucket) | MVP | 5 |
| F-66 | Network-isolated sandbox (no egress) | MVP | 3 |

## Reporting, replay, history

| ID | Feature | Tier | Phase |
|---|---|---|---|
| F-70 | Report generation (MD + JSON) | MVP | 4 |
| F-71 | Artifact store (SHA-256) + evidence lineage | MVP | 2 (store), 4 (lineage UI) |
| F-72 | Report replay | MVP | 4 |
| F-73 | Experiment replay | MVP | 4 |
| F-74 | AI re-investigation + conclusion diff | Post-MVP | — |
| F-75 | Investigation history, search, soft delete | MVP | 2 |
| F-76 | PDF export | Future | — |
| F-77 | Shareable read-only report links | Post-MVP | — |

## UI

| ID | Feature | Tier | Phase |
|---|---|---|---|
| F-80 | Investigation workspace | MVP | 1 (shell), 2 (timeline), 3–4 (results) |
| F-81 | Plan explorer (React Flow + tree-table fallback) | MVP | 1 (tree), 5 (graph polish) |
| F-82 | Agent timeline (SSE) | MVP | 2 |
| F-83 | Tournament + benchmark charts | MVP | 3 |
| F-84 | Landing page + public demo gallery (prerecorded) | MVP | 5 |
| F-85 | Dark/light mode | MVP | 1 |
| F-86 | Dashboard (recent runs, outcomes) | MVP | 5 |

## Platform

| ID | Feature | Tier | Phase |
|---|---|---|---|
| F-90 | Local single-user mode + anonymous demo sessions | MVP | 1 |
| F-91 | GitHub and Google OAuth accounts | MVP | 5 |
| F-92 | OTel tracing + optional LangSmith | MVP | 5 |
| F-93 | CI (lint, type, unit, integration, security, smoke evals) | MVP | 1 (basic), 5 (full) |
| F-94 | Teams / RBAC | Future | — |
| F-95 | Scheduled regression monitoring | Future | — |

## Dependency notes

- Benchmarking (F-40+) depends on demo workloads (F-05) because MVP never copies user data.
- The Auditor (F-25) is useful only after the statistics (F-42) and correctness (F-43) layers exist — deterministic rules come first, the LLM narrative second.
- Report replay (F-72) requires that *every* rendered value comes from persisted events/artifacts from Phase 2 onward; retrofitting is expensive, which is why the artifact store lands in Phase 2.
