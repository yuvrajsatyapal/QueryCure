<div align="center">

# QueryCure

**Find out why your PostgreSQL queries are slow. Then test the fix first.**

An autonomous, multi-agent investigation tool that explains a slow query with cited evidence, then proves the fix in a disposable sandbox before it ever reaches your database.

<br/>

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Pydantic_v2-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-agents-1C3C3C?style=flat-square&logo=langchain&logoColor=white)](https://langchain-ai.github.io/langgraph/)
[![Next.js](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=nextdotjs&logoColor=white)](https://nextjs.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?style=flat-square&logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-4-06B6D4?style=flat-square&logo=tailwindcss&logoColor=white)](https://tailwindcss.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-13--17-4169E1?style=flat-square&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white)](https://www.docker.com/)
[![CI](https://img.shields.io/github/actions/workflow/status/yuvrajsatyapal/QueryCure/ci.yml?style=flat-square&label=CI&logo=githubactions&logoColor=white)](https://github.com/yuvrajsatyapal/QueryCure/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-3CC3B4?style=flat-square)](./LICENSE)

<br/>

[**Watch the 30-second demo**](docs/media/querycure-demo.mp4) · [Architecture](#system-architecture) · [Run locally](#run-locally) · [Docs](#documentation)

<br/>

<a href="docs/media/querycure-demo.mp4">
  <img src="docs/media/05-benchmark.png" alt="QueryCure demo: a sequential scan of 84.4 ms becomes an index scan of 6 microseconds, measured as the median of 30 runs each" width="860"/>
</a>

<sub>Click to play the demo. The numbers are from one recorded PostgreSQL 17.11 run on a synthetic 2,000,000-row table, not a promise for your workload.</sub>

</div>

---

## Table of contents

- [The problem](#the-problem)
- [What QueryCure does](#what-querycure-does)
- [Demo](#demo)
- [Key features](#key-features)
- [How an investigation works](#how-an-investigation-works)
- [How verdicts are decided](#how-verdicts-are-decided)
- [Reading the results](#reading-the-results)
- [System architecture](#system-architecture)
- [Technology stack](#technology-stack)
- [Project structure](#project-structure)
- [Security model](#security-model)
- [Supported and not supported](#supported-and-not-supported)
- [Run locally](#run-locally)
- [Testing and quality](#testing-and-quality)
- [Deployment](#deployment)
- [Development phases](#development-phases)
- [Documentation](#documentation)
- [Honesty policy](#honesty-policy)
- [License](#license)

---

## The problem

When a PostgreSQL query is slow, the usual loop is:

1. Run `EXPLAIN`, squint at a plan tree, guess at a cause.
2. Add an index you *think* will help.
3. Run the query once, see it get faster, and ship it.

Step 3 is where things go wrong. One timing is noise. The index may slow your writes. A "faster" rewrite may quietly return different rows. A warm cache may explain most of the gain. Generic SQL chatbots make it worse: they give confident advice with no evidence behind it.

## What QueryCure does

QueryCure behaves like a small team of database performance engineers. It inspects the query, forms hypotheses that each cite evidence, proposes fixes, **measures them in an isolated sandbox**, and lets fixed statistical rules decide the outcome.

| Step | What happens | Who does it |
|---|---|---|
| **Inspect** | Parse the SQL; collect schema, indexes, statistics and the `EXPLAIN` plan | Deterministic tools |
| **Investigate** | Analyze plan nodes, estimates versus actuals, workload signals | Query Analyzer and Workload Investigator (LLM agents with restricted tools) |
| **Hypothesize** | Ranked root-cause hypotheses, each citing evidence | Supervisor plus specialist agents |
| **Propose** | Index, rewrite and statistics candidates with risks and costs | Index Strategist, Optimization Engineer |
| **Benchmark** | Controlled, repeated, interleaved runs in a disposable sandbox | Deterministic Benchmark Engine |
| **Verify** | Result-set correctness, statistical significance, regressions | Fixed rules first; Benchmark Auditor (can only downgrade) second |
| **Report** | Sealed, evidence-backed report with confidence, trade-offs and rollback | Report builder |

> **Core principle.** A recommendation is not a *verified improvement* until it has been benchmarked against a representative workload and passed the correctness checks. QueryCure is allowed, and expected, to conclude "inconclusive."

---

## Demo

A 30-second walkthrough of one recorded investigation: paste a slow query, watch cited findings arrive, approve the exact SQL, see the measured result, then open a sealed report you can replay.

<div align="center">
<a href="docs/media/querycure-demo.mp4"><b>Play the full demo video (30 s, 1080p)</b></a>
</div>

<br/>

| | |
|---|---|
| ![Paste the slow query](docs/media/02-paste-query.png) | ![Every cause, cited](docs/media/03-agents-cited.png) |
| **1. Paste the slow query.** The SQL, its plan and the schema go in. The sidebar shows the six steps of an investigation. | **2. Every cause, cited.** Specialist agents return typed findings, each tied to evidence IDs such as `ev_31a7`. |
| ![Nothing runs without your OK](docs/media/04-approval.png) | ![Test the fix first](docs/media/05-benchmark.png) |
| **3. Nothing runs without your OK.** You see the exact SQL and where it runs: a disposable sandbox, never your database. | **4. Test the fix first.** Same query, same parameters, median of 30 runs each: 84.4 ms down to 6 µs on this recorded run. |

![A report you can replay](docs/media/06-sealed-report.png)

**5. A report you can replay.** Every run ends in exactly one of four outcomes. The report is sealed with digests, and *Replay report* re-checks it against them with no model involved.

> These frames come from a recorded run on PostgreSQL 17.11 against a synthetic 2,000,000-row table. Every number in the video is read from the recording the landing page uses, not typed in by hand.

---

## Key features

- **Evidence, not assertions.** Every finding cites stored evidence (plan nodes, statistics, measurements). Uncited claims are removed before they reach you.
- **Measured, not predicted.** A candidate is "verified" only after an interleaved, repeated benchmark in a sandbox clone shows a real effect with a confidence interval, and returns the same rows as the original query.
- **Rules decide, models advise.** Verdicts come from deterministic statistics (`bench@2`). The Benchmark Auditor model can downgrade a verdict, never upgrade one, and the database enforces that.
- **"Inconclusive" is a valid answer.** On noisy hardware most honest benchmarks end inconclusive, and the report says so instead of picking a winner.
- **Your database is never modified.** Live inspection runs plain `EXPLAIN` in read-only sessions. AI-written SQL runs only in sandbox clones, after you approve the exact statement.
- **Live, resumable runs.** A PostgreSQL-backed job queue plus a persisted event log streams progress over SSE. Runs resume from LangGraph checkpoints after a restart.
- **Sealed and replayable.** Reports are stored with digests. Report replay re-checks them without a model. Experiment replay re-measures them.
- **Bring your own key.** Free OpenRouter models only. Keys are stored encrypted and shown only as their last four characters.
- **Honest labels everywhere.** Every claim in the UI is one of: Observed, Hypothesis, Recommendation, Verified, Rejected, Inconclusive.

---

## How an investigation works

<div align="center">
<img src="docs/images/investigation-flow.svg" alt="Flow diagram: inputs, specialist agents, materiality gate, human approval, sandbox experiment, fixed-rule verification, sealed report, with early exits for no action needed and unverified recommendation" width="640"/>
</div>

1. **Intake and context.** Your query, plan and schema are parsed. In sandbox mode, a clone of a demo workload is `EXPLAIN`ed.
2. **Specialist agents.** A supervisor fans out to a Query Analyzer, an Index Strategist and a Workload Investigator. Each uses an allowlist of typed tools and returns cited findings and ranked hypotheses.
3. **Synthesis and materiality.** Hypotheses are combined, and a deterministic gate decides whether optimizing is worth it at all. If not, the run ends with **No action needed**.
4. **Optimization tournament.** An Optimization Engineer proposes candidates inside a strict DDL allowlist. **You approve the exact SQL.** Declining ends the run with an **Unverified recommendation**.
5. **Experiment.** The Benchmark Engine measures every candidate against the baseline under identical, interleaved conditions in a throwaway sandbox clone.
6. **Audit and report.** Fixed rules set the verdict. The Benchmark Auditor reviews it, downgrade only. The run is finalized into a sealed report (Markdown and JSON) with a manifest digest.

### Request lifecycle

```mermaid
sequenceDiagram
  autonumber
  participant B as Browser
  participant A as API (FastAPI)
  participant D as Metadata Postgres
  participant W as Worker (LangGraph)
  participant L as LLM provider

  B->>A: Start investigation (REST)
  A->>D: Insert run + enqueue job
  A-->>B: Run ID
  B->>A: Open event stream (SSE)
  W->>D: Claim job (FOR UPDATE SKIP LOCKED)
  loop Each agent node
    W->>L: Typed prompt (BYOK)
    L-->>W: Structured, cited output
    W->>D: Persist event + checkpoint
    D-->>A: LISTEN / NOTIFY
    A-->>B: SSE event
  end
  W->>D: Seal report + digests
  A-->>B: Run completed
```

---

## How verdicts are decided

<div align="center">
<img src="docs/images/verdict-rules.svg" alt="Seven ordered deterministic gates. The first failing gate sets rejected or inconclusive with a reason code. Passing all gates yields verified within the tested scope. The Benchmark Auditor model may only downgrade to inconclusive." width="640"/>
</div>

The benchmark engine and verification rules are plain deterministic Python. **No LLM ever computes a metric**, and no model can turn a `rejected` verdict into anything better. The gates above run in order; the first one that fails sets the verdict and a reason code. Details: [BENCHMARK_ENGINE](docs/architecture/BENCHMARK_ENGINE.md).

## Reading the results

| Label | Meaning |
|---|---|
| **Verified** (within the tested scope) | Faster by more than the minimum effect, confidence interval clear of noise, same rows returned. Valid for the dataset, parameters, PostgreSQL version and hardware recorded with it |
| **Verified with noise warning** | Noisy measurements, but three independent experiments agreed. Always shown in words, never relabeled plain "verified" |
| **Rejected** | A measured regression, different result rows, or a failed build. The reason is named |
| **Inconclusive** | Not enough evidence either way, often noise on a laptop. Not a failure: no claim is made |
| **Unverified recommendation** | Advice from analysis only; nothing was benchmarked |
| Experiment replay: **reproduced** / **reproduced with drift** / **not reproduced** / **inconclusive** | Whether a re-measurement agrees with the original within ±25% speed-up drift ([ADR-0023](docs/engineering/adr/ADR-0023-d9-experiment-replay-equivalence-margin.md)) |
| Report replay **verified** | The stored report still matches its stored digests. This proves consistency, not authenticity |

---

## System architecture

<div align="center">
<img src="docs/images/architecture.svg" alt="Architecture: Next.js web app, FastAPI API, PostgreSQL metadata database acting as the job queue, an agent worker that calls LLM providers, runs plain EXPLAIN against your database and benchmarks in a sandbox Postgres" width="100%"/>
</div>

QueryCure is a **modular monolith**: a `frontend/` (Next.js) and a `backend/` (one Python package that runs as two processes, `api` and `worker`). There are no microservices and no Kubernetes.

| Decision | Why |
|---|---|
| **PostgreSQL is the job queue** (`FOR UPDATE SKIP LOCKED`) | One less moving part than Redis or Celery; durable by construction ([ADR-0004](docs/engineering/adr/ADR-0004-postgres-job-queue.md)) |
| **Persisted events plus `LISTEN/NOTIFY` become SSE** | Progress survives reconnects and restarts ([ADR-0005](docs/engineering/adr/ADR-0005-sse-event-log.md)) |
| **LangGraph is the only orchestrator** | Agents exchange Pydantic models, not free text. Graph state holds references (IDs, hashes), never raw datasets or credentials |
| **Three databases, never mixed** | The *metadata DB* (ours), the *target DB* (yours, read-only inspection), and the *sandbox DB* (disposable) |
| **Backend owns auth** | The frontend never talks to the metadata database |

Full details: [ARCHITECTURE](docs/architecture/ARCHITECTURE.md) · [AGENT_SYSTEM](docs/architecture/AGENT_SYSTEM.md) · designed diagrams in [docs/diagrams/](docs/diagrams/).

---

## Technology stack

| Layer | Choice |
|---|---|
| **Frontend** | Next.js 16 (App Router), TypeScript, Tailwind CSS 4, TanStack Query, React Flow + dagre, CodeMirror 6 |
| **Backend** | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async) + Alembic, psycopg 3, SQLGlot |
| **AI** | LangGraph, LangChain (model integration and structured output), OpenRouter, Gemini, BYOK |
| **Data** | PostgreSQL for metadata (Neon in a hosted demo), Docker PostgreSQL for sandboxes |
| **Jobs** | PostgreSQL job queue (`SKIP LOCKED`) with `LISTEN/NOTIFY`. No Redis |
| **Observability** | structlog JSON logs with request, job and run correlation IDs; Prometheus-format metrics computed from the database |
| **Testing** | pytest (unit, real-Postgres integration, security), Vitest, Playwright + axe, recorded-LLM evals with prerecorded measurement fixtures |
| **Delivery** | Docker Compose (local, demo and production profiles), GitHub Actions (CI and weekly dependency audits) |
| **Video** | Remotion project in [`video/`](video/) renders the demo from the same recorded run the landing page uses |

Rationale for each choice: [DECISIONS](docs/engineering/DECISIONS.md) and 34 ADRs in [docs/engineering/adr/](docs/engineering/adr/).

---

## Project structure

```text
QueryCure/
├── backend/                     # One Python package, two processes (api + worker)
│   ├── src/querycure/
│   │   ├── api/                 # FastAPI app, routers, SSE
│   │   ├── agents/              # LangGraph graph, nodes, tools, versioned prompts, budgets
│   │   ├── benchmark/           # Deterministic stats, schedule, correctness, verdict rules
│   │   ├── sandbox/             # Disposable sandbox provisioning (Mode C)
│   │   ├── connectors/          # Inspection gateway: allowlisted read-only access (Mode B)
│   │   ├── audit/               # Benchmark Auditor (downgrade-only)
│   │   ├── reports/ replay/     # Sealed reports, builders, renderers, replay engine
│   │   ├── evidence/ events/    # Evidence IDs and the persisted event log
│   │   ├── jobs/ worker/        # Postgres job queue and the worker process
│   │   ├── sql/ plans/          # SQLGlot validation, EXPLAIN plan parsing
│   │   ├── llm/ auth/ db/ core/ # Providers, sessions, repositories, errors
│   │   └── workloads/ demo/     # Six demo workloads and the prerecorded gallery
│   ├── migrations/              # Alembic
│   ├── tests/                   # unit / integration / security / rehearsal
│   └── evals/                   # Recorded-LLM eval cases and measurement fixtures
├── frontend/                    # Next.js app (landing, demo gallery, app)
│   ├── src/                     # app / components / lib / styles
│   └── e2e/                     # Playwright + axe
├── infra/docker/                # compose.yaml (local), compose.demo.yaml, compose.prod.yaml
├── video/                       # Remotion source for the demo video
└── docs/                        # Product, architecture, design, planning, ADRs, reports
    └── media/                   # Demo video and screenshots used in this README
```

---

## Security model

QueryCure runs LLM-authored SQL, so the boundary is enforced in the database, not in a prompt.

- **The LLM never receives a database client.** All access goes through the inspection gateway (Mode B) or the sandbox module (Mode C), using allowlisted operations.
- **Mode B is plain `EXPLAIN (FORMAT JSON)` only.** Never `EXPLAIN ANALYZE`, never DDL or DML. Every session is read-only and sets `statement_timeout`, `lock_timeout` and `idle_in_transaction_session_timeout`. Superuser connections are refused.
- **SQL validation (SQLGlot) is defense in depth, not the boundary.** The database-side controls stay on even when the parser agrees.
- **Prompt-injection fencing.** Schema names, comments, plan text and query text are treated as untrusted input to prompts.
- **SSRF guard.** Connection targets are resolved, checked and pinned to a `hostaddr` before connecting.
- **Secrets are never logged or stored in graph state.** Saved connection passwords and API keys are encrypted with a master key and redacted by helpers.
- **You approve every sandbox statement.** The approval shows the exact SQL.

Full threat model: [SECURITY](docs/architecture/SECURITY.md).

---

## Supported and not supported

| Supported | Not supported (yet) |
|---|---|
| PostgreSQL 13 to 17 JSON plans; single `SELECT` statements | DML and DDL analysis; text-format plans |
| Offline analysis (Mode A) everywhere | Live inspection (Mode B) on a public demo |
| Live `EXPLAIN` (Mode B) on a local install | `EXPLAIN ANALYZE` on your database (never) |
| Sandbox benchmarking (Mode C) of six demo workloads, locally | Benchmarks on your own data or user-provisioned sandboxes |
| Free OpenRouter models with your own key (BYOK) | Paid models (refused by design, [ADR-0016](docs/engineering/adr/ADR-0016-free-openrouter-models-only.md)) |
| Anonymous sessions, GitHub and Google sign-in, restricted-access allowlist | Teams, sharing, admin roles |
| Report replay, experiment replay, AI re-investigation (start) | Conclusion diff between investigations; write-overhead benchmarks |

---

## Run locally

**Prerequisites:** Docker (Compose v2), [uv](https://docs.astral.sh/uv/), Node.js 22, and pnpm 10 (`corepack enable` provides the pinned version). uv installs Python 3.12 if needed.

### 1. Databases

Starts the metadata DB on `127.0.0.1:5432` and the sandbox DB on an internal network. Both use dev-only passwords; the first start also creates the restricted `qc_app` role.

```bash
docker compose -f infra/docker/compose.yaml up -d --wait
```

### 2. Backend config

```bash
cp backend/.env.example backend/.env
```

Generate a master key (it encrypts saved connection passwords) and paste it after `QC_MASTER_KEY=` in `backend/.env`:

```bash
python3 -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
```

### 3. Migrations and API

The API runs as `qc_app`; migrations run as the owner role.

```bash
cd backend && uv sync && uv run alembic upgrade head
```

```bash
cd backend && uv run uvicorn querycure.api.main:app --port 8000
```

`curl http://localhost:8000/api/v1/readyz` should return `{"status":"ok","database":"ok","migrations":"current"}`.

### 4. Web app (second terminal)

```bash
cd frontend && pnpm install && pnpm dev
```

Open <http://localhost:3000/app>. A local session is created automatically.

### 5. LLM key and worker (for investigations)

QueryCure uses free OpenRouter models only; paid models are refused. Either save your key in the app under **Settings** (stored encrypted), or put it after `OPENROUTER_API_KEY=` in `backend/.env`. Then run the worker in a third terminal:

```bash
cd backend && uv run python -m querycure.worker
```

> To try the UI with no model at all, start the API and worker with `LLM_PROVIDER=stub` (canned, labeled output, local profile only).

### 6. Analyze a plan, then investigate

Go to **New investigation**, paste the output of `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) …` and choose **Analyze plan**. Real example plans are in `backend/tests/fixtures/plans/pg17_*.json`. Then start an investigation: the timeline streams live, and every finding links to the plan node it cites. Free models are slow (a run takes a few minutes) and limited to about 50 requests per day.

### 7. Optional: live `EXPLAIN` against a demo database

<details>
<summary>Load the <code>orders_ecommerce</code> workload and connect a restricted role</summary>

```bash
docker compose -f infra/docker/compose.yaml exec metadata-db psql -U qc_owner -d querycure -c "CREATE DATABASE qc_demo_orders"
```

```bash
cd backend && uv run python -m querycure.workloads postgresql://qc_owner:qc_local_dev_only@127.0.0.1:5432/qc_demo_orders 'orders_ecommerce@v1:sf=0.1:seed=42'
```

```bash
docker compose -f infra/docker/compose.yaml exec metadata-db psql -U qc_owner -d qc_demo_orders -c "CREATE ROLE qc_demo_inspector LOGIN PASSWORD 'demo_inspector_local_only'; GRANT CONNECT ON DATABASE qc_demo_orders TO qc_demo_inspector; GRANT USAGE ON SCHEMA public TO qc_demo_inspector; GRANT SELECT ON ALL TABLES IN SCHEMA public TO qc_demo_inspector; GRANT pg_read_all_stats TO qc_demo_inspector;"
```

In **Connections**, add host `127.0.0.1`, port `5432`, database `qc_demo_orders`, user `qc_demo_inspector`, password `demo_inspector_local_only`, and set **TLS** to `disable (local only)` (the compose container has no TLS). Choose **Test**, then use the **Live EXPLAIN** tab with a query such as:

```sql
SELECT * FROM orders WHERE customer_id = 1024 ORDER BY created_at DESC LIMIT 20
```

It runs plain `EXPLAIN` only, so nothing is executed.

</details>

### 8. Optional: the prerecorded demo gallery

Open <http://localhost:3000/demo>. It needs no model and no sandbox: real model answers and real sandbox measurements, recorded once and labeled `prerecorded` on every page.

### Run the restricted public-demo profile locally

The configuration a public deployment uses: anonymous sessions, BYOK only, strict rate limits, no live sandbox, no live database inspection, plus the gallery. The API runs with an embedded worker.

```bash
export QC_MASTER_KEY=$(python3 -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())")
docker compose -f infra/docker/compose.demo.yaml up --build
```

Open <http://localhost:3300> (API on `:8300`). Stop it with `docker compose -f infra/docker/compose.demo.yaml down -v`.

---

## Testing and quality

```bash
# backend
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q
uv run pytest tests/integration -q     # needs the compose databases running
uv run pytest tests/security -q

# frontend
cd frontend && pnpm lint && pnpm typecheck && pnpm test
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 pnpm build
pnpm exec playwright test              # end-to-end, with axe accessibility checks
```

- **TDD for deterministic logic:** parsers, validators, statistics and state transitions are written test first.
- **Every security control has a negative test** in `backend/tests/security/`.
- **Agent changes need an eval case** or an updated recorded fixture in `backend/evals/`.
- **CI** runs lint, types, unit, integration, security, recorded evals and Playwright on every push. A separate workflow audits dependencies weekly.

Strategy: [TESTING_STRATEGY](docs/engineering/TESTING_STRATEGY.md).

---

## Deployment

Hosting is deliberately small: one always-on container for the API (with the embedded worker), one for the web app, and managed Postgres. Two routes are documented in [DEPLOYMENT](docs/architecture/DEPLOYMENT.md):

- **Single VM.** `infra/docker/compose.prod.yaml` with a Caddy reverse proxy and a guarded release script.
- **Render + Neon.** A Docker web service for the API (`uvicorn querycure.api.main:app --host 0.0.0.0 --port $PORT`, health check `/api/v1/healthz`) and a Node web service for Next.js that proxies `/api/v1/*` to it.

Hosted deployments run the restricted demo profile with an access allowlist, so the sign-in page shows **Private trial · approved accounts only**. Pre-release checks: [RELEASE_CHECKLIST](docs/engineering/RELEASE_CHECKLIST.md).

---

## Development phases

| Phase | Theme | Status |
|---|---|---|
| 0 | Documentation and architecture | Done |
| 1 | Foundation: repo, API, metadata DB, SQL and plan parsing, demo workloads, editor | Done ([report](docs/planning/reports/PHASE_1_REPORT.md)) |
| 2 | Multi-agent intelligence: LangGraph supervisor, analyzer agents, streaming | Implemented ([report](docs/planning/reports/PHASE_2_REPORT.md)) |
| 3 | Optimization and benchmarking: sandbox, benchmark engine, tournament | Implemented ([report](docs/planning/reports/PHASE_3_REPORT.md)) |
| 4 | Verification and replay: auditor, lineage, replay, regression detection | Implemented ([report](docs/planning/reports/PHASE_4_REPORT.md)) |
| 5 | Production polish: auth, BYOK, hardening, demo gallery, operations, deployment artifacts | Implemented and verified locally ([report](docs/planning/reports/PHASE_5_REPORT.md)) |

Roadmap: [ROADMAP](docs/planning/ROADMAP.md) · Current state: [CURRENT_PHASE](docs/planning/CURRENT_PHASE.md).

---

## Documentation

| Area | Read |
|---|---|
| **Product** | [PRD](docs/product/PRD.md) · [Features](docs/product/FEATURES.md) · [Glossary](docs/GLOSSARY.md) |
| **Architecture** | [Architecture](docs/architecture/ARCHITECTURE.md) · [Agent system](docs/architecture/AGENT_SYSTEM.md) · [Database design](docs/architecture/DATABASE_DESIGN.md) · [API design](docs/architecture/API_DESIGN.md) · [Security](docs/architecture/SECURITY.md) · [Benchmark engine](docs/architecture/BENCHMARK_ENGINE.md) · [Replay engine](docs/architecture/REPLAY_ENGINE.md) · [Deployment](docs/architecture/DEPLOYMENT.md) |
| **Design** | [Design system](docs/design/DESIGN_SYSTEM.md) · [UI/UX](docs/design/UI_UX.md) |
| **Engineering** | [File map](docs/engineering/FILE_MAP.md) · [Coding standards](docs/engineering/CODING_STANDARDS.md) · [Testing strategy](docs/engineering/TESTING_STRATEGY.md) · [Observability](docs/engineering/OBSERVABILITY.md) · [Learning guide](docs/engineering/LEARNING.md) · [Decisions and ADRs](docs/engineering/DECISIONS.md) |
| **Planning** | [Roadmap](docs/planning/ROADMAP.md) · [Tasks](docs/planning/TASKS.md) · [Risks](docs/planning/RISKS.md) |
| **Contributors and agents** | [CLAUDE.md](CLAUDE.md) · [AGENTS.md](AGENTS.md) |

---

## Honesty policy

- QueryCure never fabricates benchmark numbers. Example numbers in the docs are illustrative only.
- Prerecorded demo benchmarks are always labeled as such and are never presented as measurements of your database.
- **"Verified" always means "verified within the tested scope":** dataset, parameters, PostgreSQL version and hardware are recorded alongside the result.
- Report replay proves *consistency against stored digests*, not authenticity. It is not described as tamper-proof or certified.

---

## License

Released under the [MIT License](LICENSE). Copyright (c) 2026 Yuvraj Satyapal.
