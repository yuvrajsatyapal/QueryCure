# File Map

**Legend:** ✅ exists · 🟡 partially exists · ⏳ planned. Unmarked rows inside `backend/` and `frontend/` trees are planned unless the filesystem says otherwise — check before assuming. Update this file when directories are created; mark rows ✅ when real.

## 1. Top level

```
querycure/                      (repo root; product name QueryCure)
├── README.md                   ✅ product overview, status, doc index
├── CLAUDE.md                   ✅ Claude Code instructions
├── AGENTS.md                   ✅ tool-agnostic agent instructions
├── docs/                       ✅ all documentation (this tree)
│   ├── diagrams/               ✅ 3 designed HTML diagrams (system architecture, trust boundaries, agent graph); Mermaid in the .md docs is authoritative
│   └── planning/reports/       ⏳ phase completion reports (created at end of each phase)
├── backend/                    🟡 Python package `querycure`: api app factory + health route exist; worker not yet
├── frontend/                   🟡 Next.js 16 app: scaffold + placeholder page exist
├── infra/
│   └── docker/                 🟡 compose.yaml exists; sandbox postgresql.conf and init SQL pending
└── .github/workflows/          ⏳ CI/CD
```

## 2. Backend (`backend/`)

```
backend/
├── pyproject.toml              uv-managed; ruff, mypy, pytest config
├── uv.lock
├── Dockerfile
├── alembic.ini
├── migrations/                 Alembic versions (metadata DB only)
├── src/querycure/
│   ├── core/                   config (pydantic-settings), logging (structlog), errors, ids, clock, retry, redaction, crypto (AES-GCM), telemetry (OTel)
│   ├── domain/                 Pydantic domain models & enums shared by all layers (Evidence, Finding, Hypothesis, Candidate, ExperimentConfig, RunStatus…)
│   ├── db/                     SQLAlchemy async engine/session, table definitions, repositories (one per aggregate), transition_run()
│   ├── api/
│   │   ├── main.py             app factory, middleware (request id, CSRF, CORS, errors)
│   │   ├── deps.py             session/user resolution, repositories
│   │   ├── schemas/            request/response models (no secrets — tested)
│   │   ├── routers/            session, connections, inspect, workloads, investigations, runs, approvals, experiments, reports, replay, settings, health
│   │   └── sse.py              event replay + LISTEN fan-out
│   ├── sql/                    parser.py (SQLGlot), validator.py (allowlist/denylist), fingerprint.py, ddl_allowlist.py
│   ├── plans/                  parser.py (PG JSON → PlanTree), metrics.py, diff.py, summarize.py (deterministic text for prompts)
│   ├── connectors/             ssrf_guard.py, session.py (hardened psycopg sessions), inspection_gateway.py, catalog_queries/ (*.sql templates), capabilities.py
│   ├── sandbox/                ✅ provisioner.py (templates, clones, advisory-lock leases, orphan cleanup); user_sandbox_backend.py planned (D4)
│   ├── benchmark/              ✅ engine.py, executor.py (timing), schedule.py, correctness.py, stats.py, rules.py, tournament.py, fixtures.py (prerecorded)
│   ├── workloads/              registry.py, <name>/generator.py, <name>/schema.sql, <name>/queries.yaml
│   ├── llm/                    providers.py (Gemini, OpenRouter via LangChain), credentials.py (BYOK decrypt), structured.py (with_structured_output + repair), rate_limit.py
│   ├── agents/
│   │   ├── graph.py            StateGraph assembly, routing functions
│   │   ├── state.py            InvestigationState + reducers
│   │   ├── budgets.py          RunBudget, budget_guard
│   │   ├── nodes/              intake.py, collect_context.py, supervisor.py, query_analyzer.py, index_strategist.py, workload_investigator.py, optimization_engineer.py, approval_gate.py, run_experiment.py, benchmark_auditor.py, write_report.py
│   │   ├── tools/              typed tool functions per agent allowlist
│   │   ├── prompts/            one module per agent with PROMPT_VERSION
│   │   ├── fencing.py          untrusted-data fencing for prompts
│   │   └── citations.py        evidence citation validator
│   ├── evidence/               store.py (deterministic ids), lineage.py
│   ├── replay/                 canonical/ (one frozen module per profile), digest.py, artifact_store.py, finalize.py (finalize_run), manifest.py, report_replay.py, experiment_replay.py, compare.py (drift CI + environment diff)
│   ├── reports/                builders/v{N}.py (records → report JSON), renderers/md_v{N}.py (JSON → Markdown); released versions frozen
│   ├── events/                 emitter.py (insert + NOTIFY in txn), types.py
│   ├── jobs/                   queue.py (claim/lease/heartbeat), handlers.py
│   └── worker/__main__.py      worker entrypoint (separate or embedded)
├── tests/
│   ├── unit/                   mirrors src modules
│   ├── integration/            real Postgres (compose/testcontainers)
│   ├── security/               negative tests per control
│   └── conftest.py
└── evals/
    ├── cases/                  YAML eval cases (workload, query, expected labels, forbidden claims)
    ├── recordings/             recorded LLM responses for deterministic CI
    └── runner.py               `python -m querycure.evals`
```

