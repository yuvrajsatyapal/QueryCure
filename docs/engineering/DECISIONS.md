# Architecture Decisions

Index of decisions. Full records (context, alternatives, decision, rationale, trade-offs, consequences) live in [adr/](adr/). To change a decision: add a new ADR that supersedes the old one; don't edit accepted ADRs except to mark them superseded.

| ADR | Decision | Key trade-off |
|---|---|---|
| [0001](adr/ADR-0001-modular-monolith.md) | Modular monolith: Next.js + one Python package with `api` and `worker` processes | Simplicity vs independent scaling |
| [0002](adr/ADR-0002-langgraph-supervisor.md) | LangGraph supervisor graph; deterministic nodes + bounded specialist agents | Upfront design vs opaque agent loops |
| [0003](adr/ADR-0003-execution-modes.md) | Modes A/B/C; no AI DDL on user DBs; Mode B off on public demo | Safety vs realism of verification data |
| [0004](adr/ADR-0004-postgres-job-queue.md) | Postgres `SKIP LOCKED` job queue, no Redis/Celery in MVP | Zero infra vs throughput ceiling |
| [0005](adr/ADR-0005-sse-event-log.md) | SSE backed by persisted, sequenced events | Resumability vs a DB write per event |
| [0006](adr/ADR-0006-metadata-schema-conventions.md) | UUID/TEXT/TIMESTAMPTZ/soft delete/no FK constraints | Convention consistency vs DB-enforced integrity |
| [0007](adr/ADR-0007-sandbox-template-clones.md) | Sandbox = template DB clones on dedicated Docker PG | Fair comparison vs shared buffer cache |
| [0008](adr/ADR-0008-benchmark-statistics.md) | Ratio of medians + seeded bootstrap CI; effect/regression/noise gates | Robustness vs small-n accuracy |
| [0009](adr/ADR-0009-deterministic-verification-authority.md) | Rules own verdicts; LLM auditor may only downgrade | Reliability vs some over-caution |
| [0010](adr/ADR-0010-content-addressed-artifacts.md) | SHA-256 content-addressed artifacts in metadata DB | Uniform integrity vs DB growth |
| [0011](adr/ADR-0011-codemirror-editor.md) | CodeMirror 6 over Monaco | Bundle/mobile vs IDE features |
| [0012](adr/ADR-0012-byok-credential-storage.md) | AES-256-GCM secrets with env master key | Async usability vs master-key blast radius |
| [0013](adr/ADR-0013-auth-strategy.md) | Backend-owned cookie sessions; OAuth in Phase 5 | One authority vs DIY CSRF |
| [0014](adr/ADR-0014-python-tooling.md) | uv, ruff, mypy --strict, pytest, import-linter | Rigor vs early velocity |
| [0015](adr/ADR-0015-canonicalization-finalization-integrity.md) | Frozen RFC 8785-based canonicalization profiles, atomic finalization, integrity ≠ authenticity, equivalence-margin replay comparison (amends 0010) | Cross-version stability vs owning canonicalization code; no signing yet |

## Smaller decisions (not worth a full ADR)

| Decision | Choice | Why |
|---|---|---|
| Python version | 3.12 | Mature typing (`type` statements, `TaskGroup`), broad library support |
| PostgreSQL version (sandbox/metadata local) | 17 | Current stable; plans parsed for 13–17 |
| Plan graph layout | dagre via `@dagrejs/dagre` | Small, deterministic tree layout; ELK is heavier |
| API types in frontend | `openapi-typescript` generation | No hand-written drift |
| Fonts | IBM Plex Sans + IBM Plex Mono | Technical, open-source, distinctive vs default UI fonts |
| Prose LLM sections | Stored, never regenerated on replay | Replay determinism |
| Global Kotlin/Micronaut API rules | Not applied (Python project; REST requested) | Database, naming, timezone rules are applied |
| No numpy/scipy in backend | stdlib statistics + random | Small dependency surface; sufficient for bootstrap |
| Hypothetical indexes (HypoPG) | Post-MVP pre-screen only, never a verdict source | Estimates are not measurements |

## Deferred decisions

Tracked with owners and deadlines in [CURRENT_PHASE.md § Open decisions](../planning/CURRENT_PHASE.md#open-decisions).
