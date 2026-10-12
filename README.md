# QueryCure

> Autonomous, multi-agent investigation and *verified* optimization of PostgreSQL query performance.

**Project status: Phase 2 (multi-agent intelligence) implemented.** What runs today: SQL and plan parsing, a plan explorer, restricted live `EXPLAIN`, and **multi-agent investigations** (LangGraph supervisor + Query Analyzer, Index Strategist, Workload Investigator) that produce cited, **unverified** hypotheses with a live timeline, using **free OpenRouter models only** ([ADR-0016](docs/engineering/adr/ADR-0016-free-openrouter-models-only.md)). **No benchmarks, verified recommendations, or replayable reports yet**: those arrive in Phases 3–4. See [docs/planning/CURRENT_PHASE.md](docs/planning/CURRENT_PHASE.md) for live status.

---

## The problem

When a PostgreSQL query is slow, engineers typically:

1. Run `EXPLAIN`, squint at a plan tree, guess at a cause.
2. Add an index they *think* will help.
3. Run the query once, see it got faster, and ship it.

Step 3 is where things go wrong: a single timing is noise, the index may slow down writes, a "faster" rewrite may silently return different rows, and the warm cache may explain most of the improvement. Generic SQL chatbots make this worse — they produce confident advice with no evidence.

## What QueryCure does

QueryCure behaves like a small team of database performance engineers:

| Step | What happens | Who does it |
|---|---|---|
| Inspect | Parse SQL, collect schema, indexes, statistics, `EXPLAIN` plan | Deterministic tools |
| Investigate | Analyze plan nodes, estimates vs actuals, workload signals | Query Analyzer, Workload Investigator (LLM agents with restricted tools) |
| Hypothesize | Ranked root-cause hypotheses, each citing evidence | Supervisor + specialist agents |
| Propose | Index / rewrite / statistics candidates with risks and costs | Index Strategist, Optimization Engineer |
| Benchmark | Controlled, repeated, interleaved runs in an **isolated sandbox** | Deterministic Benchmark Engine |
| Verify | Result-set correctness, statistical significance, regressions | Benchmark Auditor (deterministic rules first, LLM second) |
| Report | Evidence-backed report with confidence, trade-offs, rollback | Report generator |

**Core principle:** a recommendation is not a *verified improvement* until it has been benchmarked against a representative workload and passed correctness checks. QueryCure is allowed — and expected — to conclude "inconclusive" or "no candidate is sufficiently supported."

Every claim in the UI is labeled as one of: **Observed** · **Hypothesis** · **Recommendation** · **Verified** · **Rejected** · **Inconclusive**.

## Key features (planned)

- Three execution modes with explicit trust boundaries:
  **A — Offline analysis** (uploaded SQL/plans/schema), **B — Restricted live inspection** (plain `EXPLAIN` + catalog reads only), **C — Isolated benchmarking** (sandbox clones; AI-generated DDL never touches a user's database).
- LangGraph supervisor coordinating five specialist agents with typed state, checkpointing, parallel fan-out, human approval, and bounded budgets.
- **Optimization Tournament** — candidates compete under identical, interleaved conditions; losers are rejected with reasons.
- Interactive execution-plan explorer (React Flow) and before/after plan diff.
- Reproducibility engine: SHA-256 content-addressed artifacts, report replay (no LLM calls), experiment replay, and AI re-investigation diffs.
- Live investigation timeline over Server-Sent Events.
- Bring-your-own-key LLM access (Gemini, OpenRouter).

## Architecture at a glance

```mermaid
flowchart LR
  U[Browser] --> W[Next.js web app]
  W -->|REST + SSE| API[FastAPI API]
  API --> MDB[(Metadata Postgres)]
  API -->|enqueue| Q[(Job queue table)]
  WK[Worker: LangGraph + Benchmark Engine] --> Q
  WK --> MDB
  WK -->|BYOK| LLM[LLM providers]
  WK -->|Mode B: inspection gateway| TDB[(User target DB)]
  WK -->|Mode C| SBX[(Sandbox Postgres)]
```

Full details: [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md).

## Technology stack (planned)

| Layer | Choice |
|---|---|
| Frontend | Next.js (App Router), TypeScript, Tailwind CSS, shadcn/ui, TanStack Query, Zustand (UI state only), React Flow, Recharts, CodeMirror 6 |
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async) + Alembic, psycopg 3, SQLGlot |
| AI | LangGraph, LangChain (model integration + structured output), Gemini, OpenRouter, BYOK |
| Data | PostgreSQL for metadata (Neon in the public demo), Docker PostgreSQL for sandboxes |
| Jobs | PostgreSQL-backed job queue (`SKIP LOCKED`) + `LISTEN/NOTIFY` — no Redis in MVP ([ADR-0004](docs/engineering/adr/ADR-0004-postgres-job-queue.md)) |
| Observability | structlog JSON logs, OpenTelemetry traces, optional LangSmith |
| Testing | pytest, Vitest, Playwright, recorded-LLM evaluation fixtures |
| Delivery | Docker Compose (local), Vercel (web), single-container Python host (API + worker), GitHub Actions |