### Dependency direction (enforced by `import-linter` contract)

```
api ──► db, domain, jobs, events, replay(read), reports(read), sql, plans, connectors(test/explain only)
worker ──► agents ──► tools ──► connectors, sandbox, benchmark, evidence, plans, sql
benchmark ──► sandbox, domain           (never agents, never llm)
connectors, sandbox ──► core, domain    (never agents, never llm)
domain ──► (nothing but pydantic/stdlib)
```

Rules: `benchmark` must not import `llm` or `agents` (verdict authority stays deterministic); `api` must not import `agents` (no LLM in request path).

## 3. Frontend (`frontend/`)

```
frontend/
├── package.json, pnpm-lock.yaml, next.config.ts, tsconfig.json (strict), tailwind.config.ts, components.json (shadcn)
├── src/
│   ├── app/                    App Router routes (see UI_UX §1); route-level loading.tsx / error.tsx
│   ├── components/
│   │   ├── ui/                 shadcn primitives (generated, lightly restyled)
│   │   ├── claims/             ClaimBadge, EvidenceChip, VerdictPill, MetricCell
│   │   ├── editor/             SqlEditor (CodeMirror 6)
│   │   ├── plan/               PlanGraph (React Flow), PlanTreeTable, PlanNode, PlanDiff
│   │   ├── timeline/           AgentTimeline, TimelineItem
│   │   ├── tournament/         TournamentTable, SpeedupBar, LatencyChart
│   │   └── layout/             AppShell, ResizableWorkspace
│   ├── lib/
│   │   ├── api/                client.ts (fetch wrapper, CSRF, error envelope), case.ts (snake↔camel), generated/ (openapi-typescript output), per-resource modules
│   │   ├── sse.ts              EventSource wrapper with Last-Event-ID + TanStack Query cache updates
│   │   └── format.ts           numbers, durations, UTC→local display
│   ├── stores/                 Zustand: workspace UI state only
│   └── styles/tokens.css       design tokens
└── tests/
    ├── unit/                   Vitest + Testing Library
    └── e2e/                    Playwright
```

## 4. Where new features belong

| New thing | Location |
|---|---|
| New catalog/statistics query | `connectors/catalog_queries/*.sql` + typed wrapper in `inspection_gateway.py` + security test |
| New agent tool | `agents/tools/` + add to that agent's allowlist + eval case |
| New candidate kind | `domain` enum + `sql/ddl_allowlist.py` + `benchmark` handling + verdict tests |
| New verdict gate | `benchmark/rules.py` + unit tests + BENCHMARK_ENGINE §7 update |
| New demo workload | `workloads/<name>/` + eval case + BENCHMARK_ENGINE §11 row |
| New SSE event | `events/types.py` + API_DESIGN §3 table + frontend `sse.ts` handler |
| New page | `frontend/src/app/...` + UI_UX section |
