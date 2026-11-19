
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

[Overview](#1-overview) · [How it works](#2-how-it-works) · [Architecture](#3-architecture) · [Reference](#4-reference) · [Run it](#5-run-it) · [Project](#6-project)

<br/>

https://github.com/user-attachments/assets/8c922fb2-9036-4358-9abb-4b55c7fae05e

<sub>One recorded PostgreSQL 17.11 run on a synthetic 2,000,000-row table, not a promise for your workload. Every number in the video is read from the recording the landing page uses, not typed in by hand.</sub>

</div>

---

## Contents

**[1. Overview](#1-overview)**
[At a glance](#at-a-glance) · [The problem](#the-problem) · [What QueryCure does](#what-querycure-does) · [How it differs](#how-it-differs-from-a-sql-optimizer-or-chatbot) · [Key features](#key-features) · [Screenshots](#screenshots)

**[2. How it works](#2-how-it-works)**
[An investigation, step by step](#an-investigation-step-by-step) · [The agents](#the-agents) · [Execution modes](#execution-modes) · [Benchmark method](#benchmark-method) · [How verdicts are decided](#how-verdicts-are-decided) · [Reading the results](#reading-the-results) · [Reports and replay](#reports-and-replay) · [Demo workloads](#demo-workloads)

**[3. Architecture](#3-architecture)**
[Technology stack](#technology-stack) · [System architecture](#system-architecture) · [Project structure](#project-structure) · [Database design](#database-design) · [Authentication flow](#authentication-flow) · [Real-time architecture](#real-time-architecture) · [Observability](#observability) · [Reliability and budgets](#reliability-and-budgets)

**[4. Reference](#4-reference)**
[API reference](#api-reference) · [Environment variables](#environment-variables) · [Security model](#security-model) · [Supported and not supported](#supported-and-not-supported)

**[5. Run it](#5-run-it)**
[Run locally](#run-locally) · [Testing and quality](#testing-and-quality) · [CI/CD](#cicd) · [Deployment](#deployment)

**[6. Project](#6-project)**
[Development phases](#development-phases) · [Roadmap](#roadmap) · [FAQ](#faq) · [Documentation](#documentation) · [Honesty policy](#honesty-policy) · [License](#license)

---

# 1. Overview

## At a glance

| | |
|---|---|
| **What it is** | A web app and backend that investigates a slow PostgreSQL query, proposes fixes, and measures them before recommending anything |
| **Input** | A SQL query, its `EXPLAIN (FORMAT JSON)` plan and schema, or a read-only connection for live `EXPLAIN` |
| **Output** | A sealed, replayable report with one of four outcomes: verified recommendation, unverified recommendation, no action needed, or inconclusive |
| **Shape** | Modular monolith: a Next.js frontend, plus one Python package that runs as an API process and a worker process |
| **AI** | LangGraph agents with typed output and cited evidence. Free OpenRouter models, bring your own key |
| **Measurement** | Deterministic Python. No language model ever computes a metric |
| **Your data** | Never modified. AI-written SQL runs only in disposable sandbox clones, after you approve the exact SQL |
| **Status** | All five build phases implemented and verified locally. The API is deployable; a hosted trial is private and allowlisted |
| **License** | MIT |

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

**Who it is for**

- Backend engineers who own a slow endpoint and want a defensible fix, not a guess.
- DBAs and SREs who want a second opinion that shows its work.
- Teams that need an audit trail: what was claimed, what was measured, and whether it can be re-checked later.
- Anyone learning how PostgreSQL plans and statistical benchmarking behave on real data.

## How it differs from a SQL optimizer or chatbot

| | Typical chatbot or auto-tuner | QueryCure |
|---|---|---|
| **Claims** | Confident advice, no source | Every finding cites stored evidence; uncited claims are removed |
| **Proof** | "This should be faster" | Interleaved, repeated measurement with a confidence interval |
| **Correctness** | Rarely checked | A candidate that returns different rows is rejected before speed is considered |
| **Who decides** | The model | Deterministic rules. The auditor model can downgrade, never upgrade |
| **Uncertainty** | Hidden | "Inconclusive" is a first-class outcome, with reason codes |
| **Your database** | Often needs write access | Never modified; plain `EXPLAIN` in read-only sessions |
| **Afterwards** | A chat log | A sealed report with digests that can be replayed |

## Key features

### Investigation
- **Evidence, not assertions.** Every finding cites stored evidence (plan nodes, statistics, measurements). Uncited claims fail validation, are retried once, then dropped and logged.
- **Specialist agents with typed output.** Query Analyzer, Index Strategist, Workload Investigator and Optimization Engineer each have one prompt file, one Pydantic output model, a tool allowlist and a call budget.
- **Deterministic materiality gate.** A fixed check decides whether optimizing is worth it at all, so a run can end with "no action needed".
- **Live and resumable.** Progress streams over SSE from a persisted event log, and runs resume from LangGraph checkpoints after a restart.

### Measurement
- **Interleaved, repeated benchmarks.** Baseline and candidate run in alternating blocks in a sandbox clone, so drift hits both arms equally.
- **Correctness first.** A candidate that returns different rows is rejected before its speed is even considered.
- **Honest statistics.** Bootstrap confidence intervals, a minimum effect, a regression limit, a noise screen and corroborated replicates.
- **"Inconclusive" is a valid answer.** On noisy hardware most honest benchmarks end inconclusive, and the report says so.

### Trust and control
- **You approve every sandbox statement.** The approval dialog shows the exact SQL and where it will run.
- **Rules decide, models advise.** The Benchmark Auditor can downgrade a verdict, never upgrade one, and the database enforces that.
- **Your database is never modified.** Live inspection is plain `EXPLAIN` in read-only sessions.
- **Sealed and replayable reports.** Reports are stored with digests. Report replay re-checks them without a model, and experiment replay re-measures them.

### Product
- **Bring your own key.** Free OpenRouter models only. Keys are stored encrypted and shown only as their last four characters.
- **Prerecorded demo gallery.** Real model answers and real sandbox measurements, recorded once and labeled `prerecorded` everywhere they appear.
- **Linear-style UI, dark first.** Light and dark themes, keyboard shortcuts with a command palette, accessible by test (axe in end-to-end runs).
- **Honest labels everywhere.** Every claim is one of: Observed, Hypothesis, Recommendation, Verified, Rejected, Inconclusive.

### Pages in the app

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

## Screenshots

Every screen supports light and dark mode.

> **About these captures.** They come from QueryCure's own automated end-to-end and visual tests running against a local stack, so run names such as `E2E sandbox 1792812211898` and the `stub/canned via stub` label in the run header are test artifacts: the tests use a stub model and seeded fixtures to stay deterministic. The numbers in the charts and replay reports are the recorded sandbox fixtures those tests load. The demo video above is the recorded investigation with real model output.

### Dashboard
What needs you, what finished, and how runs are going: active investigations, a run-outcomes bar for the last 25 investigations, recent runs, and counts by state.

| Light | Dark |
|---|---|
| ![Dashboard, light](docs/images/screenshots/dashboard-light.png) | ![Dashboard, dark](docs/images/screenshots/dashboard-dark.png) |

### History
Every investigation and its latest run, newest first, with search and status and outcome filters.

| Light | Dark |
|---|---|
| ![History, light](docs/images/screenshots/history-light.png) | ![History, dark](docs/images/screenshots/history-dark.png) |

### Run workspace: waiting for your approval
The LangGraph topology with each node's state taken from the recorded events. The run is paused at `approval_gate` until you decide. Later nodes show "no events recorded", never a guess.

| Light | Dark |
|---|---|
| ![Run waiting for approval, light](docs/images/screenshots/run-approval-light.png) | ![Run waiting for approval, dark](docs/images/screenshots/run-approval-dark.png) |

### Run workspace: completed graph
The same graph after the run finished. Pick any node to see its input, output, metadata and the evidence it cited. The model prompt is deliberately not sent to the browser; only its version is stored.

| Light | Dark |
|---|---|
| ![Completed run graph, light](docs/images/screenshots/run-graph-light.png) | ![Completed run graph, dark](docs/images/screenshots/run-graph-dark.png) |

### Run workspace: trace
A LangSmith-style trace of every step, tool call and logged event with timings, plus the hypotheses and per-agent findings on the right. Each finding links to the evidence ID it cites.

| Light | Dark |
|---|---|
| ![Run trace, light](docs/images/screenshots/run-trace-light.png) | ![Run trace, dark](docs/images/screenshots/run-trace-dark.png) |

### Speed-up with confidence interval
Per parameter set: the median speed-up, its 95% bootstrap interval, the 1.00x no-change line, the minimum effect and the maximum regression, on a log axis. This is the evidence the verdict gates read.

| Light | Dark |
|---|---|
| ![Speed-up chart, light](docs/images/screenshots/chart-speedup-light.png) | ![Speed-up chart, dark](docs/images/screenshots/chart-speedup-dark.png) |

### Timing distributions
Every measured sample for baseline and candidate, with the median, kept outliers and the transport floor (the cost of a bare round trip), so noise is visible instead of hidden.

| Light | Dark |
|---|---|
| ![Timing distributions, light](docs/images/screenshots/chart-distributions-light.png) | ![Timing distributions, dark](docs/images/screenshots/chart-distributions-dark.png) |

### Sealed report: original recommendation reproduced
An experiment replay re-measured the same experiment with the same seed and no model calls. The result matched the original within the equivalence margin. The report lists query, measurements, correctness, limitations, next steps, missing evidence and digests.

| Light | Dark |
|---|---|
| ![Replay report reproduced, light](docs/images/screenshots/replay-reproduced-light.png) | ![Replay report reproduced, dark](docs/images/screenshots/replay-reproduced-dark.png) |

### Sealed report: performance drift detected
Correctness held but the size of the speed-up moved beyond the margin, so the report says the original claim is **not confirmed** instead of declaring a pass.

| Light | Dark |
|---|---|
| ![Replay report with drift, light](docs/images/screenshots/replay-drift-light.png) | ![Replay report with drift, dark](docs/images/screenshots/replay-drift-dark.png) |

### Mobile
The run workspace on a 390 px wide screen.

| Light | Dark |
|---|---|
| <img src="docs/images/screenshots/mobile-run-light.png" alt="Run workspace on mobile, light" width="320"/> | <img src="docs/images/screenshots/mobile-run-dark.png" alt="Run workspace on mobile, dark" width="320"/> |

---

# 2. How it works

## An investigation, step by step

<div align="center">
<img src="docs/images/investigation-flow.svg" alt="Flow diagram: inputs, specialist agents, materiality gate, human approval, sandbox experiment, fixed-rule verification, sealed report, with early exits for no action needed and unverified recommendation" width="640"/>
</div>

1. **Intake and context.** Your query, plan and schema are parsed. In sandbox mode, a clone of a demo workload is `EXPLAIN`ed.
2. **Specialist agents.** A supervisor fans out to a Query Analyzer, an Index Strategist and a Workload Investigator. Each uses an allowlist of typed tools and returns cited findings and ranked hypotheses.
3. **Synthesis and materiality.** Hypotheses are combined, and a deterministic gate decides whether optimizing is worth it. If not, the run ends with **No action needed**.
4. **Optimization tournament.** An Optimization Engineer proposes candidates inside a strict DDL allowlist. **You approve the exact SQL.** Declining ends the run with an **Unverified recommendation**.
5. **Experiment.** The Benchmark Engine measures every candidate against the baseline under identical, interleaved conditions in a throwaway sandbox clone.
6. **Audit and report.** Fixed rules set the verdict. The Benchmark Auditor reviews it, downgrade only. The run is finalized into a sealed report (Markdown and JSON) with a manifest digest.

If a round ends inconclusive and budget remains, the loop goes back to the Optimization Engineer with the reason codes.

**A run ends in exactly one of these** ([AGENT_SYSTEM §12](docs/architecture/AGENT_SYSTEM.md)):

| Outcome | When |
|---|---|
| `verified_recommendation` | A candidate is verified, audited, and the tournament is complete |
| `no_action_needed` | No hypothesis is actionable, or the materiality gate found nothing material ([ADR-0017](docs/engineering/adr/ADR-0017-deterministic-materiality-gate.md)) |
| `unverified_recommendations` | Candidates exist but the sandbox is unavailable, or every approval was declined |
| `inconclusive` | Every candidate was rejected or inconclusive and the rounds or budget ran out |
| `cancelled` / `failed` | You cancelled, or an unrecoverable error occurred. A partial report is still written |

## The agents

The agent graph the run workspace draws, in the order a normal run visits it:

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
| **Supervisor** | LLM planning plus a deterministic router | none (routes only) | `InvestigationPlan`, `HypothesisSet` | Always |
| **Query Analyzer** | LLM plus tools | `get_plan_node`, `get_table_stats`, `get_column_stats`, `get_schema_object` | `QueryAnalysis` | A plan or query is available |
| **Index Strategist** | LLM plus tools | `list_indexes`, `get_column_stats`, `estimate_index_size` | `IndexAnalysis` | The query touches at least one base table |
| **Workload Investigator** | LLM plus tools | `get_statement_stats`, `get_activity_snapshot`, `get_lock_snapshot`, `get_table_io_stats` | `WorkloadAnalysis` | Live inspection with a workload capability, or an imported snapshot |
| **Optimization Engineer** | LLM | `validate_sql`, `explain_in_sandbox` (plain `EXPLAIN`, sandbox only) | `CandidateSet`, `ExperimentSpec` | At least one actionable hypothesis |
| **Benchmark Auditor** | Deterministic rules, then LLM narrative | `get_benchmark_summary`, `get_plan_diff` | `AuditAssessment` | After each experiment |
| Benchmark runner | **Deterministic node**, not an agent | sandbox and benchmark engine | `ExperimentResult` | After approval |
| Report writer | Deterministic template plus flagged LLM prose | none | `InvestigationReport` | Always, last |

**How an agent turn works.** Providers are not asked for native tool calling. Each turn the model returns one JSON object, either `call_tool` or `final`, validated against a Pydantic model. QueryCure's code then refuses any tool outside the agent's allowlist, validates the arguments, charges the call budget, records evidence and an execution row, and returns the result **fenced** as untrusted data. An agent gets at most 14 turns. Tools return evidence IDs next to their data so agents can cite them.

**Citations are enforced, not requested.** A claim without `evidence_ids`, or one that contradicts its evidence, is removed by the claims checker. If more than half of an agent's claims are removed, it is retried once. Prompts live in `backend/src/querycure/agents/prompts/`, each with a `PROMPT_VERSION` that is bumped on every change.

## Execution modes

How much of QueryCure touches a database is a per-investigation choice ([ADR-0003](docs/engineering/adr/ADR-0003-execution-modes.md)).

| Mode | What it does | Touches your database? | Available |
|---|---|---|---|
| **A. Offline** | Analyze a pasted `EXPLAIN (FORMAT JSON)` plan, SQL and schema | No | Everywhere, including a public demo |
| **B. Live inspection** | Run plain `EXPLAIN` through the inspection gateway in a read-only session | Reads catalog and plans only; never executes the query | Local installs. Off on a public demo |
| **C. Sandbox benchmark** | Build candidates and measure them in a disposable clone of a demo workload | No: runs in QueryCure's own sandbox | Local installs. Off on a hosted demo |

## Benchmark method

The benchmark engine (`bench@2`) is synchronous, deterministic Python. Every random choice is seeded, so the same experiment configuration reproduces the same schedule ([BENCHMARK_ENGINE](docs/architecture/BENCHMARK_ENGINE.md)).

1. **Provision.** A template database per workload version is built once. Each arm gets its own clone, owned by a locked-down `qc_bench` role.
2. **Build.** The approved candidate DDL (inside a strict allowlist) is applied to its clone. Index size and build time are recorded.
3. **Warm up.** A few executions per arm are discarded, so every arm is measured in the same warm-cache regime.
4. **Measure, interleaved.** Time is split into blocks. Each block runs every arm a few times in a shuffled order. Interleaving stops slow drift from favoring whichever arm ran later. The default is 30 measured runs per arm and parameter set.
5. **Check correctness.** Result rows from each candidate are fingerprinted and compared with the baseline's for every parameter set.
6. **Compute statistics.** The speed-up is the ratio of medians. Its 95% interval is a percentile bootstrap over 2,000 resamples. Medians and a bootstrap are used because latency is skewed and full of outliers, which breaks means and t-tests.
7. **Record the transport floor.** Bare `SELECT 1` round trips before and after measurement show how much of a timing is just the network hop. Nothing is subtracted, and no verdict reads it, but it is shown next to every result.
8. **Replicate when noisy.** If there is no winner but a promising screen, up to two more full experiments run with fresh seeds.

Operational costs are captured too: index size from `pg_relation_size` and `CREATE INDEX` wall time. Write overhead is not measured yet, so reports mark it **unmeasured** instead of guessing.

## How verdicts are decided

<div align="center">
<img src="docs/images/verdict-rules.svg" alt="Seven ordered deterministic gates. The first failing gate sets rejected or inconclusive with a reason code. Passing all gates yields verified within the tested scope. The Benchmark Auditor model may only downgrade to inconclusive." width="640"/>
</div>

The verification rules are plain deterministic Python. **No LLM ever computes a metric**, and no model can turn a `rejected` verdict into anything better. Gates run in order; the first one that fails sets the verdict and a reason code.

Two refinements worth knowing:

- **Corroborated regressions.** A confidence interval below the regression limit rejects a candidate only when it is corroborated: at least 20 samples on both arms, no failed baseline sample, at least 3 blocks, and every block ratio below the limit. Otherwise the result is inconclusive.
- **Noise warning.** If a noisy run has no winner but a promising screen, replicate experiments are measured. A candidate agreed on by all three experiments is reported as **verified with noise warning**, in words, never relabeled plain "verified".

## Reading the results

| Label | Meaning |
|---|---|
| **Verified** (within the tested scope) | Faster by more than the minimum effect, confidence interval clear of noise, same rows returned. Valid for the dataset, parameters, PostgreSQL version and hardware recorded with it |
| **Verified with noise warning** | Noisy measurements, but independent experiments agreed. Always shown in words |
| **Rejected** | A measured regression, different result rows, or a failed build. The reason is named |
| **Inconclusive** | Not enough evidence either way, often noise on a laptop. Not a failure: no claim is made |
| **Unverified recommendation** | Advice from analysis only; nothing was benchmarked |
| Experiment replay: **reproduced** / **reproduced with drift** / **not reproduced** / **inconclusive** | Whether a re-measurement agrees with the original within ±25% speed-up drift ([ADR-0023](docs/engineering/adr/ADR-0023-d9-experiment-replay-equivalence-margin.md)) |
| Report replay **verified** | The stored report still matches its stored digests. This proves consistency, not authenticity |

## Reports and replay

**What a sealed report contains**

| Section | Content |
|---|---|
| Query | The SQL and the parameter sets that were tested |
| Problem | Plan evidence and the materiality decision |
| Hypotheses and findings | Each with its cited evidence IDs and a "Why?" lineage drawer |
| Rounds | The exact SQL proposed in each round |
| Approvals | What you approved or declined, and when |
| Experiments | Measurements, correctness, build costs, replication and the audit, each with evidence ID and artifact digest |
| Recommendation | Always scoped to the sandbox it was measured in |
| Limitations, next steps, missing evidence | Stated in words, never omitted |
| Provenance and integrity | Models, prompt versions, measured versus prerecorded labels, and the digests |

Reports export as Markdown and JSON. Builders and renderers are **versioned and frozen**: a change means a new version ID, never an edit, so old reports stay byte-identical ([ADR-0015](docs/engineering/adr/ADR-0015-canonicalization-finalization-integrity.md)).

**Three kinds of replay, never conflated** ([REPLAY_ENGINE](docs/architecture/REPLAY_ENGINE.md)):

| Kind | What it does | LLM calls | New measurements |
|---|---|---|---|
| **Report replay** | Verifies a finalized run's stored evidence against its manifest and redisplays it | 0 | No |
| **Experiment replay** | Re-executes a stored experiment in a fresh sandbox and compares it statistically with the original | 0 | Yes, as a new linked run |
| **AI re-investigation** | A new LLM run on the same inputs, with consent, its own budget and a parent link | Yes | If it benchmarks |

Replay proves **consistency against stored digests, not authenticity**. It is never described as tamper-proof or certified.

## Demo workloads

Mode C benchmarks run on deterministic workloads: the same reference always produces byte-identical tables. Several are traps designed so the right answer is to *change nothing*.

| Workload | What it teaches |
|---|---|
| `orders_ecommerce` | Orders per customer, newest first, where ten hot customers own 10% of the rows. The classic composite-index win |
| `join_fanout` | A join on an unindexed foreign key with correlated predicates the planner underestimates |
| `stale_stats` | Half the rows were loaded after the last `ANALYZE`, so the planner picks a nested loop from a one-row estimate |
| `rewrite_trap` | A `NOT IN` against a list that contains `NULL`. A tempting rewrite changes the result |
| `no_benefit` | A small settings table read by primary key. Nothing to fix, and the right answer is "no action needed" |
| `index_regression` | An index that helps common statuses but walks almost the whole index for a rare one (an `ORDER BY ... LIMIT` trap) |
| `online_retail_ii` | A real dataset (UCI Online Retail II, CC BY 4.0) loaded as published, with duplicates and missing ids kept. The data file is not in this repository |

---

# 3. Architecture

## Technology stack

| Layer | Choice |
|---|---|
| **Frontend** | Next.js 16 (App Router), TypeScript, Tailwind CSS 4, TanStack Query, React Flow + dagre, CodeMirror 6 |
| **Backend** | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async) + Alembic, psycopg 3, SQLGlot |
| **AI** | LangGraph, LangChain (model integration and structured output), OpenRouter, Gemini, BYOK |
| **Data** | PostgreSQL for metadata (Neon in a hosted demo), Docker PostgreSQL for sandboxes |
| **Jobs** | PostgreSQL job queue (`SKIP LOCKED`) with `LISTEN/NOTIFY`. No Redis |
| **Auth** | Backend-owned cookie sessions, GitHub and Google OAuth (Authlib, PKCE), CSRF double-submit token |
| **Observability** | structlog JSON logs with request, job and run correlation IDs; Prometheus-format metrics computed from the database |
| **Testing** | pytest (unit, real-Postgres integration, security), Vitest, Playwright + axe, recorded-LLM evals with prerecorded measurement fixtures |
| **Delivery** | Docker Compose (local, demo and production profiles), GitHub Actions (CI and weekly dependency audits) |
| **Video** | A Remotion project in [`video/`](video/) renders the demo from the same recorded run the landing page uses |

Rationale for each choice: [DECISIONS](docs/engineering/DECISIONS.md) and the 34 ADRs in [docs/engineering/adr/](docs/engineering/adr/).

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
| **Deterministic core** | The benchmark engine and verification rules are plain Python. LLMs never compute metrics |

Full details: [ARCHITECTURE](docs/architecture/ARCHITECTURE.md) · [AGENT_SYSTEM](docs/architecture/AGENT_SYSTEM.md) · designed diagrams in [docs/diagrams/](docs/diagrams/).

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
│   │   └── workloads/ demo/     # Demo workloads and the prerecorded gallery
│   ├── migrations/              # Alembic (16 revisions)
│   ├── tests/                   # unit / integration / security / rehearsal
│   └── evals/                   # Recorded-LLM eval cases and measurement fixtures
├── frontend/                    # Next.js app (landing, sign-in, demo gallery, app)
│   ├── src/                     # app / components / lib / styles
│   └── e2e/                     # Playwright + axe
├── infra/docker/                # compose.yaml (local), compose.demo.yaml, compose.prod.yaml
├── video/                       # Remotion source for the demo video
└── docs/                        # Product, architecture, design, planning, ADRs, reports
    ├── images/                  # Diagrams and the screenshots shown above
    └── media/                   # Demo video
```

## Database design

Three databases with three owners, never mixed ([DATABASE_DESIGN](docs/architecture/DATABASE_DESIGN.md)):

| Database | Owner | Purpose | Access path | Lifecycle |
|---|---|---|---|---|
| **Metadata DB** | QueryCure | Users, investigations, events, artifacts, evidence, jobs, checkpoints | SQLAlchemy async repositories | Persistent |
| **Target DB** | You | Read-only inspection (Mode B) | The inspection gateway only | Never written to |
| **Sandbox DB** | QueryCure (ephemeral) | Benchmark clones (Mode C) | `sandbox` and `benchmark` modules | Template per workload; clones dropped after each experiment |

Conventions for every metadata table: UUID primary keys, `TEXT` not `VARCHAR`, `TIMESTAMPTZ` timestamps in UTC, `created_at` / `updated_at` / `deleted_at` with soft deletes, and no foreign-key constraints (integrity is enforced in repositories, [ADR-0006](docs/engineering/adr/ADR-0006-metadata-schema-conventions.md)). Artifacts are immutable and content-addressed by SHA-256.

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

## Authentication flow

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

- **Local profile:** a single local user and anonymous demo sessions, so you can try the app with no sign-in.
- **Providers:** GitHub and Google, each enabled by its own client ID and secret. Accounts are identified by `(auth_provider, auth_subject)` and are never merged by email.
- **CSRF:** a double-submit token. State-changing requests send the `qc_csrf` cookie value back in a header.
- **Restricted trial:** with `RESTRICTED_ACCESS=true` there are no anonymous sessions, and only allowlisted, provider-verified emails can sign in. The sign-in page then says **Private trial · approved accounts only** ([ADR-0031](docs/engineering/adr/ADR-0031-restricted-access-email-allowlist.md)).
- **Same-site cookies:** production needs the web app and API on the same site (or the web app proxying `/api/v1/*`, as in the Render route), because the cookies are `SameSite=Lax`.

## Real-time architecture

Progress is an **append-only event log**, not an in-memory stream, so a dropped connection loses nothing.

1. The worker writes each event to `investigation_events` with a per-run sequence number.
2. A `NOTIFY` wakes the API, which fans events out to open SSE connections.
3. A reconnecting browser sends `Last-Event-ID` (or `?after_seq=`) and receives exactly the events it missed.
4. A 15-second heartbeat keeps proxies from closing idle streams.
5. `GET /runs/{run_id}/events/history` returns the same log as plain JSON for the trace view.

**Durability.** Jobs are claimed with a lease. If a worker is stopped it stops claiming work, lets in-flight jobs finish for a grace period (20 s by default), then abandons them to lease expiry. The next worker resumes from the last LangGraph checkpoint. Every 5 minutes the worker logs `stuck_work_detected` for expired leases and runs with no job.

## Observability

| Channel | What you get |
|---|---|
| **Logs** | structlog JSON with request, job and run correlation IDs on every line. Credentials and prompts are redacted |
| **Metrics** | Prometheus format, computed from the database, at `/api/v1/internal/metrics` behind a bearer `METRICS_TOKEN` |
| **In the product** | The trace and graph views in the run workspace read the same persisted events the worker wrote |

Metrics include run outcomes and duration, LLM calls, tokens and latency per agent, tool calls by status, structured-output repairs, citations removed, queue depth, expired job leases, benchmark coefficient of variation, blocked security attempts, replay attempts by failure code, and open SSE connections. OpenTelemetry export and LangSmith are deferred. Details: [OBSERVABILITY](docs/engineering/OBSERVABILITY.md).

## Reliability and budgets

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
| Provider rate limit, 5xx or timeout | Exponential backoff with jitter, then the fallback model if one is configured |
| Invalid structured output | Re-prompt with the validation errors once, then one attempt on the fallback model |
| A model keeps failing in a run | A circuit breaker skips it |
| Uncited or contradicted claim | The claim is removed, never retried into existence |
| Sandbox benchmark failure | The experiment is marked failed and its candidates inconclusive, after one re-provision |
| Auditor skipped or crashed | At sealing, any verified candidate with no audit row is downgraded to inconclusive (`audit_not_completed`) |
| Worker stopped mid-run | The job lease expires and the next worker resumes from the checkpoint |

---

# 4. Reference

## API reference

Base path `/api/v1`. All timestamps are ISO 8601 UTC. JSON on the wire is `snake_case`; the frontend converts to `camelCase` in its API client only. Interactive docs are served at `/api/v1/docs` and the schema at `/api/v1/openapi.json`.

<details open>
<summary><b>Session and auth</b></summary>

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/auth/options` | Which sign-in methods are on, and whether access is restricted |
| `POST` | `/session` | Start a local or anonymous session |
| `GET` | `/me` | Current user, profile and feature flags |
| `POST` | `/auth/logout` | End the session |
| `GET` | `/auth/{github,google}/login` | Begin OAuth |
| `GET` | `/auth/{github,google}/callback` | Finish OAuth |

</details>

<details>
<summary><b>Investigations and runs</b></summary>

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/investigations` | Create an investigation (and its first run) |
| `GET` | `/investigations` | List, newest first |
| `GET` | `/investigations/{id}` | Read one |
| `DELETE` | `/investigations/{id}` | Soft delete |
| `POST` | `/investigations/{id}/restore` | Restore a soft-deleted one |
| `POST` | `/investigations/{id}/reinvestigate` | Start another run |
| `GET` | `/runs/{run_id}` | Run state, outcome, budget and usage |
| `POST` | `/runs/{run_id}/cancel` | Cancel a run |
| `GET` | `/runs/{run_id}/events` | Live SSE stream |
| `GET` | `/runs/{run_id}/events/history` | The same events as JSON |
| `GET` | `/runs/{run_id}/findings` | Cited findings and hypotheses |
| `GET` | `/runs/{run_id}/plans` | Plans collected for the run |
| `GET` | `/runs/{run_id}/evidence/{evidence_id}` | One evidence record |
| `GET` | `/artifacts/{sha256}` | An immutable artifact by digest |

</details>

<details>
<summary><b>Optimization, approvals and benchmarks</b></summary>

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/runs/{run_id}/candidates` | Proposed optimization candidates |
| `GET` | `/runs/{run_id}/approvals` | Pending and decided approvals |
| `POST` | `/approvals/{approval_id}/decision` | Approve or decline the exact SQL |
| `GET` | `/runs/{run_id}/experiments` | Experiments for a run |
| `GET` | `/experiments/{experiment_id}` | One experiment and its measurements |
| `GET` | `/runs/{run_id}/verifications` | Verdicts and the Benchmark Auditor panel |

</details>

<details>
<summary><b>Reports and replay</b></summary>

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
| `GET` | `/runs/{run_id}/plans/diff` | Baseline versus candidate plan diff |

</details>

<details>
<summary><b>Inspection, connections and workloads</b></summary>

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/inspect/sql` | Parse and validate SQL |
| `POST` | `/inspect/plan` | Analyze a pasted `EXPLAIN` JSON plan (Mode A) |
| `POST` | `/inspect/schema` | Parse a pasted schema |
| `GET` `POST` | `/connections` | List or add a connection |
| `DELETE` | `/connections/{id}` | Remove a connection |
| `POST` | `/connections/{id}/test` | Test connectivity |
| `GET` | `/connections/{id}/schema` | Read the catalog (fixed, parameterized queries) |
| `POST` | `/connections/{id}/explain` | Plain `EXPLAIN` through the gateway (Mode B) |
| `GET` | `/workloads` | The demo workloads |

</details>

<details>
<summary><b>Demo gallery, settings, health</b></summary>

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/demo/gallery` | Prerecorded investigations |
| `GET` | `/demo/gallery/{slug}` | One recording |
| `GET` | `/demo/gallery/{slug}/verification` | Verify its digests |
| `GET` `POST` | `/settings/llm-credentials` | List or save your key (encrypted; shown as last four characters) |
| `DELETE` | `/settings/llm-credentials/{id}` | Remove a key |
| `GET` | `/settings/models` | Allowed free models |
| `GET` | `/healthz` | Liveness |
| `GET` | `/readyz` | Database reachable and migrations current |
| `GET` | `/internal/metrics` | Prometheus-format metrics (bearer `METRICS_TOKEN`) |

</details>

Errors use one envelope: `{"error": {"code", "message", "status", "details"}}`. Design notes: [API_DESIGN](docs/architecture/API_DESIGN.md).

## Environment variables

Backend variables live in `backend/.env` locally (see `backend/.env.example`) or in the host's secret store. **Never commit real values.**

| Variable | Purpose |
|---|---|
| `QC_PROFILE` | `local` or `demo`. The demo profile is the restricted public configuration |
| `DATABASE_URL` | Metadata DB (pooled), as the restricted `qc_app` role |
| `DATABASE_URL_DIRECT` | Metadata DB (direct), for `LISTEN/NOTIFY` and the worker, as `qc_app` |
| `DATABASE_MIGRATION_URL` | Owner role, used only to run migrations from an operator machine. Never on the app host |
| `DATABASE_RETENTION_URL` | The one role allowed to `DELETE`; used only by the ops commands |
| `QC_MASTER_KEY` | 32 random bytes, base64. Encrypts stored keys and connection passwords. Keep a second offline copy |
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
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | GitHub OAuth (set the pair together) |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Google OAuth (set the pair together) |
| `LLM_PROVIDER` / `LLM_MODEL` / `LLM_FALLBACK_MODEL` | Provider and pinned free model. `stub` is local only |
| `OPENROUTER_API_KEY` | Local-profile key; hosted users bring their own |
| `LLM_DAILY_REQUEST_LIMIT`, `LLM_REQUESTS_PER_MINUTE`, `LLM_MAX_CONCURRENCY` | Rate and budget limits |
| `SANDBOX_ADMIN_URL` / `SANDBOX_BENCH_PASSWORD` | Local sandbox provisioning (never on a hosted API) |
| `LOG_LEVEL` | Log verbosity |

Frontend:

| Variable | Purpose |
|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | API origin, compiled into the bundle and the CSP, so set it **before** `pnpm build` |
| `BACKEND_ORIGIN` | Render route only: origin Next proxies `/api/v1/*` to (set for both build and run) |
| `BACKEND_PROXY_TIMEOUT_MS` | Optional idle timeout for that proxy |

## Security model

QueryCure runs LLM-authored SQL, so the boundary is enforced in the database, not in a prompt.

- **The LLM never receives a database client.** All access goes through the inspection gateway (Mode B) or the sandbox module (Mode C), using allowlisted operations.
- **Mode B is plain `EXPLAIN (FORMAT JSON)` only.** Never `EXPLAIN ANALYZE`, never DDL or DML. Every session is read-only and sets `statement_timeout`, `lock_timeout` and `idle_in_transaction_session_timeout`. Superuser connections are refused.
- **Catalog and statistics queries are fixed, parameterized templates in code.** LLM-authored SQL is only validated and `EXPLAIN`ed (Mode B) or executed in a sandbox (Mode C).
- **SQL validation (SQLGlot) is defense in depth, not the boundary.** The database-side controls stay on even when the parser agrees.
- **Least-privilege roles.** The API runs as `qc_app`, retention as `qc_retention`, migrations as the owner, and sandbox work as `qc_bench`, a role with no superuser, no `CREATEDB` and no file or program access.
- **Prompt-injection fencing.** Schema names, comments, plan text and query text are treated as untrusted input to prompts.
- **SSRF guard.** Connection targets are resolved, checked and pinned to a `hostaddr` before connecting.
- **Secrets stay out of state.** Credentials and API keys are never logged or placed in graph state, and are redacted by helpers.
- **You approve every sandbox statement.** The approval shows the exact SQL.

Full threat model: [SECURITY](docs/architecture/SECURITY.md).

## Supported and not supported

| Supported | Not supported (yet) |
|---|---|
| PostgreSQL 13 to 17 JSON plans; single `SELECT` statements | DML and DDL analysis; text-format plans |
| Offline analysis (Mode A) everywhere | Live inspection (Mode B) on a public demo |
| Live `EXPLAIN` (Mode B) on a local install | `EXPLAIN ANALYZE` on your database (never) |
| Sandbox benchmarking (Mode C) of the demo workloads, locally | Benchmarks on your own data or user-provisioned sandboxes |
| Free OpenRouter models with your own key (BYOK) | Paid models (refused by design, [ADR-0016](docs/engineering/adr/ADR-0016-free-openrouter-models-only.md)) |
| Anonymous sessions, GitHub and Google sign-in, restricted-access allowlist | Teams, sharing, admin roles |
| Report replay, experiment replay, AI re-investigation (start) | Conclusion diff between investigations; write-overhead benchmarks |

---

# 5. Run it

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

> To try the UI with no model at all, start the API and worker with `LLM_PROVIDER=stub` (canned, labeled output, local profile only). That is how the screenshots above were produced.

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

- **Strict typing and formatting.** `mypy --strict`, `ruff`, ESLint and `tsc` are all gates.
- **TDD for deterministic logic.** Parsers, validators, statistics and state transitions are written test first.
- **Every security control has a negative test** in `backend/tests/security/`.
- **Real Postgres in integration tests.** No mocked database for repository or benchmark behavior.
- **Evals without cost.** Agent changes need an eval case or an updated recorded fixture in `backend/evals/`; recorded runs replay with no model calls.
- **Accessibility.** Playwright runs axe against the key screens in both themes.

Strategy: [TESTING_STRATEGY](docs/engineering/TESTING_STRATEGY.md).

## CI/CD

| Workflow | Trigger | Jobs |
|---|---|---|
| `ci.yml` | Push to `main`, every PR | **Backend** (Python 3.12 and 3.13): ruff, format check, mypy, unit tests. **Backend integration** (`postgres:17` service containers): integration and security tests, recorded evals. **Frontend:** lint, typecheck, Vitest, build, and a build of both demo images. **End-to-end:** Playwright with the stub model |
| `audit.yml` | Mondays, manual, and PRs or pushes touching a lockfile | `pip-audit` for backend runtime dependencies, `pnpm audit` for the frontend |

Deployment is manual until a host is chosen: migrations run as a separate release step before new API instances start, and must stay backward compatible with the previous version (expand, migrate, contract).

## Deployment

Hosting is deliberately small: one always-on container for the API (with the embedded worker), one for the web app, and managed Postgres. Two routes are documented in [DEPLOYMENT](docs/architecture/DEPLOYMENT.md):

- **Single VM.** `infra/docker/compose.prod.yaml` with a Caddy reverse proxy and a guarded release script.
- **Render + Neon.** A Docker web service for the API and a Node web service for Next.js that proxies `/api/v1/*` to it.

<details>
<summary>Render settings at a glance</summary>

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

</details>

Hosted deployments run the restricted demo profile with an access allowlist, so the sign-in page shows **Private trial · approved accounts only**. Pre-release checks: [RELEASE_CHECKLIST](docs/engineering/RELEASE_CHECKLIST.md).

---

# 6. Project

## Development phases

| Phase | Theme | Status |
|---|---|---|
| 0 | Documentation and architecture | Done |
| 1 | Foundation: repo, API, metadata DB, SQL and plan parsing, demo workloads, editor | Done ([report](docs/planning/reports/PHASE_1_REPORT.md)) |
| 2 | Multi-agent intelligence: LangGraph supervisor, analyzer agents, streaming | Implemented ([report](docs/planning/reports/PHASE_2_REPORT.md)) |
| 3 | Optimization and benchmarking: sandbox, benchmark engine, tournament | Implemented ([report](docs/planning/reports/PHASE_3_REPORT.md)) |
| 4 | Verification and replay: auditor, lineage, replay, regression detection | Implemented ([report](docs/planning/reports/PHASE_4_REPORT.md)) |
| 5 | Production polish: auth, BYOK, hardening, demo gallery, operations, deployment artifacts | Implemented and verified locally ([report](docs/planning/reports/PHASE_5_REPORT.md)) |

## Roadmap

Post-MVP candidates, in priority order ([ROADMAP](docs/planning/ROADMAP.md)):

1. Write-overhead micro-benchmark, so index cost on inserts and updates is measured instead of marked unmeasured.
2. AI re-investigation with a conclusion diff against the original run.
3. HypoPG pre-screen to rank index candidates before building them.
4. Grounded Q&A over a finished investigation.
5. Shareable read-only reports.
6. Text-format plans and `pg_stat_statements` CSV import.

## FAQ

<details>
<summary><b>Does QueryCure change my database?</b></summary>

No. Live inspection runs plain `EXPLAIN` in a read-only session and never executes your query. Candidate SQL runs only in a disposable sandbox clone, and only after you approve the exact statement.

</details>

<details>
<summary><b>Do I need a paid model?</b></summary>

No. QueryCure uses free OpenRouter models only, with your own key, and refuses paid models by design. Free models are slow (a run takes a few minutes) and rate limited.

</details>

<details>
<summary><b>Why does it say "inconclusive" so often?</b></summary>

Because that is often the honest answer. On a laptop or a shared host, timing noise can be larger than a modest improvement. QueryCure would rather say "not enough evidence" with a reason code than pick a winner from noise.

</details>

<details>
<summary><b>Can I benchmark my own data?</b></summary>

Not yet. Sandbox benchmarks run on the demo workloads. For your own database you get plan analysis and live `EXPLAIN` (on a local install), and an unverified recommendation to test on a staging copy. The report's "next steps" says so.

</details>

<details>
<summary><b>What does "verified" actually mean?</b></summary>

Verified within the tested scope: the dataset, parameters, PostgreSQL version and hardware recorded with the result. It is not a guarantee for your production workload.

</details>

<details>
<summary><b>Is a sealed report tamper-proof?</b></summary>

No. Replay checks that stored records still match their stored digests, which shows consistency. It does not prove who wrote them, so it is never described as tamper-proof or certified.

</details>

<details>
<summary><b>Which PostgreSQL versions work?</b></summary>

JSON-format plans from PostgreSQL 13 to 17 are parsed. The recorded demo run used 17.11.

</details>

<details>
<summary><b>Is there a public hosted version?</b></summary>

A hosted trial runs as a private, allowlisted deployment. Anyone else sees "Private trial · approved accounts only". To try it, run it locally with the steps above.

</details>

## Documentation

| Area | Read |
|---|---|
| **Product** | [PRD](docs/product/PRD.md) · [Features](docs/product/FEATURES.md) · [Glossary](docs/GLOSSARY.md) |
| **Architecture** | [Architecture](docs/architecture/ARCHITECTURE.md) · [Agent system](docs/architecture/AGENT_SYSTEM.md) · [Database design](docs/architecture/DATABASE_DESIGN.md) · [API design](docs/architecture/API_DESIGN.md) · [Security](docs/architecture/SECURITY.md) · [Benchmark engine](docs/architecture/BENCHMARK_ENGINE.md) · [Replay engine](docs/architecture/REPLAY_ENGINE.md) · [Deployment](docs/architecture/DEPLOYMENT.md) |
| **Design** | [Design system](docs/design/DESIGN_SYSTEM.md) · [UI/UX](docs/design/UI_UX.md) |
| **Engineering** | [File map](docs/engineering/FILE_MAP.md) · [Coding standards](docs/engineering/CODING_STANDARDS.md) · [Testing strategy](docs/engineering/TESTING_STRATEGY.md) · [Observability](docs/engineering/OBSERVABILITY.md) · [Learning guide](docs/engineering/LEARNING.md) · [Decisions and ADRs](docs/engineering/DECISIONS.md) |
| **Planning** | [Roadmap](docs/planning/ROADMAP.md) · [Tasks](docs/planning/TASKS.md) · [Risks](docs/planning/RISKS.md) |
| **Contributors and agents** | [CLAUDE.md](CLAUDE.md) · [AGENTS.md](AGENTS.md) |

## Honesty policy

- QueryCure never fabricates benchmark numbers. Example numbers in the docs are illustrative only.
- Prerecorded demo benchmarks are always labeled as such and are never presented as measurements of your database.
- **"Verified" always means "verified within the tested scope":** dataset, parameters, PostgreSQL version and hardware are recorded alongside the result.
- Report replay proves *consistency against stored digests*, not authenticity. It is not described as tamper-proof or certified.
- The screenshots in this README come from automated tests that use a stub model and seeded fixtures, and say so.

## License

Released under the [MIT License](LICENSE). Copyright (c) 2026 Yuvraj Satyapal.