Rationale for each choice: [docs/engineering/DECISIONS.md](docs/engineering/DECISIONS.md).

## Run locally

Prerequisites: Docker (with Compose v2), [uv](https://docs.astral.sh/uv/), Node.js 22, and pnpm 10 (`corepack enable` provides the pinned version). uv installs Python 3.12 if needed.

**1. Databases.** This starts the metadata DB on `127.0.0.1:5432` and the sandbox DB on an internal network. Both use dev-only passwords; the first start also creates the restricted `qc_app` role.

```bash
docker compose -f infra/docker/compose.yaml up -d --wait
```

**2. Backend config.** Copy the example env file, then set `QC_MASTER_KEY`, which encrypts saved connection passwords.

```bash
cp backend/.env.example backend/.env
```

```bash
python3 -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
```

Paste the output after `QC_MASTER_KEY=` in `backend/.env`.

**3. Migrations and API.** The API runs as `qc_app`; migrations run as the owner role.

```bash
cd backend && uv sync && uv run alembic upgrade head
```

```bash
cd backend && uv run uvicorn querycure.api.main:app --port 8000
```

`curl http://localhost:8000/api/v1/readyz` should return `{"status":"ok","database":"ok","migrations":"current"}`.

**4. Web app** (in a second terminal):

```bash
cd frontend && pnpm install && pnpm dev
```

Open <http://localhost:3000/app>. A local session is created automatically.

**5. LLM key and worker (for investigations).** QueryCure uses free OpenRouter models only; paid models are refused. Put your key after `OPENROUTER_API_KEY=` in `backend/.env` (the pinned model is in `.env.example`), then run the worker in a third terminal:

```bash
cd backend && uv run python -m querycure.worker
```

Without a key, investigations stop with a configuration error. To try the UI with no model at all, start the API and worker with `LLM_PROVIDER=stub` (canned, labelled output for testing; local profile only).

**6. Inspect a plan offline, then investigate.** Go to **New investigation**, paste the output of `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) …`, and choose **Analyze plan**. Real example plans are in `backend/tests/fixtures/plans/pg17_*.json`. Then choose **New investigation**, give it a title and start it: the timeline streams live, and findings cite evidence you can click through to the plan node. Past runs are under **History**. Free models are slow (a run takes a few minutes) and limited to about 50 requests per day.

**7. Optional: live EXPLAIN against a demo database.** Load the `orders_ecommerce` workload (100k orders at `sf=0.1`) into its own database, then create a restricted role for QueryCure to connect as:

```bash
docker compose -f infra/docker/compose.yaml exec metadata-db psql -U qc_owner -d querycure -c "CREATE DATABASE qc_demo_orders"
```

```bash
cd backend && uv run python -m querycure.workloads postgresql://qc_owner:qc_local_dev_only@127.0.0.1:5432/qc_demo_orders 'orders_ecommerce@v1:sf=0.1:seed=42'
```

```bash
docker compose -f infra/docker/compose.yaml exec metadata-db psql -U qc_owner -d qc_demo_orders -c "CREATE ROLE qc_demo_inspector LOGIN PASSWORD 'demo_inspector_local_only'; GRANT CONNECT ON DATABASE qc_demo_orders TO qc_demo_inspector; GRANT USAGE ON SCHEMA public TO qc_demo_inspector; GRANT SELECT ON ALL TABLES IN SCHEMA public TO qc_demo_inspector; GRANT pg_read_all_stats TO qc_demo_inspector;"
```

In **Connections**, add host `127.0.0.1`, port `5432`, database `qc_demo_orders`, user `qc_demo_inspector`, and password `demo_inspector_local_only`. Set **TLS** to `disable (local only)`, because the compose container has no TLS and the default `verify-full` will fail to connect. Then choose **Test**. The workspace's **Live EXPLAIN** tab can now plan queries such as `SELECT * FROM orders WHERE customer_id = 1024 ORDER BY created_at DESC LIMIT 20`. It runs plain EXPLAIN only, so nothing is executed. Superuser connections are refused.

The demo database shares the local metadata server only for convenience. Private and loopback targets are allowed only because `ALLOW_PRIVATE_TARGETS=true` in the local profile.

**Checks:** see the verification commands in [CLAUDE.md §7](CLAUDE.md#7-verification-commands-valid-once-phase-1-scaffolding-exists). Integration tests need the compose databases running.

## Development phases

| Phase | Theme | Status |
|---|---|---|
| 0 | Documentation & architecture | Done |
| 1 | Foundation: repo, API, metadata DB, SQL/plan parsing, demo workloads, editor | Done ([report](docs/planning/reports/PHASE_1_REPORT.md)) |
| 2 | Multi-agent intelligence: LangGraph supervisor, analyzer agents, streaming | Implemented; exit partially met ([report](docs/planning/reports/PHASE_2_REPORT.md)) |
| 3 | Optimization & benchmarking: sandbox, benchmark engine, tournament | Planned |
| 4 | Verification & replay: auditor, lineage, replay, regression detection | Planned |
| 5 | Production polish: auth, BYOK, observability, evals, hardening, deploy | Planned |

See [docs/planning/ROADMAP.md](docs/planning/ROADMAP.md).

## Documentation index

**Agent/contributor instructions:** [CLAUDE.md](CLAUDE.md) · [AGENTS.md](AGENTS.md) · [Glossary](docs/GLOSSARY.md)

**Product:** [PRD](docs/product/PRD.md) · [Features](docs/product/FEATURES.md)

**Architecture:** [Architecture](docs/architecture/ARCHITECTURE.md) · [Agent system](docs/architecture/AGENT_SYSTEM.md) · [Database design](docs/architecture/DATABASE_DESIGN.md) · [API design](docs/architecture/API_DESIGN.md) · [Security](docs/architecture/SECURITY.md) · [Benchmark engine](docs/architecture/BENCHMARK_ENGINE.md) · [Replay engine](docs/architecture/REPLAY_ENGINE.md) · [Deployment](docs/architecture/DEPLOYMENT.md)

**Design:** [Design system](docs/design/DESIGN_SYSTEM.md) · [UI/UX](docs/design/UI_UX.md)

**Engineering:** [File map](docs/engineering/FILE_MAP.md) · [Coding standards](docs/engineering/CODING_STANDARDS.md) · [Testing strategy](docs/engineering/TESTING_STRATEGY.md) · [Observability](docs/engineering/OBSERVABILITY.md) · [Learning guide](docs/engineering/LEARNING.md) · [Decisions & ADRs](docs/engineering/DECISIONS.md)

**Diagrams (designed HTML, Mermaid stays authoritative in each doc):** [System architecture](docs/diagrams/system-architecture.html) · [Trust boundaries](docs/diagrams/trust-boundaries.html) · [Investigation graph](docs/diagrams/langgraph-topology.html)

**Planning:** [Roadmap](docs/planning/ROADMAP.md) · [Tasks](docs/planning/TASKS.md) · [Current phase](docs/planning/CURRENT_PHASE.md) · [Phase report template](docs/planning/PHASE_TEMPLATE.md) · [Risks](docs/planning/RISKS.md)

## Honesty policy

- QueryCure never fabricates benchmark numbers. Example numbers in these docs (e.g. "2.4 s") are illustrative only.
- Prerecorded demo benchmarks are always labeled as such and are never presented as measurements of a user's database.
- "Verified" always means "verified within the tested scope" — dataset, parameters, PostgreSQL version, and hardware are recorded alongside the result.
