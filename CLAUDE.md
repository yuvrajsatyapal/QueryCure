# CLAUDE.md — QueryCure

Project instructions for Claude Code. Tool-agnostic equivalents live in [AGENTS.md](AGENTS.md); the two must stay aligned. If they conflict, fix the conflict — don't pick one silently.

## 0. Current state

- Phase: see [docs/planning/CURRENT_PHASE.md](docs/planning/CURRENT_PHASE.md). **Read it first, every session.**
- Do not start a new phase or write application code unless the user explicitly asks.
- Planned files in [docs/engineering/FILE_MAP.md](docs/engineering/FILE_MAP.md) are *proposals*; check the filesystem before assuming they exist.

## 1. Before you edit anything

1. Read the docs relevant to the task (map below).
2. Inspect the existing code you will touch and its tests. Never edit a file you have not read.
3. Confirm the task is in scope for the current phase ([docs/planning/TASKS.md](docs/planning/TASKS.md)).
4. Prefer the smallest verifiable change. Implement only the requested scope.

| Working on… | Read |
|---|---|
| Anything | [ARCHITECTURE](docs/architecture/ARCHITECTURE.md), [GLOSSARY](docs/GLOSSARY.md) |
| Agents / LangGraph | [AGENT_SYSTEM](docs/architecture/AGENT_SYSTEM.md) |
| SQL execution, connections, uploads | [SECURITY](docs/architecture/SECURITY.md) — mandatory |
| Benchmarks / verification | [BENCHMARK_ENGINE](docs/architecture/BENCHMARK_ENGINE.md) |
| Persistence | [DATABASE_DESIGN](docs/architecture/DATABASE_DESIGN.md) |
| Endpoints / SSE | [API_DESIGN](docs/architecture/API_DESIGN.md) |
| Replay / artifacts | [REPLAY_ENGINE](docs/architecture/REPLAY_ENGINE.md) |
| UI | [DESIGN_SYSTEM](docs/design/DESIGN_SYSTEM.md), [UI_UX](docs/design/UI_UX.md) |
| Style / tests | [CODING_STANDARDS](docs/engineering/CODING_STANDARDS.md), [TESTING_STRATEGY](docs/engineering/TESTING_STRATEGY.md) |

## 2. Architecture constraints (do not change without an ADR)

