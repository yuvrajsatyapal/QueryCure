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
| [0016](adr/ADR-0016-free-openrouter-models-only.md) | Free OpenRouter models only: config guard, per-response zero-cost check, no paid fallback, free-tier rate and daily limits, served-model provenance | Zero spend and graceful stops vs fewer runs per day and weaker models |
| [0017](adr/ADR-0017-deterministic-materiality-gate.md) | Deterministic optimization-materiality gate after synthesis: workload share, measured latency vs planning overhead, rows touched, table size and spills; `not_material` caps hypotheses and ends `no_action_needed` | Calibration independent of the model vs conservative thresholds that leave borderline cases `undetermined` |
| [0018](adr/ADR-0018-robust-sample-quality-gate.md) | Sample-quality gate uses robust CV (IQR / 1.349·median) and runs after a decisive regression check; classic CV still reported | Median-consistent noise gate and reported harm on noisy hosts vs a further departure from the original ADR-0008 rule |
| [0019](adr/ADR-0019-noise-warning-verification-and-corroborated-regression.md) | `bench@2`: a regression rejects only when corroborated (n ≥ 20, no baseline censoring, every block slower); D11: `verified_with_noise_warning` needs a per-experiment noise screen (n ≥ 30, no censoring, no param-set regression, quartile separation, every block ≥ `min_effect`) plus agreement of 3 independent experiments; `bench@1` rules frozen for replay | Conservative, explained verdicts on noisy hosts vs two extra experiments on the noisy path and more `inconclusive` regressions |
| [0020](adr/ADR-0020-container-worker-default-for-local-benchmarks.md) | Containerized worker on `sandbox_net` is the default for local Mode C benchmarking; host worker + relay still supported; measurement path recorded in the fingerprint | Lower measurement noise vs a rebuild after backend changes |
| [0021](adr/ADR-0021-d13-clean-verification-block-agreement.md) | **Accepted 2026-10-13:** D13 closed as no change to `bench@2`: no block-agreement check on the clean `verified` gate and no block-size or schedule change. Measured false verification is 0/2,250 real runs below `min_effect`; block agreement would cost about 28 points of correct verifications at 1.18× | Keeps power and released semantics vs leaving the single-experiment arm-specific-bias limitation (R18) documented, not closed |
| [0022](adr/ADR-0022-phase4-verification-replay-implementation.md) | Phase 4 implementation: DB-enforced downgrade-only auditor with deterministic re-scoring first; `run.concluded` content event so builders read only records; every terminal path finalizes; strict canonical-byte verification; `container_runtime` material in replay comparison; replay scored by source rules; comparison stored as content; re-investigation start contract; live-measurement eval replay reported as `DIVERGED` | Byte-exact, rebuildable reports and honest eval status vs Mode C evals that cannot replay green |
| [0023](adr/ADR-0023-d9-experiment-replay-equivalence-margin.md) | **Accepted 2026-10-16:** D9 closed: the experiment-replay equivalence margin stays `m = 1.25` (±25% speed-up drift). It is not widened to raise the reproduction rate; low reproduction on noisy hardware is a measurement problem. No code or released contract changes | A stricter "reproduced" vs more same-machine replays ending `inconclusive` |
| [0024](adr/ADR-0024-deterministic-mode-c-evals-measurement-fixtures.md) | **Accepted 2026-10-16 (R19):** Mode C eval replay uses prerecorded measurement fixtures captured at record time (labelled `prerecorded` everywhere), exact prompt matching and no benchmark; live re-benchmarking stays available as `--measurements live` (`DIVERGED` never a pass) | Deterministic, offline agent evals vs a re-record after deliberate prompt/rule changes |
| [0025](adr/ADR-0025-pgbouncer-compatible-metadata-connections.md) | **Accepted 2026-10-17:** pooled (Neon PgBouncer) metadata connections apply `statement_timeout` / `idle_in_transaction_session_timeout` per transaction via `set_config(..., true)`; direct endpoints keep startup options; LISTEN and the checkpointer use `DATABASE_URL_DIRECT`; settings reject inconsistent URL pairs | Startup options (rejected by the pooler) vs per-transaction hook vs dropping the timeouts |
| [0026](adr/ADR-0026-deterministic-claim-grounding-and-model-reliability.md) | **Accepted 2026-10-17:** deterministic claim grounding (`claims@1`) at every LLM output boundary and once more against final verdicts; statistics provenance (planner vs reset counters); timeouts retried once, bounded free fallback incl. invalid output, per-run model circuit breaker; pinned default model; run-level `MODEL_UNAVAILABLE`; quota excludes undispatched attempts; no report-builder change | Model prose can no longer contradict measurements vs conservative sentence removal and re-recorded evals |
| [0027](adr/ADR-0027-groq-provider-trusted-free-plan.md) | **Accepted 2026-10-17 (owner):** `LLM_PROVIDER=groq` with a local-profile `GROQ_API_KEY`; allowed while `LLM_FREE_ONLY` is on by trusting the key to be on Groq's free plan (Groq reports no cost); per-day 429 stops the run, minute limiter applies, no BYOK; amends ADR-0016 | Groq usable without dropping free-only vs a free-only promise that is the operator's, not a code check |
| [0028](adr/ADR-0028-evidence-specific-claim-grounding.md) | **Accepted 2026-10-18:** `claims@2` binds each clause to the arms, param sets, experiment and plan it names before checking it, adds typed claims (fold/factor/percentage reduction/saving/transition), status, guarantee, advice-against, estimate and freshness rules; `claims@1` frozen; version recorded in `claim_check` and `narrative_check` | Evidence-specific grounding without an LLM call vs still pattern-based coverage |

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
