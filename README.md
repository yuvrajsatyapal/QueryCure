<div align="center">

# QueryCure

**An autonomous multi-agent investigator for slow PostgreSQL queries. It explains the cause with cited evidence, then proves the fix in a disposable sandbox before it ever reaches your database.**

<br/>

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Pydantic_v2-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-agents-1C3C3C?style=flat-square&logo=langchain&logoColor=white)](https://langchain-ai.github.io/langgraph/)
[![Next.js](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=nextdotjs&logoColor=white)](https://nextjs.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?style=flat-square&logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-4-06B6D4?style=flat-square&logo=tailwindcss&logoColor=white)](https://tailwindcss.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-13--17-4169E1?style=flat-square&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2_async-D71F00?style=flat-square&logo=sqlalchemy&logoColor=white)](https://www.sqlalchemy.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white)](https://www.docker.com/)
[![pnpm](https://img.shields.io/badge/pnpm-10-F69220?style=flat-square&logo=pnpm&logoColor=white)](https://pnpm.io/)
[![uv](https://img.shields.io/badge/uv-Python-DE5FE9?style=flat-square&logo=uv&logoColor=white)](https://docs.astral.sh/uv/)
[![CI](https://img.shields.io/github/actions/workflow/status/yuvrajsatyapal/QueryCure/ci.yml?style=flat-square&label=CI&logo=githubactions&logoColor=white)](https://github.com/yuvrajsatyapal/QueryCure/actions)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](./LICENSE)

<br/>

https://github.com/user-attachments/assets/8c922fb2-9036-4358-9abb-4b55c7fae05e

<sub>One recorded PostgreSQL 17.11 run on a synthetic 2,000,000-row table, not a promise for your workload. Every number in the video is read from the recording the landing page uses, not typed in by hand.</sub>

</div>

---

## Table of Contents

- [Screenshots](#screenshots)
- [Project Overview](#project-overview)
- [Key Features](#key-features)
- [Tech Stack](#tech-stack)
- [System Architecture](#system-architecture)
- [High-Level System Design](#high-level-system-design)
- [Investigation Flow](#investigation-flow)
- [Agent System](#agent-system)
- [Benchmark Engine](#benchmark-engine)
- [Verification Rules](#verification-rules)
- [Reports and Replay](#reports-and-replay)
- [Folder Structure](#folder-structure)
- [Database Schema](#database-schema)
- [Authentication Flow](#authentication-flow)
- [Real-Time Architecture](#real-time-architecture)
- [API Reference](#api-reference)
- [Environment Variables](#environment-variables)
- [Local Development](#local-development)
- [Production Deployment](#production-deployment)
- [Security](#security)
- [Reliability and Budgets](#reliability-and-budgets)
- [Observability](#observability)
- [Testing](#testing)
- [Project Workflow](#project-workflow)
- [CI / CD](#ci--cd)
- [Roadmap](#roadmap)
- [Documentation](#documentation)
- [Honesty Policy](#honesty-policy)
- [License](#license)

---

## Screenshots

Every screen supports light and dark mode.

<sub>These captures come from QueryCure's own end-to-end and visual tests against a local stack. Run names such as `E2E sandbox 1792812211898` and the `stub/canned via stub` label are test artifacts: the tests use a stub model and seeded fixtures to stay deterministic. The demo video above is the recorded investigation with real model output.</sub>

### Dashboard
Active investigations, a run-outcomes bar for the last 25 investigations, recent runs, and counts by state.

| Light | Dark |
|---|---|
| ![Dashboard — light](docs/images/screenshots/dashboard-light.png) | ![Dashboard — dark](docs/images/screenshots/dashboard-dark.png) |

### History
Every investigation and its latest run, newest first, with search plus status and outcome filters.

| Light | Dark |
|---|---|
| ![History — light](docs/images/screenshots/history-light.png) | ![History — dark](docs/images/screenshots/history-dark.png) |

### Run Workspace — Waiting for Approval
The LangGraph topology with each node's state taken from recorded events. The run is paused at `approval_gate` until you decide. Later nodes show "no events recorded", never a guess.

| Light | Dark |
|---|---|
| ![Run waiting for approval — light](docs/images/screenshots/run-approval-light.png) | ![Run waiting for approval — dark](docs/images/screenshots/run-approval-dark.png) |

### Run Workspace — Completed Graph
Pick any node to see its input, output, metadata and the evidence it cited. The model prompt is never sent to the browser; only its version is stored.

| Light | Dark |
|---|---|
| ![Completed run graph — light](docs/images/screenshots/run-graph-light.png) | ![Completed run graph — dark](docs/images/screenshots/run-graph-dark.png) |

### Run Workspace — Trace
A trace of every step, tool call and logged event with timings, plus hypotheses and per-agent findings. Each finding links to the evidence ID it cites.

| Light | Dark |
|---|---|
| ![Run trace — light](docs/images/screenshots/run-trace-light.png) | ![Run trace — dark](docs/images/screenshots/run-trace-dark.png) |

### Speed-up with Confidence Interval
Per parameter set: median speed-up, its 95% bootstrap interval, the 1.00× no-change line, the minimum effect and the maximum regression, on a log axis.

| Light | Dark |
|---|---|
| ![Speed-up chart — light](docs/images/screenshots/chart-speedup-light.png) | ![Speed-up chart — dark](docs/images/screenshots/chart-speedup-dark.png) |

### Timing Distributions
Every measured sample for baseline and candidate, with the median, kept outliers and the transport floor (the cost of a bare round trip), so noise is visible instead of hidden.

| Light | Dark |
|---|---|
| ![Timing distributions — light](docs/images/screenshots/chart-distributions-light.png) | ![Timing distributions — dark](docs/images/screenshots/chart-distributions-dark.png) |

### Sealed Report — Recommendation Reproduced
An experiment replay re-measured the same experiment with the same seed and no model calls, and matched the original within the equivalence margin.

| Light | Dark |
|---|---|
| ![Replay report reproduced — light](docs/images/screenshots/replay-reproduced-light.png) | ![Replay report reproduced — dark](docs/images/screenshots/replay-reproduced-dark.png) |

### Sealed Report — Performance Drift Detected
Correctness held, but the speed-up moved beyond the margin, so the report says the original claim is **not confirmed** instead of declaring a pass.

| Light | Dark |
|---|---|
| ![Replay report with drift — light](docs/images/screenshots/replay-drift-light.png) | ![Replay report with drift — dark](docs/images/screenshots/replay-drift-dark.png) |

### Mobile
The run workspace on a 390 px wide screen.

| Light | Dark |
|---|---|
| <img src="docs/images/screenshots/mobile-run-light.png" alt="Run workspace on mobile — light" width="320"/> | <img src="docs/images/screenshots/mobile-run-dark.png" alt="Run workspace on mobile — dark" width="320"/> |

---

## Project Overview

When a PostgreSQL query is slow, the usual loop is: run `EXPLAIN`, guess at a cause, add an index you *think* will help, time it once, ship it. That last step is where things go wrong. One timing is noise, the index may slow your writes, a "faster" rewrite may quietly return different rows, and a warm cache may explain most of the gain. Generic SQL chatbots make it worse with confident advice and no evidence.

QueryCure behaves like a small team of database performance engineers. It inspects the query, forms hypotheses that each cite evidence, proposes fixes, **measures them in an isolated sandbox**, and lets fixed statistical rules decide the outcome. It is allowed, and expected, to conclude "inconclusive".

**Who it is for:**
- Backend engineers who own a slow endpoint and want a defensible fix, not a guess
- DBAs and SREs who want a second opinion that shows its work
- Teams that need an audit trail: what was claimed, what was measured, and whether it can be re-checked later
- Anyone learning how PostgreSQL plans and statistical benchmarking behave on real data

**Key problems it solves:**

| Problem | QueryCure Solution |
|---|---|
| Confident advice with no source | Every finding cites stored evidence; uncited claims are removed by a claims checker |
| "This should be faster" | Interleaved, repeated measurement with a 95% bootstrap confidence interval |
| Rewrites that change the result | Result rows are fingerprinted; a candidate returning different rows is rejected before speed is considered |
| The model decides | Deterministic Python rules decide; the auditor model can downgrade a verdict, never upgrade it |
| Hidden uncertainty | "Inconclusive" and "no action needed" are first-class outcomes, with reason codes |
| Tools that need write access | Your database is never modified: plain `EXPLAIN` in read-only sessions only |
| A chat log as the only record | A sealed report with digests that can be replayed later |

**At a glance:**

| | |
|---|---|
| **Input** | A SQL query plus its `EXPLAIN (FORMAT JSON)` plan and schema, or a read-only connection for live `EXPLAIN` |
| **Output** | A sealed, replayable report: verified recommendation, unverified recommendation, no action needed, or inconclusive |
| **Shape** | Modular monolith: a Next.js frontend and one Python package running as an `api` and a `worker` process |
| **AI** | LangGraph agents with typed output and cited evidence. Free OpenRouter models, bring your own key |
| **Status** | All five build phases implemented and verified locally. A hosted trial runs privately behind an allowlist |

---

## Key Features

### Multi-Agent Investigation
- **Specialist agents**: Supervisor, Query Analyzer, Index Strategist, Workload Investigator, Optimization Engineer and Benchmark Auditor
- Each agent has one versioned prompt file, one Pydantic output model, an explicit tool allowlist and a call budget
- **Evidence, not assertions**: every claim must cite `evidence_ids`; uncited or contradicted claims are dropped and logged
- **Deterministic materiality gate** decides whether optimizing is worth it at all, so a run can end with "no action needed"
- Prompt-injection fencing: schema names, comments, plan text and query text are treated as untrusted input

### Three Execution Modes
- **Mode A — Offline**: analyze a pasted `EXPLAIN (FORMAT JSON)` plan, SQL and schema. Available everywhere
- **Mode B — Live inspection**: plain `EXPLAIN` through the inspection gateway in a read-only session. Reads catalog and plans only; never executes the query
- **Mode C — Sandbox benchmark**: build candidates and measure them in a disposable clone of a demo workload, in QueryCure's own sandbox

### Human Approval
- The optimization tournament proposes index, rewrite and statistics candidates inside a strict DDL allowlist
- **You approve the exact SQL** and see where it will run before anything executes
- Declining ends the run with an unverified recommendation instead of a guess

### Benchmark Engine (`bench@2`)
- Deterministic, seeded Python: the same configuration reproduces the same schedule
- Per-arm template clones owned by a locked-down `qc_bench` role
- Warm-up, then **interleaved, shuffled blocks** so slow drift hits both arms equally (30 measured runs per arm and parameter set by default)
- Ratio of medians with a percentile bootstrap over 2,000 resamples
- Transport floor (`SELECT 1` round trips) shown next to every result
- Up to two replicate experiments with fresh seeds when results are noisy but promising
- Index size and build time recorded; write overhead marked **unmeasured** instead of guessed

### Verification
- Seven ordered deterministic gates; the first failure sets the verdict and a reason code
- Corroborated regressions only: a confidence interval below the limit rejects only with enough samples and agreeing blocks
- **Verified with noise warning** when replicates agree on noisy hardware, always shown in words
- The database enforces that the auditor can only downgrade

### Reports and Replay
- Sealed Markdown and JSON reports with a manifest digest
- Versioned, frozen builders and renderers keep old reports byte-identical
- **Report replay** (no model, no measurement), **experiment replay** (re-measure in a fresh sandbox) and **AI re-investigation** (a new linked run), never conflated

### Real-Time and Durable
- Progress streams over SSE from a persisted `investigation_events` log
- Reconnects resume from `Last-Event-ID` with nothing lost
- Runs resume from LangGraph checkpoints after a worker restart

### Product
- **Bring your own key**: free OpenRouter models only; keys stored encrypted and shown as their last four characters
- **Prerecorded demo gallery**: real model answers and real sandbox measurements, labeled `prerecorded` everywhere
- **Demo workloads** including traps where the right answer is to change nothing
- Linear-style UI, dark first, with a command palette and keyboard shortcuts; axe accessibility checks in end-to-end runs
- Honest labels everywhere: Observed, Hypothesis, Recommendation, Verified, Rejected, Inconclusive

### Pages in the App

| Page | What it is for |
|---|---|
| **Landing** | Product story and the recorded "X-Ray" result, read from the same recording as the video |
| **Dashboard** | What needs you, what finished, outcomes of the last 25 investigations |
| **New investigation** | Paste a query and plan, analyze offline, or start a full investigation |
| **Run workspace** | Graph, trace, findings, plan explorer, tournament and report tabs for one run |
| **History** | Every investigation and its latest run, with search and filters |
| **Connections** | Add, test and inspect a read-only database connection (Mode B) |
| **Report** | The sealed report with a table of contents, provenance labels and exports |
| **Replay** | Manifest, verify and replay a report, re-run an experiment, attempt history |
| **Demo gallery** | Prerecorded investigations that need no model and no sandbox |
| **Settings** | Save or remove your own LLM key |

---

## Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| **Frontend** | Next.js 16 (App Router) | Web app, landing, sign-in, demo gallery |
| **Language** | TypeScript 5 / Python 3.12 | Typed end to end (`tsc`, `mypy --strict`) |
| **Styling** | Tailwind CSS 4 | Design tokens, light and dark themes |
| **State (server)** | TanStack Query | Server-state caching for the app |
| **Graph view** | React Flow + dagre | Live LangGraph topology in the run workspace |
| **Editor** | CodeMirror 6 | SQL and plan editing |
| **Backend** | FastAPI + Pydantic v2 | REST API, SSE, typed contracts |
| **ORM** | SQLAlchemy 2 (async) + Alembic | Metadata repositories and migrations |
| **Driver** | psycopg 3 | Async Postgres access, `LISTEN/NOTIFY` |
| **SQL parsing** | SQLGlot | SQL validation (defense in depth) |
| **Orchestration** | LangGraph | The only agent orchestrator, with checkpoints |
| **Models** | LangChain, OpenRouter, Gemini | Structured output; free models, BYOK |
| **Database** | PostgreSQL 13–17 | Metadata DB (Neon when hosted); Docker Postgres for sandboxes |
| **Job queue** | PostgreSQL `FOR UPDATE SKIP LOCKED` | Durable jobs without Redis or Celery |
| **Authentication** | Authlib (GitHub, Google, PKCE) | Backend-owned cookie sessions + CSRF token |
| **Logging** | structlog | JSON logs with request, job and run IDs |
| **Metrics** | Prometheus format | Computed from the database |
| **Testing** | pytest, Vitest, Playwright + axe | Unit, real-Postgres integration, security, e2e, recorded-LLM evals |
| **Containers** | Docker Compose | Local, demo and production profiles |
| **Reverse proxy** | Caddy | Single-VM production route |
| **CI** | GitHub Actions | CI and weekly dependency audits |
| **Video** | Remotion | Renders the demo from the recorded run ([`video/`](video/)) |

Rationale for each choice: [DECISIONS](docs/engineering/DECISIONS.md) and the ADRs in [docs/engineering/adr/](docs/engineering/adr/).

---

## System Architecture

```mermaid
flowchart TD
    Browser["Browser\n(Next.js app)"]
    Web["Next.js server\n(proxies /api/v1 on Render)"]
    API["FastAPI API\n/api/v1 + SSE"]
    Worker["Worker\n(LangGraph agents)"]
    Meta["Metadata Postgres\n(users, runs, events,\njobs, artifacts)"]
    LLM["LLM providers\n(OpenRouter / Gemini, BYOK)"]
    Gateway["Inspection gateway\n(plain EXPLAIN, read-only)"]
    Target["Your Postgres\n(target DB, never written)"]
    Sandbox["Sandbox Postgres\n(disposable clones)"]
    OAuth["GitHub / Google OAuth"]

    Browser -->|HTTPS + cookies| Web
    Web --> API
    Browser -->|EventSource| API
    API --> Meta
    API -->|OAuth redirect| OAuth
    Worker -->|claim job SKIP LOCKED| Meta
    Worker -->|events + checkpoints| Meta
    Meta -->|LISTEN / NOTIFY| API
    Worker --> LLM
    Worker --> Gateway
    Gateway --> Target
    Worker -->|approved SQL only| Sandbox
```

QueryCure is a **modular monolith**: `frontend/` (Next.js) and `backend/` (one Python package, two processes). No microservices, no Kubernetes.

| Decision | Why |
|---|---|
| **PostgreSQL is the job queue** | One less moving part than Redis or Celery; durable by construction ([ADR-0004](docs/engineering/adr/ADR-0004-postgres-job-queue.md)) |
| **Persisted events + `LISTEN/NOTIFY` → SSE** | Progress survives reconnects and restarts ([ADR-0005](docs/engineering/adr/ADR-0005-sse-event-log.md)) |
| **LangGraph is the only orchestrator** | Agents exchange Pydantic models; graph state holds references (IDs, hashes), never datasets or credentials |
| **Three databases, never mixed** | Metadata DB (ours), target DB (yours, read-only), sandbox DB (disposable) |
| **Backend owns auth** | The frontend never talks to the metadata database |
| **Deterministic core** | The benchmark engine and verification rules are plain Python; LLMs never compute metrics |

---

## High-Level System Design

```mermaid
flowchart LR
    subgraph Client["Client Layer"]
        App["Next.js App Router\nTanStack Query"]
        ES["EventSource\n(SSE, Last-Event-ID)"]
    end

    subgraph Edge["Edge"]
        Proxy["Caddy (VM) or\nNext.js proxy (Render)"]
    end

    subgraph API["API Process (FastAPI)"]
        Auth["Auth\nsessions · OAuth · CSRF"]
        REST["REST routers\n/api/v1/*"]
        SSE["SSE fan-out\nheartbeat 15 s"]
    end

    subgraph Worker["Worker Process"]
        Graph["LangGraph\nsupervisor + agents"]
        Bench["Benchmark engine\n+ verification rules"]
        Report["Report builder\n+ replay engine"]
    end

    subgraph Data["Data Layer"]
        Meta[("Metadata Postgres\nqueue · events · artifacts")]
        Sandbox[("Sandbox Postgres\ntemplate + clones")]
    end

    subgraph External["External"]
        Models["OpenRouter / Gemini"]
        Target[("Your Postgres\nread-only EXPLAIN")]
        IdP["GitHub / Google"]
    end

    App --> Proxy --> REST
    ES --> Proxy --> SSE
    Auth --> IdP
    REST --> Meta
    SSE --> Meta
    Graph --> Meta
    Graph --> Models
    Graph --> Target
    Bench --> Sandbox
    Report --> Meta
```

---

## Investigation Flow

<div align="center">
<img src="docs/images/investigation-flow.svg" alt="Flow diagram: inputs, specialist agents, materiality gate, human approval, sandbox experiment, fixed-rule verification, sealed report, with early exits for no action needed and unverified recommendation" width="640"/>
</div>

| Step | What happens | Who does it |
|---|---|---|
| **Inspect** | Parse the SQL; collect schema, indexes, statistics and the `EXPLAIN` plan | Deterministic tools |
| **Investigate** | Analyze plan nodes, estimates versus actuals, workload signals | Query Analyzer, Index Strategist, Workload Investigator |
| **Hypothesize** | Ranked root-cause hypotheses, each citing evidence; materiality gate | Supervisor + deterministic gate |
| **Propose** | Index, rewrite and statistics candidates with risks and costs | Optimization Engineer |
| **Approve** | You review the exact SQL and where it will run | You |
| **Benchmark** | Controlled, repeated, interleaved runs in a disposable sandbox | Benchmark Engine (deterministic) |
| **Verify** | Correctness, statistical significance, regressions | Fixed rules first, Benchmark Auditor (downgrade only) second |
| **Report** | Sealed, evidence-backed report with confidence, trade-offs and rollback | Report builder |

If a round ends inconclusive and budget remains, the loop returns to the Optimization Engineer with the reason codes.

**A run ends in exactly one outcome** ([AGENT_SYSTEM §12](docs/architecture/AGENT_SYSTEM.md)):

| Outcome | When |
|---|---|
| `verified_recommendation` | A candidate is verified, audited, and the tournament is complete |
| `no_action_needed` | Nothing actionable, or the materiality gate found nothing material ([ADR-0017](docs/engineering/adr/ADR-0017-deterministic-materiality-gate.md)) |
| `unverified_recommendations` | Candidates exist but the sandbox is unavailable, or every approval was declined |
| `inconclusive` | Every candidate was rejected or inconclusive and the rounds or budget ran out |
| `cancelled` / `failed` | You cancelled, or an unrecoverable error occurred. A partial report is still written |

---

## Agent System

```mermaid
flowchart LR
  I[intake] --> C[collect_context] --> S[supervisor_plan]
  S -->|fan-out| QA[query_analyzer]
  S -->|fan-out| IS[index_strategist]
  S -->|fan-out| WI[workload_investigator]
  QA --> SH[synthesize_hypotheses]
  IS --> SH
  WI --> SH
  SH --> OE[optimization_engineer]
  OE --> AG{approval_gate}
  AG -->|approved| RE[run_experiment]
  RE --> BA[benchmark_auditor]
  BA --> NR{next_round?}
  NR -->|inconclusive, budget left| OE
  NR -->|verified or out of budget| WR[write_report]
  AG -->|declined| WR
```

| Agent | Type | Tools (allowlist) | Output | Runs when |
|---|---|---|---|---|
| **Supervisor** | LLM planning + deterministic router | none (routes only) | `InvestigationPlan`, `HypothesisSet` | Always |
| **Query Analyzer** | LLM + tools | `get_plan_node`, `get_table_stats`, `get_column_stats`, `get_schema_object` | `QueryAnalysis` | A plan or query is available |
| **Index Strategist** | LLM + tools | `list_indexes`, `get_column_stats`, `estimate_index_size` | `IndexAnalysis` | The query touches a base table |
| **Workload Investigator** | LLM + tools | `get_statement_stats`, `get_activity_snapshot`, `get_lock_snapshot`, `get_table_io_stats` | `WorkloadAnalysis` | Live workload capability or an imported snapshot |
| **Optimization Engineer** | LLM | `validate_sql`, `explain_in_sandbox` | `CandidateSet`, `ExperimentSpec` | At least one actionable hypothesis |
| **Benchmark Auditor** | Deterministic rules, then LLM narrative | `get_benchmark_summary`, `get_plan_diff` | `AuditAssessment` | After each experiment |
| Benchmark runner | **Deterministic node** | sandbox + benchmark engine | `ExperimentResult` | After approval |
| Report writer | Deterministic template + flagged LLM prose | none | `InvestigationReport` | Always, last |

**How an agent turn works.** Providers are not asked for native tool calling. Each turn the model returns one JSON object, `call_tool` or `final`, validated against a Pydantic model. QueryCure's code then refuses any tool outside the allowlist, validates arguments, charges the budget, records evidence and an execution row, and returns the result **fenced** as untrusted data. An agent gets at most 14 turns.

**Citations are enforced, not requested.** A claim without `evidence_ids`, or one that contradicts its evidence, is removed. If more than half of an agent's claims are removed, it is retried once. Prompts live in `backend/src/querycure/agents/prompts/`, each with a `PROMPT_VERSION` bumped on every change.

---

## Benchmark Engine

The engine (`bench@2`) is synchronous, deterministic Python; every random choice is seeded ([BENCHMARK_ENGINE](docs/architecture/BENCHMARK_ENGINE.md)).

```mermaid
flowchart LR
    P["Provision\ntemplate + per-arm clones"] --> B["Build\napproved DDL,\nsize + build time"]
    B --> W["Warm up\ndiscarded runs"]
    W --> M["Measure\ninterleaved, shuffled blocks"]
    M --> C["Correctness\nrow fingerprints"]
    C --> S["Statistics\nmedian ratio +\nbootstrap 95% CI"]
    S --> F["Transport floor\nSELECT 1 round trips"]
    F --> R{"Noisy but\npromising?"}
    R -->|yes, up to 2| M
    R -->|no| V["Verdict gates"]
```

Medians and a bootstrap are used because latency is skewed and full of outliers, which breaks means and t-tests. The transport floor is shown next to every result; nothing is subtracted and no verdict reads it.

### Demo Workloads

Mode C runs on deterministic workloads: the same reference always produces byte-identical tables. Several are traps where the right answer is to change nothing.

| Workload | What it teaches |
|---|---|
| `orders_ecommerce` | Orders per customer, newest first, where ten hot customers own 10% of the rows. The classic composite-index win |
| `join_fanout` | A join on an unindexed foreign key with correlated predicates the planner underestimates |
| `stale_stats` | Half the rows loaded after the last `ANALYZE`, so the planner picks a nested loop from a one-row estimate |
| `rewrite_trap` | A `NOT IN` against a list containing `NULL`. A tempting rewrite changes the result |
| `no_benefit` | A small settings table read by primary key. The right answer is "no action needed" |
| `index_regression` | An index that helps common statuses but walks almost the whole index for a rare one (`ORDER BY ... LIMIT` trap) |
| `online_retail_ii` | A real dataset (UCI Online Retail II, CC BY 4.0) loaded as published. The data file is not in this repository |

---

## Verification Rules

<div align="center">
<img src="docs/images/verdict-rules.svg" alt="Seven ordered deterministic gates. The first failing gate sets rejected or inconclusive with a reason code. Passing all gates yields verified within the tested scope. The Benchmark Auditor model may only downgrade to inconclusive." width="640"/>
</div>

**No LLM ever computes a metric**, and no model can turn a `rejected` verdict into anything better. Gates run in order; the first failure sets the verdict and a reason code.

- **Corroborated regressions.** A CI below the regression limit rejects only with at least 20 samples on both arms, no failed baseline sample, at least 3 blocks, and every block ratio below the limit. Otherwise the result is inconclusive.
- **Noise warning.** When a noisy run has no winner but a promising screen, replicates are measured. A candidate all three agree on is reported as **verified with noise warning**, never relabeled plain "verified".

| Label | Meaning |
|---|---|
| **Verified** (within the tested scope) | Faster than the minimum effect, CI clear of noise, same rows. Valid for the recorded dataset, parameters, PostgreSQL version and hardware |
| **Verified with noise warning** | Noisy measurements, but independent experiments agreed |
| **Rejected** | A measured regression, different rows, or a failed build. The reason is named |
| **Inconclusive** | Not enough evidence either way, often laptop noise. No claim is made |
| **Unverified recommendation** | Advice from analysis only; nothing was benchmarked |

---

## Reports and Replay

**What a sealed report contains**

| Section | Content |
|---|---|
| Query | The SQL and the parameter sets tested |
| Problem | Plan evidence and the materiality decision |
| Hypotheses and findings | Each with cited evidence IDs and a "Why?" lineage drawer |
| Rounds and approvals | The exact SQL proposed each round, and what you approved or declined |
| Experiments | Measurements, correctness, build costs, replication and the audit, with evidence IDs and artifact digests |
| Recommendation | Always scoped to the sandbox it was measured in |
| Limitations, next steps, missing evidence | Stated in words, never omitted |
| Provenance and integrity | Models, prompt versions, measured vs prerecorded labels, digests |

Builders and renderers are **versioned and frozen**: a change means a new version ID, never an edit, so old reports stay byte-identical ([ADR-0015](docs/engineering/adr/ADR-0015-canonicalization-finalization-integrity.md)).

**Three kinds of replay, never conflated** ([REPLAY_ENGINE](docs/architecture/REPLAY_ENGINE.md)):

| Kind | What it does | LLM calls | New measurements |
|---|---|---|---|
| **Report replay** | Verifies stored evidence against the manifest and redisplays it | 0 | No |
| **Experiment replay** | Re-executes a stored experiment in a fresh sandbox and compares statistically (±25% drift margin, [ADR-0023](docs/engineering/adr/ADR-0023-d9-experiment-replay-equivalence-margin.md)) | 0 | Yes, as a new linked run |
| **AI re-investigation** | A new LLM run on the same inputs, with consent, its own budget and a parent link | Yes | If it benchmarks |

Replay proves **consistency against stored digests, not authenticity**.

---

## Folder Structure

```
QueryCure/
├── backend/                     ← One Python package, two processes (api + worker)
│   ├── src/querycure/
│   │   ├── api/                 ← FastAPI app, routers, SSE
│   │   ├── agents/              ← LangGraph graph, nodes, tools, versioned prompts, budgets
│   │   ├── benchmark/           ← Deterministic stats, schedule, correctness, verdict rules
│   │   ├── sandbox/             ← Disposable sandbox provisioning (Mode C)
│   │   ├── connectors/          ← Inspection gateway: allowlisted read-only access (Mode B)
│   │   ├── audit/               ← Benchmark Auditor (downgrade-only)
│   │   ├── reports/ replay/     ← Sealed reports, builders, renderers, replay engine
│   │   ├── evidence/ events/    ← Evidence IDs and the persisted event log
│   │   ├── jobs/ worker/        ← Postgres job queue and the worker process
│   │   ├── sql/ plans/          ← SQLGlot validation, EXPLAIN plan parsing
│   │   ├── llm/ auth/ db/ core/ ← Providers, sessions, repositories, errors
│   │   └── workloads/ demo/     ← Demo workloads and the prerecorded gallery
│   ├── migrations/              ← Alembic revisions
│   ├── tests/                   ← unit / integration / security / rehearsal
│   └── evals/                   ← Recorded-LLM eval cases and measurement fixtures
├── frontend/                    ← Next.js app (landing, sign-in, demo gallery, app)
│   ├── src/                     ← app / components / lib / styles
│   └── e2e/                     ← Playwright + axe
├── infra/docker/                ← compose.yaml (local), compose.demo.yaml, compose.prod.yaml
├── video/                       ← Remotion source for the demo video
└── docs/                        ← Product, architecture, design, planning, ADRs, reports
    └── images/                  ← Diagrams and screenshots
```

---

## Database Schema

Three databases with three owners, never mixed ([DATABASE_DESIGN](docs/architecture/DATABASE_DESIGN.md)):

| Database | Owner | Purpose | Access path | Lifecycle |
|---|---|---|---|---|
| **Metadata DB** | QueryCure | Users, investigations, events, artifacts, evidence, jobs, checkpoints | SQLAlchemy async repositories | Persistent |
| **Target DB** | You | Read-only inspection (Mode B) | The inspection gateway only | Never written to |
| **Sandbox DB** | QueryCure (ephemeral) | Benchmark clones (Mode C) | `sandbox` and `benchmark` modules | Template per workload; clones dropped after each experiment |

```mermaid
erDiagram
  users ||--o{ database_connections : owns
  users ||--o{ llm_credentials : owns
  users ||--o{ investigations : owns
  investigations ||--o{ investigation_runs : has
  investigation_runs ||--o{ investigation_events : emits
  investigation_runs ||--o{ agent_executions : records
  agent_executions ||--o{ tool_executions : records
  investigation_runs ||--o{ evidence : collects
  artifacts ||--o{ evidence : "sourced from"
  investigation_runs ||--o{ hypotheses : proposes
  investigation_runs ||--o{ optimization_candidates : proposes
  investigation_runs ||--o{ approval_requests : requires
  investigation_runs ||--o{ experiments : runs
  experiments ||--o{ benchmark_runs : measures
  optimization_candidates ||--o{ benchmark_runs : "arm of"
  experiments ||--o{ verification_results : produces
  investigation_runs ||--o| investigation_reports : produces
  investigation_runs ||--o| replay_manifests : produces
  investigation_runs ||--o{ replay_attempts : "replayed by"
  jobs }o--|| investigation_runs : drives
```

### Key Design Decisions

- **UUID primary keys** generated with `uuid_generate_v4()`
- **`TEXT` not `VARCHAR`**, **`TIMESTAMPTZ`** in UTC everywhere
- **Soft deletes** via `created_at` / `updated_at` / `deleted_at`
- **No foreign-key constraints**: integrity is enforced in repositories ([ADR-0006](docs/engineering/adr/ADR-0006-metadata-schema-conventions.md))
- **Immutable, content-addressed artifacts** keyed by SHA-256
- **Least-privilege roles**: the API runs as `qc_app`; only `qc_retention` may `DELETE`; migrations run as the owner from an operator machine

---

## Authentication Flow

The backend owns authentication ([ADR-0013](docs/engineering/adr/ADR-0013-auth-strategy.md)): opaque session tokens, stored hashed, in `HttpOnly` cookies. That works with SSE (an `EventSource` cannot set headers) and lets a session be revoked instantly by deleting its row.

```mermaid
sequenceDiagram
  autonumber
  participant B as Browser
  participant A as API
  participant P as GitHub / Google
  participant D as Metadata Postgres

  B->>A: GET /auth/{provider}/login
  A-->>B: 302 to provider (state + PKCE S256)
  B->>P: Authorize
  P-->>B: 302 back with code
  B->>A: GET /auth/{provider}/callback?code&state
  A->>P: Exchange code (PKCE verifier)
  P-->>A: Identity
  A->>D: Upsert user by (provider, subject)
  opt RESTRICTED_ACCESS=true
    A->>A: Check verified email against ACCESS_ALLOWLIST
  end
  A->>D: Create session (token stored hashed)
  A-->>B: Set-Cookie qc_session (HttpOnly) and qc_csrf, 302 to the app
```

**Session details:**
- **Local profile**: a single local user and anonymous demo sessions, so you can try the app with no sign-in
- **Providers**: GitHub and Google, each enabled by its own client ID and secret. Accounts are keyed by `(auth_provider, auth_subject)` and never merged by email
- **CSRF**: double-submit token; state-changing requests echo the `qc_csrf` cookie in a header
- **Restricted trial**: with `RESTRICTED_ACCESS=true` there are no anonymous sessions and only allowlisted, provider-verified emails can sign in ([ADR-0031](docs/engineering/adr/ADR-0031-restricted-access-email-allowlist.md))
- **Same-site cookies**: cookies are `SameSite=Lax`, so production serves the web app and API on the same site, or the web app proxies `/api/v1/*`

---

## Real-Time Architecture

Progress is an **append-only event log**, not an in-memory stream, so a dropped connection loses nothing.

```mermaid
sequenceDiagram
  autonumber
  participant B as Browser
  participant A as API (FastAPI)
  participant D as Metadata Postgres
  participant W as Worker (LangGraph)
  participant L as LLM provider

  B->>A: POST /investigations
  A->>D: Insert run + enqueue job
  A-->>B: Run ID
  B->>A: GET /runs/{id}/events (SSE)
  W->>D: Claim job (FOR UPDATE SKIP LOCKED, lease)
  loop Each agent node
    W->>L: Typed prompt (BYOK)
    L-->>W: Structured, cited output
    W->>D: Persist event (seq) + checkpoint
    D-->>A: NOTIFY
    A-->>B: SSE event
  end
  Note over B,A: On reconnect: Last-Event-ID → only missed events
  W->>D: Seal report + digests
  A-->>B: Run completed
```

- Each event gets a per-run sequence number in `investigation_events`
- A reconnecting browser sends `Last-Event-ID` (or `?after_seq=`) and receives exactly what it missed
- A 15-second heartbeat keeps proxies from closing idle streams
- `GET /runs/{run_id}/events/history` returns the same log as JSON for the trace view
- **Durability**: jobs are claimed with a lease. A stopping worker finishes in-flight jobs for a grace period (20 s by default), then abandons them to lease expiry; the next worker resumes from the last LangGraph checkpoint. Every 5 minutes the worker logs `stuck_work_detected` for expired leases

---

## API Reference

Base path `/api/v1`. Timestamps are ISO 8601 UTC. JSON on the wire is `snake_case`; the frontend converts to `camelCase` in its API client only. Interactive docs at `/api/v1/docs`, schema at `/api/v1/openapi.json`. Errors use one envelope: `{"error": {"code", "message", "status", "details"}}` ([API_DESIGN](docs/architecture/API_DESIGN.md)).

### Session and Auth — `/auth`, `/session`, `/me`

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/auth/options` | Which sign-in methods are on, and whether access is restricted |
| `POST` | `/session` | Start a local or anonymous session |
| `GET` | `/me` | Current user, profile and feature flags |
| `POST` | `/auth/logout` | End the session |
| `GET` | `/auth/{github,google}/login` | Begin OAuth |
| `GET` | `/auth/{github,google}/callback` | Finish OAuth |

### Investigations — `/investigations`

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/investigations` | Create an investigation and its first run |
| `GET` | `/investigations` | List, newest first |
| `GET` | `/investigations/{id}` | Read one |
| `DELETE` | `/investigations/{id}` | Soft delete |
| `POST` | `/investigations/{id}/restore` | Restore a soft-deleted one |
| `POST` | `/investigations/{id}/reinvestigate` | Start another run |

### Runs — `/runs`

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/runs/{run_id}` | Run state, outcome, budget and usage |
| `POST` | `/runs/{run_id}/cancel` | Cancel a run |
| `GET` | `/runs/{run_id}/events` | Live SSE stream |
| `GET` | `/runs/{run_id}/events/history` | The same events as JSON |
| `GET` | `/runs/{run_id}/findings` | Cited findings and hypotheses |
| `GET` | `/runs/{run_id}/plans` | Plans collected for the run |
| `GET` | `/runs/{run_id}/plans/diff` | Baseline versus candidate plan diff |
| `GET` | `/runs/{run_id}/evidence/{evidence_id}` | One evidence record |
| `GET` | `/artifacts/{sha256}` | An immutable artifact by digest |

### Optimization and Approvals

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/runs/{run_id}/candidates` | Proposed optimization candidates |
| `GET` | `/runs/{run_id}/approvals` | Pending and decided approvals |
| `POST` | `/approvals/{approval_id}/decision` | Approve or decline the exact SQL |

### Experiments and Verification

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/runs/{run_id}/experiments` | Experiments for a run |
| `GET` | `/experiments/{experiment_id}` | One experiment and its measurements |
| `GET` | `/runs/{run_id}/verifications` | Verdicts and the Benchmark Auditor panel |

### Reports and Replay

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/runs/{run_id}/report` | Stored report |
| `GET` | `/runs/{run_id}/report.md` | Markdown export with a digest footer |
| `GET` | `/runs/{run_id}/report.json` | JSON export |
| `GET` | `/runs/{run_id}/replay/manifest` | The replay manifest |
| `POST` | `/runs/{run_id}/replay/report` | Verify the stored report against its digests |
| `POST` | `/experiments/{experiment_id}/replay` | Re-measure an experiment |
| `GET` | `/runs/{run_id}/replay/attempts` | Replay history for a run |
| `GET` | `/replay-attempts/{attempt_id}` | One attempt |
| `POST` | `/replay-attempts/{attempt_id}/cancel` | Cancel a running attempt |

### Inspection — `/inspect`

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/inspect/sql` | Parse and validate SQL |
| `POST` | `/inspect/plan` | Analyze a pasted `EXPLAIN` JSON plan (Mode A) |
| `POST` | `/inspect/schema` | Parse a pasted schema |

### Connections — `/connections`

| Method | Path | Purpose |
|---|---|---|
| `GET` `POST` | `/connections` | List or add a connection |
| `DELETE` | `/connections/{id}` | Remove a connection |
| `POST` | `/connections/{id}/test` | Test connectivity |
| `GET` | `/connections/{id}/schema` | Read the catalog (fixed, parameterized queries) |
| `POST` | `/connections/{id}/explain` | Plain `EXPLAIN` through the gateway (Mode B) |
| `GET` | `/workloads` | The demo workloads |

### Demo Gallery — `/demo`

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/demo/gallery` | Prerecorded investigations |
| `GET` | `/demo/gallery/{slug}` | One recording |
| `GET` | `/demo/gallery/{slug}/verification` | Verify its digests |

### Settings — `/settings`

| Method | Path | Purpose |
|---|---|---|
| `GET` `POST` | `/settings/llm-credentials` | List or save your key (encrypted; shown as last four characters) |
| `DELETE` | `/settings/llm-credentials/{id}` | Remove a key |
| `GET` | `/settings/models` | Allowed free models |

### Health and Metrics

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/healthz` | Liveness |
| `GET` | `/readyz` | Database reachable and migrations current |
| `GET` | `/internal/metrics` | Prometheus-format metrics (bearer `METRICS_TOKEN`) |

---

## Environment Variables

### Backend (`backend/.env`)

See `backend/.env.example`. In production, use the host's secret store. **Never commit real values.**

| Variable | Purpose |
|---|---|
| `QC_PROFILE` | `local` or `demo` (the restricted public configuration) |
| `DATABASE_URL` | Metadata DB (pooled), as the restricted `qc_app` role |
| `DATABASE_URL_DIRECT` | Metadata DB (direct), for `LISTEN/NOTIFY` and the worker, as `qc_app` |
| `DATABASE_MIGRATION_URL` | Owner role, only for migrations from an operator machine. Never on the app host |
| `DATABASE_RETENTION_URL` | The one role allowed to `DELETE`; ops commands only |
| `QC_MASTER_KEY` | 32 random bytes, base64. Encrypts stored keys and connection passwords. Keep an offline copy |
| `QC_MASTER_KEY_VERSION` | Key version, for rotation |
| `METRICS_TOKEN` | At least 32 characters; protects `/internal/metrics` |
| `WORKER_MODE` | `embedded` (worker inside the API process) or `separate` |
| `FEATURE_SANDBOX` | Live sandbox benchmarking on or off |
| `FEATURE_LIVE_INSPECTION_PUBLIC` | Live inspection (Mode B) for hosted users |
| `ALLOW_PRIVATE_TARGETS` | Allow loopback and private connection targets (local only) |
| `RESTRICTED_ACCESS` / `ACCESS_ALLOWLIST` | Private trial switch and the JSON list of allowed emails |
| `CORS_ORIGINS` / `COOKIE_DOMAIN` | Browser origins and session-cookie scope |
| `PUBLIC_API_URL` / `WEB_BASE_URL` | Public origins of the API and the web app |
| `TRUSTED_PROXY_HOPS` | How many proxies append to `X-Forwarded-For` |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | GitHub OAuth (set together) |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Google OAuth (set together) |
| `LLM_PROVIDER` / `LLM_MODEL` / `LLM_FALLBACK_MODEL` | Provider and pinned free model. `stub` is local only |
| `OPENROUTER_API_KEY` | Local-profile key; hosted users bring their own |
| `LLM_DAILY_REQUEST_LIMIT` / `LLM_REQUESTS_PER_MINUTE` / `LLM_MAX_CONCURRENCY` | Rate and budget limits |
| `SANDBOX_ADMIN_URL` / `SANDBOX_BENCH_PASSWORD` | Local sandbox provisioning (never on a hosted API) |
| `LOG_LEVEL` | Log verbosity |

### Frontend (`frontend/.env`)

| Variable | Purpose |
|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | API origin, compiled into the bundle and the CSP, so set it **before** `pnpm build` |
| `BACKEND_ORIGIN` | Render route only: origin Next proxies `/api/v1/*` to (set for build and run) |
| `BACKEND_PROXY_TIMEOUT_MS` | Optional idle timeout for that proxy |

---

## Local Development

### Prerequisites

- Docker with Compose v2
- [uv](https://docs.astral.sh/uv/) (installs Python 3.12 if needed)
- Node.js 22
- pnpm 10 (`corepack enable` provides the pinned version)
- A free [OpenRouter](https://openrouter.ai/) key for real investigations (optional: a `stub` model works without one)

### Setup

```bash
# 1. Clone the repository
git clone https://github.com/yuvrajsatyapal/QueryCure.git
cd QueryCure

# 2. Start the metadata DB (127.0.0.1:5432) and the sandbox DB (internal network)
#    Dev-only passwords; the first start also creates the restricted qc_app role
docker compose -f infra/docker/compose.yaml up -d --wait

# 3. Configure the backend
cp backend/.env.example backend/.env
# Generate a master key and paste it after QC_MASTER_KEY= in backend/.env:
python3 -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
# Optional: put your free key after OPENROUTER_API_KEY= (or save it later in Settings)

# 4. Install backend dependencies and run migrations (as the owner role)
cd backend && uv sync && uv run alembic upgrade head

# 5. Start the API (runs as qc_app)
uv run uvicorn querycure.api.main:app --port 8000
# curl http://localhost:8000/api/v1/readyz → {"status":"ok","database":"ok","migrations":"current"}

# 6. In a second terminal: start the web app
cd frontend && pnpm install && pnpm dev
# Open http://localhost:3000/app — a local session is created automatically

# 7. In a third terminal: start the worker (needed for investigations)
cd backend && uv run python -m querycure.worker
```

> To try the UI with no model at all, start the API and worker with `LLM_PROVIDER=stub` (canned, labeled output, local profile only). That is how the screenshots above were produced.

**First investigation.** Go to **New investigation**, paste the output of `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) …` and choose **Analyze plan**. Real example plans are in `backend/tests/fixtures/plans/pg17_*.json`. Then start an investigation: the timeline streams live, and every finding links to the plan node it cites. Free models are slow (a few minutes per run) and limited to about 50 requests per day.

**Demo gallery.** Open <http://localhost:3000/demo>. It needs no model and no sandbox.

<details>
<summary><b>Optional: live <code>EXPLAIN</code> against a demo database</b></summary>

```bash
docker compose -f infra/docker/compose.yaml exec metadata-db psql -U qc_owner -d querycure -c "CREATE DATABASE qc_demo_orders"
```

```bash
cd backend && uv run python -m querycure.workloads postgresql://qc_owner:qc_local_dev_only@127.0.0.1:5432/qc_demo_orders 'orders_ecommerce@v1:sf=0.1:seed=42'
```

```bash
docker compose -f infra/docker/compose.yaml exec metadata-db psql -U qc_owner -d qc_demo_orders -c "CREATE ROLE qc_demo_inspector LOGIN PASSWORD 'demo_inspector_local_only'; GRANT CONNECT ON DATABASE qc_demo_orders TO qc_demo_inspector; GRANT USAGE ON SCHEMA public TO qc_demo_inspector; GRANT SELECT ON ALL TABLES IN SCHEMA public TO qc_demo_inspector; GRANT pg_read_all_stats TO qc_demo_inspector;"
```

In **Connections**, add host `127.0.0.1`, port `5432`, database `qc_demo_orders`, user `qc_demo_inspector`, password `demo_inspector_local_only`, and set **TLS** to `disable (local only)`. Choose **Test**, then use the **Live EXPLAIN** tab:

```sql
SELECT * FROM orders WHERE customer_id = 1024 ORDER BY created_at DESC LIMIT 20
```

It runs plain `EXPLAIN` only, so nothing is executed.

</details>

### Development Commands

| Command | What it does |
|---|---|
| `uv run ruff check . && uv run ruff format --check .` | Backend lint and format check |
| `uv run mypy src` | Backend strict type check |
| `uv run pytest -q` | Backend unit tests |
| `uv run pytest tests/integration -q` | Real-Postgres integration tests (needs the compose databases) |
| `uv run pytest tests/security -q` | Negative tests for every security control |
| `pnpm lint && pnpm typecheck && pnpm test` | Frontend ESLint, `tsc` and Vitest |
| `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 pnpm build` | Production frontend build |
| `pnpm exec playwright test` | End-to-end tests with axe accessibility checks |

---

## Production Deployment

Hosting is deliberately small: one always-on container for the API (with the embedded worker), one for the web app, and managed Postgres ([DEPLOYMENT](docs/architecture/DEPLOYMENT.md)). Migrations run as a separate release step before new API instances start, and stay backward compatible with the previous version (expand, migrate, contract).

### Option A — Single VM (Docker Compose + Caddy)

`infra/docker/compose.prod.yaml` with a Caddy reverse proxy and a guarded release script. Configuration starts from `infra/docker/env.prod.example`.

### Option B — Render (API + web) + Neon (database)

A Docker web service for the API and a Node web service for Next.js that proxies `/api/v1/*` to it.

| Service | Setting | Value |
|---|---|---|
| API (Docker) | Root directory | `backend` |
| | Start command | `uvicorn querycure.api.main:app --host 0.0.0.0 --port $PORT` |
| | Health check | `/api/v1/healthz` |
| | Must set | `QC_PROFILE=demo`, `WORKER_MODE=embedded`, `FEATURE_SANDBOX=false`, `DATABASE_URL`, `DATABASE_URL_DIRECT`, `QC_MASTER_KEY`, `METRICS_TOKEN`, origins |
| | Must not set | `DATABASE_MIGRATION_URL`, `DATABASE_RETENTION_URL`, `SANDBOX_*` |
| Web (Node) | Root directory | `frontend` |
| | Build | `corepack enable && pnpm install --frozen-lockfile && pnpm build` |
| | Start | `pnpm start` |
| | Must set | `NEXT_PUBLIC_API_BASE_URL` (its own origin), `BACKEND_ORIGIN` (the API origin) |

After deploying, `GET /api/v1/readyz` should return `database: ok` and `migrations: current`.

### Option C — Restricted Public-Demo Profile (locally)

The configuration a public deployment uses: anonymous sessions, BYOK only, strict rate limits, no live sandbox, no live inspection, plus the gallery. The API runs with an embedded worker.

```bash
export QC_MASTER_KEY=$(python3 -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())")
docker compose -f infra/docker/compose.demo.yaml up --build
# Web on http://localhost:3300, API on :8300
# Stop with: docker compose -f infra/docker/compose.demo.yaml down -v
```

Hosted deployments run the demo profile with an access allowlist, so the sign-in page shows **Private trial · approved accounts only**. Pre-release checks: [RELEASE_CHECKLIST](docs/engineering/RELEASE_CHECKLIST.md).

---

## Security

QueryCure runs LLM-authored SQL, so the boundary is enforced in the database, not in a prompt. Full threat model: [SECURITY](docs/architecture/SECURITY.md).

### Database Access
- **The LLM never receives a database client.** All access goes through the inspection gateway (Mode B) or the sandbox module (Mode C), using allowlisted operations
- **Mode B is plain `EXPLAIN (FORMAT JSON)` only**: never `EXPLAIN ANALYZE`, never DDL or DML
- Every session is read-only and sets `statement_timeout`, `lock_timeout` and `idle_in_transaction_session_timeout`; superuser connections are refused
- **Catalog and statistics queries are fixed, parameterized templates** in code
- **SQLGlot validation is defense in depth, not the boundary**: database-side controls stay on even when the parser agrees

### Least-Privilege Roles
- The API runs as `qc_app`, retention as `qc_retention`, migrations as the owner
- Sandbox work runs as `qc_bench`: no superuser, no `CREATEDB`, no file or program access

### Untrusted Input
- **Prompt-injection fencing**: schema names, comments, plan text and query text are fenced as untrusted data in prompts
- Tool results are returned to agents fenced, and tools outside an agent's allowlist are refused in code

### Network and Secrets
- **SSRF guard**: connection targets are resolved, checked and pinned to a `hostaddr` before connecting
- Credentials and API keys are never logged or placed in graph state, and are redacted by helpers
- Stored LLM keys and connection passwords are encrypted with `QC_MASTER_KEY`

### Human in the Loop
- You approve every sandbox statement, and the approval shows the exact SQL

### Supported and Not Supported

| Supported | Not supported (yet) |
|---|---|
| PostgreSQL 13–17 JSON plans; single `SELECT` statements | DML and DDL analysis; text-format plans |
| Offline analysis (Mode A) everywhere | Live inspection (Mode B) on a public demo |
| Live `EXPLAIN` (Mode B) on a local install | `EXPLAIN ANALYZE` on your database (never) |
| Sandbox benchmarking (Mode C) of the demo workloads, locally | Benchmarks on your own data |
| Free OpenRouter models with your own key | Paid models (refused by design, [ADR-0016](docs/engineering/adr/ADR-0016-free-openrouter-models-only.md)) |
| Anonymous sessions, GitHub and Google sign-in, allowlist | Teams, sharing, admin roles |

---

## Reliability and Budgets

Every run is bounded. Counters live in the database, not in graph state, so parallel branches share one budget with no races and counts survive a crash. Each LLM or tool call is also a cancellation point.

| Budget | Local default | Hosted demo |
|---|---|---|
| LLM calls per run | 40 | 20 |
| Tokens per run | 400k | 150k |
| Tool calls per run | 80 | 40 |
| Tool calls per agent invocation | 8 | 6 |
| Run wall clock | 20 min | 5 min |
| Candidates per round | 4 | 3 |
| Extra optimization rounds | 2 | 1 |
| Concurrent runs per user | 2 | 1 |

When a budget runs out the run routes to `write_report`, which always runs, so cancelled and exhausted runs still produce a partial report with missing sections labeled.

| Failure | Behavior |
|---|---|
| Provider rate limit, 5xx or timeout | Exponential backoff with jitter, then the fallback model if configured |
| Invalid structured output | Re-prompt with the validation errors once, then one attempt on the fallback model |
| A model keeps failing | A circuit breaker skips it for the run |
| Uncited or contradicted claim | The claim is removed, never retried into existence |
| Sandbox benchmark failure | Experiment marked failed and candidates inconclusive, after one re-provision |
| Auditor skipped or crashed | Verified candidates with no audit row are downgraded to inconclusive (`audit_not_completed`) |
| Worker stopped mid-run | The lease expires and the next worker resumes from the checkpoint |

---

## Observability

| Channel | What you get |
|---|---|
| **Logs** | structlog JSON with request, job and run correlation IDs on every line. Credentials and prompts are redacted |
| **Metrics** | Prometheus format, computed from the database, at `/api/v1/internal/metrics` behind a bearer `METRICS_TOKEN` |
| **In the product** | The trace and graph views read the same persisted events the worker wrote |

Metrics include run outcomes and duration, LLM calls, tokens and latency per agent, tool calls by status, structured-output repairs, citations removed, queue depth, expired leases, benchmark coefficient of variation, blocked security attempts, replay attempts by failure code, and open SSE connections. Details: [OBSERVABILITY](docs/engineering/OBSERVABILITY.md).

---

## Testing

- **Strict typing and formatting**: `mypy --strict`, `ruff`, ESLint and `tsc` are all gates
- **TDD for deterministic logic**: parsers, validators, statistics and state transitions are written test first
- **Every security control has a negative test** in `backend/tests/security/`
- **Real Postgres in integration tests**: no mocked database for repository or benchmark behavior
- **Evals without cost**: agent changes need an eval case or updated recorded fixture in `backend/evals/`; recorded runs replay with no model calls
- **Accessibility**: Playwright runs axe against the key screens in both themes

Strategy: [TESTING_STRATEGY](docs/engineering/TESTING_STRATEGY.md).

---

## Project Workflow

```mermaid
flowchart LR
    subgraph Setup
        A["Open the app\n(local session or sign in)"] --> B["Save a free\nOpenRouter key"]
        B --> C["Optional: add a\nread-only connection"]
    end

    subgraph Investigate
        C --> D["Paste query +\nEXPLAIN plan"]
        D --> E["Agents collect\ncited evidence"]
        E --> F["Ranked hypotheses\n+ materiality gate"]
    end

    subgraph Prove
        F --> G["Review candidates\n+ approve exact SQL"]
        G --> H["Sandbox benchmark\ninterleaved runs"]
        H --> I["Deterministic\nverdict + audit"]
    end

    subgraph Keep
        I --> J["Sealed report\nMarkdown / JSON"]
        J --> K["Replay later\nreport or experiment"]
    end
```

---

## CI / CD

GitHub Actions runs on every push to `main` and every pull request.

```
ci.yml
  ├── backend              (Python 3.12 and 3.13)
  │   ├── ruff check + format check
  │   ├── mypy --strict
  │   └── unit tests
  ├── backend-integration  (postgres:17 service containers)
  │   ├── integration tests
  │   ├── security tests
  │   └── recorded evals (no model calls)
  ├── frontend
  │   ├── lint + typecheck
  │   ├── Vitest
  │   ├── production build
  │   └── build both demo images
  └── e2e
      └── Playwright + axe with the stub model

audit.yml   (Mondays, manual, and PRs or pushes touching a lockfile)
  ├── pip-audit   backend runtime dependencies
  └── pnpm audit  frontend dependencies
```

Deployment is manual: migrations run as a separate release step before new API instances start.

---

## Roadmap

Post-MVP candidates, in priority order ([ROADMAP](docs/planning/ROADMAP.md)):

1. Write-overhead micro-benchmark, so index cost on inserts and updates is measured instead of marked unmeasured
2. AI re-investigation with a conclusion diff against the original run
3. HypoPG pre-screen to rank index candidates before building them
4. Grounded Q&A over a finished investigation
5. Shareable read-only reports
6. Text-format plans and `pg_stat_statements` CSV import

| Phase | Theme | Status |
|---|---|---|
| 0 | Documentation and architecture | Done |
| 1 | Foundation: repo, API, metadata DB, SQL and plan parsing, demo workloads, editor | Done ([report](docs/planning/reports/PHASE_1_REPORT.md)) |
| 2 | Multi-agent intelligence: LangGraph supervisor, analyzer agents, streaming | Implemented ([report](docs/planning/reports/PHASE_2_REPORT.md)) |
| 3 | Optimization and benchmarking: sandbox, benchmark engine, tournament | Implemented ([report](docs/planning/reports/PHASE_3_REPORT.md)) |
| 4 | Verification and replay: auditor, lineage, replay, regression detection | Implemented ([report](docs/planning/reports/PHASE_4_REPORT.md)) |
| 5 | Production polish: auth, BYOK, hardening, demo gallery, operations, deployment | Implemented and verified locally ([report](docs/planning/reports/PHASE_5_REPORT.md)) |

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

## Honesty Policy

- QueryCure never fabricates benchmark numbers. Example numbers in the docs are illustrative only
- Prerecorded demo benchmarks are always labeled as such and never presented as measurements of your database
- **"Verified" always means "verified within the tested scope"**: dataset, parameters, PostgreSQL version and hardware are recorded with the result
- Report replay proves *consistency against stored digests*, not authenticity. It is never described as tamper-proof or certified
- The screenshots in this README come from automated tests that use a stub model and seeded fixtures, and say so

---

## License

MIT License — see [LICENSE](./LICENSE) for details. Copyright (c) 2026 Yuvraj Satyapal.