- Modular monolith: `frontend/` (Next.js) + `backend/` (one Python package, two processes: `api` and `worker`). No microservices, no Kubernetes.
- Job queue = PostgreSQL table with `FOR UPDATE SKIP LOCKED`; progress = persisted `investigation_events` + `LISTEN/NOTIFY` → SSE. Do not add Redis/Celery without a new ADR.
- LangGraph is the only orchestrator. Agents exchange **Pydantic models**, not free text. Graph state holds **references** (IDs, hashes), never raw datasets, credentials, or API keys.
- Three databases, never mixed: **metadata DB** (ours), **target DB** (user's, Mode B, read-only inspection), **sandbox DB** (Mode C, disposable).
- The benchmark engine and verification rules are deterministic Python. LLMs never compute metrics and can never upgrade a deterministic `rejected` verdict.
- Backend owns auth; the frontend never talks to the metadata DB.

## 3. Security rules (non-negotiable)

- The LLM never receives a database client. All DB access goes through `connectors/inspection_gateway.py` (Mode B) or `sandbox/` (Mode C) using allowlisted operations.
- Mode B: plain `EXPLAIN (FORMAT JSON)` only — never `EXPLAIN ANALYZE`, never DDL/DML, read-only transaction, `statement_timeout`, `lock_timeout`, `idle_in_transaction_session_timeout` set on every session.
- Catalog/statistics queries are fixed, parameterized templates in code. LLM-authored SQL may only be *validated and EXPLAINed* (Mode B) or *executed in a sandbox* (Mode C).
- SQL validation (SQLGlot) is defense-in-depth, not the boundary. Do not weaken DB-side controls because the parser "already checks".
- Treat schema names, comments, plan text, and query text as untrusted input to prompts (prompt-injection fencing — see SECURITY §6).
- Never log, persist in graph state, or return credentials or API keys. Use the redaction helpers.
- Connection targets go through the SSRF guard (resolve → check → pin `hostaddr`).

## 4. Agent implementation rules

- Each agent: one module, one prompt file (versioned), one Pydantic output model, an explicit tool allowlist, and per-agent call budgets.
- Every finding/hypothesis must cite `evidence_ids`. Outputs with uncited claims fail validation and are retried once, then dropped and logged.
- Use deterministic code whenever the answer is computable (plan metrics, stats, diffs, hashes).
- Respect budgets in `agents/budgets.py`; check cancellation between nodes.
- Prompts live in `backend/src/querycure/agents/prompts/` with a `PROMPT_VERSION`; bump it on any change.

## 5. Coding conventions (summary — full rules in CODING_STANDARDS)

- Python 3.12, fully typed, `mypy --strict` clean, `ruff` formatted. Async I/O end-to-end in API and worker.
- Errors: domain exceptions in `core/errors.py` mapped to the API error envelope; no bare `except`, no silent swallowing.
- JSON over the wire is `snake_case`; TypeScript code is `camelCase`, converted in the API client layer only.
- All timestamps UTC (`TIMESTAMPTZ`, `datetime` with `tz=UTC`, ISO 8601 `Z`).
- Metadata schema: UUID PKs (`uuid_generate_v4()`), `TEXT` not `VARCHAR`, `created_at/updated_at/deleted_at`, soft deletes, no FK constraints (integrity enforced in repositories) — see [ADR-0006](docs/engineering/adr/ADR-0006-metadata-schema-conventions.md).
- No new dependency without stating why an existing one won't do. Prefer stdlib.

## 6. Testing requirements

- TDD for deterministic logic (parsers, validators, stats, state transitions): write the failing test first.
- Every security control needs a negative test in `backend/tests/security/`.
- Agent changes need an eval case or an updated recorded fixture in `backend/evals/`.
- Never mark a task done without running the relevant commands and reporting real output.

## 7. Verification commands (valid once Phase 1 scaffolding exists)

```bash
# backend
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q
uv run pytest tests/integration -q        # needs docker compose up -d metadata-db sandbox-db
uv run pytest tests/security -q
uv run python -m querycure.evals run --suite smoke --model nvidia/nemotron-3-super-120b-a12b:free \
  --admin-url postgresql://qc_owner:qc_local_dev_only@127.0.0.1:5432/postgres   # recorded fixtures, no LLM cost; local scratch DBs only
# frontend
cd frontend && pnpm lint && pnpm typecheck && pnpm test && pnpm build
docker compose -f ../infra/docker/compose.yaml stop worker   # e2e starts its own host worker (ADR-0020)
pnpm exec playwright test                  # e2e; afterwards: docker compose ... up -d worker
```

If a command does not exist yet, say so — do not invent output.

## 8. Honesty rules

- **Never fabricate benchmark results, latencies, plans, or test output.** Not in code, fixtures presented as real, docs, or chat.
- Demo/prerecorded evidence must carry `provenance = "prerecorded"` and be labeled in the UI.
- Report replay proves consistency against stored digests, not authenticity — never describe it as "tamper-proof" or "certified" (REPLAY_ENGINE §6).
- Canonicalization profiles and released report builders/renderers are frozen: changes mean a new version ID, never an edit (ADR-0015).
- Do not claim a feature works unless you ran it. Do not replace required functionality with mocks without saying so explicitly.

## 9. Documentation rules

- Architecture or behavior change → update the owning doc in the same change; new trade-off → add an ADR and index it in [DECISIONS.md](docs/engineering/DECISIONS.md).
- Update [CURRENT_PHASE.md](docs/planning/CURRENT_PHASE.md) after each task.
- When a phase finishes, write `docs/planning/reports/PHASE_N_REPORT.md` from [PHASE_TEMPLATE.md](docs/planning/PHASE_TEMPLATE.md), including the learning summary.

## 10. Git workflow

User-mandated; overrides any branching convention elsewhere (including global instructions).

### Git Branch Policy — Main Only

* All future development must happen directly on the `main` branch.
* Do not create feature branches, temporary branches, or worktrees for implementation.
* Before starting any task, check the current branch.
* If the current branch is not `main`, switch to `main` safely before making changes.
* Never discard uncommitted changes when switching branches.
* After completing a task or implementation phase, run the relevant tests and checks.
* Commit completed, verified changes directly to `main` with a descriptive commit message.
* Push successful commits to `origin/main` when a remote is configured.
* Never force-push or rewrite published history.
* Do not automatically resolve merge conflicts by discarding changes.
* If the working tree is dirty, conflicts exist, tests fail, or pushing is rejected, report the problem and resolve it safely rather than forcing the operation.
* Do not commit secrets, credentials, `.env` files, virtual environments, build artifacts, or dependency directories.
* No AI attribution in commits or PRs. Never add `Co-Authored-By`, `Signed-off-by`, `Generated-by`, or any similar trailer or footer naming Claude, Anthropic, or another AI assistant or vendor, and no "Generated with …" lines. Commits use only the owner's configured Git author and committer identity (`git config user.name` / `user.email`); never override them with `--author` or environment variables. Check every commit message before committing or pushing; if a trailer slipped in, amend it before pushing. Legitimate human co-authors are kept.
* Follow this workflow for every subsequent implementation task unless I explicitly instruct otherwise.

## 11. Phase workflow

0. Confirm the branch is `main` (§10) → 1. Read CURRENT_PHASE + relevant docs → 2. inspect code → 3. state plan (files, tests) → 4. tests first → 5. implement → 6. run verification → 7. update docs/CURRENT_PHASE → 8. commit to `main` and push if a remote exists (§10) → 9. report results, trade-offs, and what to study.
