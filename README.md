# QueryCure

> Autonomous, multi-agent investigation and *verified* optimization of PostgreSQL query performance.

**Project status: Phase 5 (production polish) implemented and verified locally; not publicly deployed.** All five phases are built: multi-agent investigation, sandbox benchmarking with deterministic verdicts, a downgrade-only Benchmark Auditor, sealed reports with replay, and Phase 5's hardening, BYOK, GitHub sign-in, the run-history UI, the prerecorded demo gallery, operations tooling and deployment artifacts. Nothing is hosted publicly yet: that needs the owner's approval, a domain and accounts ([DEPLOYMENT](docs/architecture/DEPLOYMENT.md), [release checklist](docs/engineering/RELEASE_CHECKLIST.md)). Details and exact test results: [Phase 5 report](docs/planning/reports/PHASE_5_REPORT.md).

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

## How it differs from a SQL optimizer or chatbot

- **Evidence, not assertions.** Every finding cites stored evidence (plan nodes, statistics, measurements); uncited claims are removed before they reach you.
- **Measured, not predicted.** A candidate index or rewrite is "verified" only after an interleaved, repeated benchmark in a disposable sandbox clone shows a real effect with a confidence interval, and the result rows are identical to the original query's.
- **Rules decide, models advise.** Verdicts come from deterministic statistics (`bench@2`). The Benchmark Auditor model may downgrade a verdict, never upgrade one; the database enforces that.
- **"Inconclusive" is a valid answer.** On noisy hardware most honest benchmarks end inconclusive, and the report says so instead of picking a winner.
- **Your database is never modified.** Live inspection runs plain `EXPLAIN` in read-only sessions only. AI-written SQL runs only in sandbox clones, after you approve the exact SQL.
- **Replayable.** Finished reports are sealed with digests. Report replay re-checks them without a model, and experiment replay re-measures them.

## How an investigation works

1. **Intake and context.** Your query, plan and schema are parsed; in sandbox mode a clone of a demo workload is EXPLAINed.
2. **Specialist agents.** A supervisor fans out to a Query Analyzer, an Index Strategist and a Workload Investigator. Each uses an allowlist of typed tools and returns cited findings and ranked hypotheses.
3. **Synthesis and materiality.** The hypotheses are combined, and a deterministic gate decides whether optimizing is worth it at all.
4. **Optimization tournament** (sandbox mode). An Optimization Engineer proposes candidates within a strict DDL allowlist. You approve the exact SQL, and the benchmark engine measures every candidate against the baseline under identical, interleaved conditions.
5. **Audit and report.** The Benchmark Auditor reviews the verdicts (downgrade-only). The run is finalized into a sealed report: Markdown and JSON, with a manifest digest.

## Reading the results

| Label | Meaning |
|---|---|
| **Verified** (within the tested scope) | The candidate was faster by more than the minimum effect, with a confidence interval clear of noise, and returned the same rows. Valid for the dataset, parameters, PostgreSQL version and hardware recorded with it |
| **Verified with noise warning** | Noisy measurements, but three independent experiments agreed |
| **Rejected** | A measured regression, different result rows, or a failed build. The reason is named |
| **Inconclusive** | Not enough evidence either way (often noise on a laptop). Not a failure: no claim is made |
| **Unverified recommendation** | Advice from analysis only; nothing was benchmarked (offline mode) |
| Experiment replay: **reproduced** / **reproduced with drift** / **not reproduced** / **inconclusive** | Whether a re-measurement agrees with the original within ±25% speed-up drift. Same-machine replays on Docker Desktop are mostly inconclusive because of noise ([ADR-0023](docs/engineering/adr/ADR-0023-d9-experiment-replay-equivalence-margin.md)) |
| Report replay **verified** | The stored report still matches its stored digests. This proves consistency, not authenticity |

## Supported and not supported

| Supported | Not supported (yet) |
|---|---|
| PostgreSQL 13–17 JSON plans; single `SELECT` statements | DML/DDL analysis; text-format plans |
| Offline analysis (Mode A) everywhere | Live inspection (Mode B) on the public demo |
| Live `EXPLAIN` (Mode B) on a local install | `EXPLAIN ANALYZE` on your database (never) |
| Sandbox benchmarking (Mode C) of six demo workloads, locally | Benchmarks on your own data or user-provisioned sandboxes |
| Free OpenRouter models with your own key (BYOK) | Paid models (refused by design, ADR-0016) |
| Anonymous sessions, GitHub sign-in | Teams, sharing, admin roles |
| Report replay, experiment replay, AI re-investigation (start) | Conclusion diff between investigations; write-overhead benchmarks |

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

## Technology stack

| Layer | Choice |
|---|---|
| Frontend | Next.js 16 (App Router), TypeScript, Tailwind CSS 4, TanStack Query, React Flow + dagre, CodeMirror 6 |
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async) + Alembic, psycopg 3, SQLGlot |
| AI | LangGraph, LangChain (model integration + structured output), Gemini, OpenRouter, BYOK |
| Data | PostgreSQL for metadata (Neon in the public demo), Docker PostgreSQL for sandboxes |
| Jobs | PostgreSQL-backed job queue (`SKIP LOCKED`) + `LISTEN/NOTIFY` — no Redis in MVP ([ADR-0004](docs/engineering/adr/ADR-0004-postgres-job-queue.md)) |
| Observability | structlog JSON logs with request/job/run correlation IDs, Prometheus-format metrics computed from the database (OpenTelemetry export and LangSmith deferred) |
| Testing | pytest (unit, real-Postgres integration, security), Vitest, Playwright + axe, recorded-LLM evals with prerecorded measurement fixtures |
| Delivery | Docker Compose (local and restricted-demo profiles), images for the API/worker and web, GitHub Actions (CI + weekly audits). Target hosting: Vercel (web), one always-on container (API + embedded worker), managed Postgres; not deployed yet |

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

