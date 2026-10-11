# AGENTS.md — QueryDoctor AI

Instructions for any coding agent (Codex, Claude Code, Cursor, etc.). [CLAUDE.md](CLAUDE.md) is the detailed version; this file is the tool-agnostic contract. Keep them aligned — when you change a rule here, change it there.

## Start of every task

1. Read [docs/planning/CURRENT_PHASE.md](docs/planning/CURRENT_PHASE.md). Work only on the current phase unless told otherwise.
2. Read the docs for the area you touch (table in CLAUDE.md §1). [SECURITY.md](docs/architecture/SECURITY.md) is mandatory for anything that executes SQL, opens connections, or handles uploads/keys.
3. Inspect existing code and tests before editing. Files listed in [FILE_MAP.md](docs/engineering/FILE_MAP.md) may not exist yet.
4. Implement only the requested scope, in small verifiable steps.

## Hard constraints

| Area | Rule |
|---|---|
| Structure | `frontend/` (Next.js) + `backend/` (Python package, `api` + `worker` processes). No new services. |
| Orchestration | LangGraph only. Typed state with references, not raw data. Pydantic messages between agents. |
| Jobs/streaming | Postgres job table + `investigation_events` + SSE. No Redis/Celery without an ADR. |
| Databases | Metadata ≠ target ≠ sandbox. Never cross them. |
| SQL safety | No LLM-held DB clients. Mode B = plain `EXPLAIN` + templated catalog queries, read-only, timeouts. AI DDL runs only in sandboxes. |
| Verification | Benchmark math and verdict rules are deterministic. LLM can downgrade a verdict, never upgrade it. |
| Secrets | Never log/persist/return credentials or API keys; never put them in graph state. |
| Replay integrity | Canonicalization profiles and released report builders are frozen (new version, never edits); runs are sealed by atomic `finalize_run`; never call replay "tamper-proof" ([ADR-0015](docs/engineering/adr/ADR-0015-canonicalization-finalization-integrity.md)). |
| Data conventions | snake_case JSON, camelCase TS, UTC everywhere, UUID PKs, TEXT, soft delete, no FK constraints ([ADR-0006](docs/engineering/adr/ADR-0006-metadata-schema-conventions.md)). |
| Dependencies | Justify every new one; prefer stdlib and existing deps. |

## Definition of done

- Tests written first for deterministic logic; security controls have negative tests; agent changes have eval fixtures.
- Verification commands (CLAUDE.md §7) run, and **actual** output reported. If a command could not run, say so.
- Owning docs updated; ADR added for new trade-offs; CURRENT_PHASE.md updated.
- No fabricated benchmark numbers or claims of untested functionality. No silent mocks.
- At phase completion: report in `docs/planning/reports/` using [PHASE_TEMPLATE.md](docs/planning/PHASE_TEMPLATE.md), with a learning summary.