**5. LLM key and worker (for investigations).** QueryCure uses free OpenRouter models only; paid models are refused. Either save your key in the app under **Settings** (stored encrypted, shown only as its last four characters), or put it after `OPENROUTER_API_KEY=` in `backend/.env` for the local profile (the pinned model is in `.env.example`). Then run the worker in a third terminal:

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

**8. Optional: the prerecorded demo gallery** is at <http://localhost:3000/demo>. It needs no model and no sandbox: real model answers and real sandbox measurements, recorded once and labelled `prerecorded` on every page.

### Run the restricted public-demo profile locally

This is the configuration a public deployment uses: anonymous sessions, BYOK only, strict rate limits, no live sandbox and no live database inspection, plus the gallery. It runs the API with an embedded worker.

```bash
export QC_MASTER_KEY=$(python3 -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())")
```

```bash
docker compose -f infra/docker/compose.demo.yaml up --build
```

Then open <http://localhost:3300> (API on `:8300`). Stop it with `docker compose -f infra/docker/compose.demo.yaml down -v`.

**Checks:** see the verification commands in [CLAUDE.md §7](CLAUDE.md#7-verification-commands-valid-once-phase-1-scaffolding-exists). Integration tests need the compose databases running.

## Development phases

| Phase | Theme | Status |
|---|---|---|
| 0 | Documentation & architecture | Done |
| 1 | Foundation: repo, API, metadata DB, SQL/plan parsing, demo workloads, editor | Done ([report](docs/planning/reports/PHASE_1_REPORT.md)) |
| 2 | Multi-agent intelligence: LangGraph supervisor, analyzer agents, streaming | Implemented; exit partially met ([report](docs/planning/reports/PHASE_2_REPORT.md)) |
| 3 | Optimization & benchmarking: sandbox, benchmark engine, tournament | Implemented; exit partially met ([report](docs/planning/reports/PHASE_3_REPORT.md)) |
| 4 | Verification & replay: auditor, lineage, replay, regression detection | Implemented; owner-reviewed ([report](docs/planning/reports/PHASE_4_REPORT.md)) |
| 5 | Production polish: auth, BYOK, hardening, demo gallery, operations, deployment artifacts | Implemented and verified locally; **not deployed** ([report](docs/planning/reports/PHASE_5_REPORT.md)) |

See [docs/planning/ROADMAP.md](docs/planning/ROADMAP.md).

## Documentation index

**Agent/contributor instructions:** [CLAUDE.md](CLAUDE.md) · [AGENTS.md](AGENTS.md) · [Glossary](docs/GLOSSARY.md)

**Product:** [PRD](docs/product/PRD.md) · [Features](docs/product/FEATURES.md)

**Architecture:** [Architecture](docs/architecture/ARCHITECTURE.md) · [Agent system](docs/architecture/AGENT_SYSTEM.md) · [Database design](docs/architecture/DATABASE_DESIGN.md) · [API design](docs/architecture/API_DESIGN.md) · [Security](docs/architecture/SECURITY.md) · [Benchmark engine](docs/architecture/BENCHMARK_ENGINE.md) · [Replay engine](docs/architecture/REPLAY_ENGINE.md) · [Deployment](docs/architecture/DEPLOYMENT.md)

**Design:** [Design system](docs/design/DESIGN_SYSTEM.md) · [UI/UX](docs/design/UI_UX.md)

**Operations:** [Release checklist](docs/engineering/RELEASE_CHECKLIST.md)

**Engineering:** [File map](docs/engineering/FILE_MAP.md) · [Coding standards](docs/engineering/CODING_STANDARDS.md) · [Testing strategy](docs/engineering/TESTING_STRATEGY.md) · [Observability](docs/engineering/OBSERVABILITY.md) · [Learning guide](docs/engineering/LEARNING.md) · [Decisions & ADRs](docs/engineering/DECISIONS.md)

**Diagrams (designed HTML, Mermaid stays authoritative in each doc):** [System architecture](docs/diagrams/system-architecture.html) · [Trust boundaries](docs/diagrams/trust-boundaries.html) · [Investigation graph](docs/diagrams/langgraph-topology.html)

**Planning:** [Roadmap](docs/planning/ROADMAP.md) · [Tasks](docs/planning/TASKS.md) · [Current phase](docs/planning/CURRENT_PHASE.md) · [Phase report template](docs/planning/PHASE_TEMPLATE.md) · [Risks](docs/planning/RISKS.md)

## Honesty policy

- QueryCure never fabricates benchmark numbers. Example numbers in these docs (e.g. "2.4 s") are illustrative only.
- Prerecorded demo benchmarks are always labeled as such and are never presented as measurements of a user's database.
- "Verified" always means "verified within the tested scope" — dataset, parameters, PostgreSQL version, and hardware are recorded alongside the result.
