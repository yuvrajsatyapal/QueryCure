# AI reliability, evidence integrity and production hardening — 2026-10-17

Follow-up to the [end-to-end audit of the same day](E2E_AUDIT_2026-10-17.md): issues O1, O2, O3, O6 and O7, plus the retry, fallback and handoff review. The decision record is [ADR-0026](../engineering/adr/ADR-0026-deterministic-claim-grounding-and-model-reliability.md).

Everything below was run in this session unless it is marked **not done**. Two kinds of run appear here:
- **Real-model** runs called OpenRouter.
- **Recorded** runs replay stored responses and make no model call.

No secrets appear in this report.

## A. Root causes

| # | Issue | Root cause |
|---|---|---|
| O1 | `openrouter/free` could not complete an investigation | **Router primary.** `.env` and `.env.example` set the router as the primary (the code default was already the pinned model). |
| | | **Fallback scope.** The fallback client was used only after transport retries ran out, never for invalid output. |
| | | **No memory of failures.** Nothing remembered that a model had failed, so every agent paid the full cycle again. |
| | | **Amplification.** One logical call could cost 4 attempts × 120 s, plus a repair, a fallback and a citation retry. Timeouts were retried 3 times. |
| O1 | Failure classes blurred | `LLMUnavailableError` dropped the transport cause. A 404 "no endpoints" became a generic `LLM_REQUEST_REJECTED`. |
| O2 | The AI narrative contradicted the verdicts | **Pre-benchmark summary.** The report `summary` is the synthesis text, written before any benchmark, so its "create the index **and run ANALYZE**" was never reconciled with ANALYZE's `inconclusive` verdict. |
| | | **Citations ≠ agreement.** Citations prove a claim points at evidence, not that it agrees with it. |
| | | **Narrow number check.** The only quantitative guard was one "N x faster" regex. It missed ranges and the model's U+2011 hyphens (`2.9‑4.4×`), and never compared auditor figures with stored values. That range combined point estimates from two different experiments, so it matches no stored interval. |
| | | **Scan types unchecked.** Nothing compared scan-type claims with plan nodes. "Index‑only scan" for `SELECT *` appeared in the summary and in a candidate's `expected_benefit`. |
| O3 | False stale-statistics hypothesis | `schema_evidence` rendered `pg_stat_*` counters as "0 seq scans / 0 index scans; last analyzed never". `CREATE DATABASE … TEMPLATE` resets those counters, while the planner statistics in the same snapshot (reltuples 100,000, `pg_stats` for 5 columns) showed the table had been analyzed. The false evidence produced a hypothesis, a finding and the ANALYZE candidate. |
| O6 | Quota counted attempts that never left the machine | `DailyQuota` counted every `agent_executions` row, including connection-refused attempts. |
| O7 | A total outage looked like a plain `inconclusive` | `write_report` never derived a run-level reason from per-call outcomes. |

Where unsupported claims entered the system: analyst findings and summaries, hypothesis statements, the synthesis summary (into the report summary), candidate prose (into the approval card and the report), and the auditor's summary and concerns (into the audit notes). The fixes below cover each of these.

## B. Changes implemented

| Area | Files / functions | What changed |
|---|---|---|
| Claim grounding | `agents/claims.py` (new): `filter_text`, `check_sentence`, `claim_context`, `action_refs`, `star_projection`, `index_columns`, `CHECKER_VERSION = "claims@1"` | Sentence-level, deterministic checks against recorded evidence. Rules are listed in ADR-0026 §1. |
| Wiring | `agents/outputs.py` (`judge_analysis`, `judge_hypotheses`, `judge_audit` take a `ClaimContext`)<br>`agents/candidates.py` (`judge_candidates(claims=)`)<br>`agents/agent_runner.py` (`run_tool_agent(query_sql=)`, `claim_check` stored with outputs)<br>`nodes/supervisor.py`, `nodes/optimization_engineer.py`, `nodes/benchmark_auditor.py` (`audit_actions`), `nodes/analysts.py` | Every LLM prose boundary is grounded. Removals are recorded with the output and never trigger a retry (`CitationReport.claims_removed` and `claim_problems`). |
| Final reconciliation | `nodes/write_report.py`: `_reconcile_summary`, `model_failure`<br>`replay/finalize.py` (`Conclusion.narrative_check`)<br>`db/repositories/agents.call_outcomes` | Summary sentences that contradict final candidate statuses are removed and recorded in `run.concluded`. `MODEL_UNAVAILABLE` is recorded when no call succeeded. |
| Statistics provenance | `evidence/builders.schema_evidence(origin=…)`, `nodes/collect_context._opener` | `planner_stats`, `counters`, `freshness`, `stats_origin` and `analyzed_columns` per table. Clone counters are labelled reset. |
| Retry, fallback, circuit | `llm/structured.py`: `RetryPolicy.max_timeout_retries=1`, `LLMError.cause`, `LLMModelUnavailableError`, `LLMCircuitOpenError`, `ModelHealth`, `call_structured(health=)`, `_attempt`<br>`llm/openrouter.ModelUnavailableError`<br>`agents/runtime.RunContext.llm_health`, `agents/run.py`<br>`core/config.llm_circuit_threshold` | Bounded behaviour described in ADR-0026 §4. |
| Default model | `.env.example`, local `backend/.env` (gitignored, one line), `llm/models.py` (new), `worker/__main__.py` warning, `llm/probe.py` (new, opt-in, one request)<br>`core/config._blank_fallback_is_unset` | Pinned, tested model. An empty `LLM_FALLBACK_MODEL=` means no fallback; before this fix it failed startup, which the smoke run caught. |
| Quota | `llm/rate_limit.NOT_DISPATCHED_CODES` | `LLM_CONNECTION_ERROR` rows no longer use the allowance. |
| API / UI | `api/schemas/investigations.RunDetail.error_message`; `InvestigationView.tsx`; regenerated OpenAPI types | The run-level reason is shown in words. |
| Docs | ADR-0026, DECISIONS, AGENT_SYSTEM §5 / §10, API_DESIGN, CURRENT_PHASE | — |

Architectural decisions:
- **No `report-builder@2`.** Grounding happens before text enters records, so the frozen `report-builder@1` / `report-md@1` render validated text for new runs, and sealed reports and their replay are untouched.
- **Prompts unchanged.** No prompt was edited, so no `PROMPT_VERSION` bump was needed. The only prompt-visible change is the Mode C table-statistics evidence text (O3).
- **Agent handoffs.** The Optimization Engineer still cannot propose a candidate that addresses no known hypothesis, and its prose is grounded. The Benchmark Auditor reads stored measurements and can only downgrade (ADR-0009). Its narrative is now grounded against the post-check verdicts. Missing evidence still yields `unverified` or `inconclusive`, and invalid outputs never reach persisted state (Pydantic validation, then the citation check, then grounding).

## C. Before / after

Real text from audit run 2 (`2968ce49`), now regression tests (`tests/unit/agents/test_claims.py`, `tests/integration/test_report_grounding.py`):

| Text | Before | After |
|---|---|---|
| Summary: "Creating the recommended index and running ANALYZE should resolve the performance issue." | In the report next to "Verified recommendation" | Removed: "recommends ANALYZE, which was not verified by the benchmark" |
| Summary: "…would allow an index‑only scan…" (`SELECT *`) | Shown | Removed: "an index-only scan is impossible for SELECT * and no recorded plan shows one" |
| Summary: "Additionally, the table statistics are stale…" | Shown | Removed: "no recorded statistic shows the statistics are stale" |
| Auditor: "…showed 2.9‑4.4× median latency reductions…" | Audit notes | Removed: "speed-up range 2.9-4.4x matches no measured confidence interval". The next sentence, "All other candidates… remained inconclusive", is kept. |
| Hypothesis: "Table statistics are stale (never analyzed)…" | Hypothesis → ANALYZE candidate | Dropped: "planner statistics are present, so the table has been analyzed" |
| Finding: "…the table has never had an index scan (0 index scans ever)." | Shown | That sentence removed: "usage counters were reset by sandbox cloning and are not evidence" |
| Table evidence | "~100,000 rows, 9.0 MiB, 0 seq scans / 0 index scans; last analyzed never" | "~100,000 rows, 9.0 MiB; planner statistics present (5 columns); usage counters (scans, last analyze, row changes) were reset when the sandbox clone was created and are not evidence" |
| Total outage | `completed · inconclusive`, `error: null` | `error_code: MODEL_UNAVAILABLE`, message "No model call produced usable output (7 attempt(s): 5 invalid structured output, 2 timeout), so nothing was diagnosed…", and an `error` event in the sealed log |
| 12 connection-refused attempts | 12 of 45 free requests used | 0 used |

False positives found on recorded real-model output, then fixed and covered by tests:
- "270× overestimate" is an estimate-error ratio, not a speed-up (plan value 270.81).
- "≈62 ms" against a recorded 62.568 ms.
- A truncated "2.9x" against a measured 2.955.

## D. Model reliability

| Item | State |
|---|---|
| Default model | `nvidia/nemotron-3-super-120b-a12b:free` (code default, `.env.example`, local `.env`). Evidence: Phase 2 benchmark, eval recordings, audit runs 2–3 (13/13 valid), and this session's smoke run (7/7 valid) and recordings (15/15 valid). |
| Router | Discouraged as the primary (startup warning). Allowed only as an optional, bounded fallback. |
| Fallback policy | Optional (empty by default, to save quota), free only. One full attempt when the primary is unavailable, the model is unknown, or the output is still invalid after repair. Never used for quota, paid usage or rejected keys. No ping-pong. BYOK runs have no server fallback (unchanged). |
| Circuit breaker | After 2 consecutive failed logical calls (an unknown model trips at once) the model is skipped for the rest of the run. When every model is open: `LLM_CIRCUIT_OPEN`, with no calls. |
| Timeouts | 120 s per call, retried once (it was up to 3 times). Worst case per logical call on a hanging model: about 4 min instead of 8. The run wall clock (20 min local, 5 min demo) still bounds the total. |
| Error classes | `LLM_RATE_LIMITED`, `LLM_TIMEOUT`, `LLM_CONNECTION_ERROR`, `LLM_PROVIDER_ERROR`, `LLM_MODEL_UNAVAILABLE`, `LLM_INVALID_OUTPUT`, `LLM_FREE_QUOTA_EXHAUSTED`, `LLM_PAID_USAGE_BLOCKED`, `LLM_AUTH_FAILED`, `LLM_CIRCUIT_OPEN`. `AGENT_FAILED` details carry `cause`. |
| Schema validity | Probe CLI `python -m querycure.llm.probe [--model]`: one request, no retry. **It was not run this session** to save quota. |
| Per-run model choice | Still refused (`llm.model` → 422). Not added: it needs persistence and worker plumbing. |
| Provenance | Unchanged and verified in the smoke report: requested model, served model and upstream provider per call, prompt versions per agent. |
| Limitations | One more real run is still a small sample. The free tier allows about 50 requests a day, which limits re-recording (§F). `openrouter/free` was not re-measured. |

## E. Evidence integrity

- **Measured facts come only from deterministic code:** speed-ups, intervals, verdicts, the headline and the recommendation (`report-builder@1`, unchanged).
- **AI prose can explain, never assert.** It cannot keep a figure, range, latency, scan type, verification status, recommendation or statistics claim that the recorded evidence does not support. Unsupported sentences are removed, not reworded, and every removal is recorded (`claim_check`, `narrative_check`).
- **Uncertainty is preserved:**
  - Hedged proposals stay in hypotheses.
  - `verified_with_noise_warning` keeps its headline and limitation text.
  - Inconclusive candidates cannot be recommended in prose, because a recommendation sentence survives only if every action it names maps to a verified candidate.
- **Known gaps:**
  - The report UI does not yet show *what* was removed: `narrative_check` is in the sealed event log only, and surfacing it needs `report-builder@2`.
  - A sentence mixing a supported and an unsupported claim is removed whole.
  - The checker is pattern-based. A contradiction phrased in a way it does not recognise can still pass.

## F. Regression results (actual output, this session)

| Suite | Result |
|---|---|
| Backend `ruff check`, `ruff format --check`, `mypy --strict src` | pass (208 source files) |
| Backend unit | **837 passed, 1 xfailed** (ADR-0019 limitation; was 767) |
| Backend integration + security (local Docker, `QC_REQUIRE_DB=1`) | **607 passed**, 0 failed (was 603). Run before the last one-line config validator, which has its own unit tests. |
| Evals smoke (recorded) | **5/5**. `orders_missing_composite_index` re-recorded: its old recording contained an "index-only retrieval" finding for `SELECT *`, which grounding now removes. |
| Evals Mode C (recorded + prerecorded fixtures) | **0/2: not re-recorded.** The O3 context text changes their first prompt. A record attempt of `orders_sandbox_composite_index` hit the request cap in round 2 and was not saved (result file committed as FAIL). The CI step "Eval Mode C" fails until both cases are re-recorded. |
| Frontend lint, typecheck, unit (Vitest) | pass, **89 passed** (21 files) |
| Frontend production build | pass |
| Playwright e2e (stub LLM, local Docker) | **14/14** |

New targeted tests, mapped to the required list:
1. Invalid structured output → fallback, no ping-pong.
2. Unsupported benchmark claims.
3. Incorrect speed-up figures and ranges.
4. Scan-type claims.
5. Inconclusive candidates recommended in prose.
6. Reset PostgreSQL statistics (real run-2 snapshot values).
7. Timeouts (one retry) and 429 cause.
8. Fallback restrictions (quota never reaches it, paid fallback refused, empty fallback = none).
9. Evidence-handoff grounding for each judge, plus candidate prose.
10. Historical replay: the existing report-replay suite passes unchanged, and the smoke run's report replay is `verified`.

Files: `test_claims.py` (37), `test_grounding.py` (8), `test_structured.py` (+10), `test_models.py` (3), `test_builders.py` (+5), `test_config.py` (+2), `test_report_grounding.py` (3 integration), the quota integration test, and `InvestigationView.test.tsx` (+1).

### Real-model smoke investigation

- **Run** `4c54fb8f`, through the HTTP API (session, CSRF, explicit approval) with the host worker. Local Docker metadata DB (not Neon), local Docker sandbox, `nvidia/nemotron-3-super-120b-a12b:free`, capped at 14 requests.
- **Progression:** plan → query_analyzer ∥ index_strategist (1 tool call) → synthesis → optimization_engineer → approval gate (paused, approved over the API) → 3 sandbox experiments → auditor → report.
- **Model calls:** 7 real requests, all schema-valid; 14,841 + 7,546 tokens; no fallback, no circuit trip.
- **Hypotheses:** 1, `missing_index` (high), cited. **No stale-statistics hypothesis and no ANALYZE candidate**, now that the clone counters are labelled.
- **Grounding in action:** the Optimization Engineer again wrote "Enable index-only scan…" for `SELECT *`, and grounding removed it (the candidate shows "Not stated.").
- **Verdict:** `verified_with_noise_warning`, which the report renders unchanged:
  - `hot_customer` 3.62 → 0.77 ms, 4.72× (3.40–5.67);
  - `regular_customer` 3.19 → 0.51 ms, 6.27× (5.22–7.40);
  - robust CV up to 0.47, 2 replicates; provenance `measured`, `docker-relay`.
- **Outcome and replay:** `verified_recommendation`. Report replay `verified`.
- **Eval recording:** `orders_missing_composite_index` re-recorded with 5 real requests (passes).

Real requests today: 23 (audit) + 7 (smoke) + 15 (recording) = 45. Today's ledger is exhausted, so nothing more was attempted.

## G. Remaining risks before a restricted public demo

1. **Mode C eval recordings are stale.** CI "Eval Mode C" is red until `orders_sandbox_composite_index` and `rewrite_trap_sandbox` are re-recorded. That takes about 25 requests, including a possible second round, so it is a job for tomorrow's allowance. Command:
   ```
   uv run python -m querycure.evals run --suite full --mode record --case <id> --model nvidia/nemotron-3-super-120b-a12b:free --admin-url <local>
   ```
2. **Noisy local measurements (O5):** this run had robust CV up to 0.47 on the relay path, and round 1 in the eval record was inconclusive.
3. **Removals are invisible in the report UI.** They are in the sealed log but not on the report page (`report-builder@2`, together with O4 measured materiality).
4. **Pattern coverage of `claims@1`.** Paraphrased contradictions can slip through. Grounding is defence in depth, and the verdicts remain deterministic.
5. **OAuth sign-in on real origins** has not been completed (unchanged from the audit).
6. **BYOK default model.** It must be a tested model (the startup warning covers only server-side models).
7. **Hosting and region (O11) and provenance gaps (O10)** are unchanged.
8. **Old worker still running.** A host worker started at 14:16 local time (during the audit, connected to Neon) still runs the pre-change code. Restart it before using the Neon setup.

## H. Next phase: frontend redesign readiness checklist (priority order)

1. Re-record the two Mode C eval cases (green CI) before any UI work.
2. `report-builder@2` / `report-md@2`: show removed AI claims (`narrative_check`, `claim_check`) under "AI-written, checked against measurements", and measured materiality (O4).
3. Investigation view:
   - waiting for model (attempt n, cause) from `llm_call` records;
   - circuit-open and fallback notices;
   - `MODEL_UNAVAILABLE` banner styling.
4. Truthful display:
   - hypotheses linked to their verified candidate;
   - no "too noisy" caption on verified rows;
   - version and approver formatting (O9);
   - no "No hypotheses" text before synthesis has run.
5. Statistics provenance in the evidence drawer: planner statistics vs counters, reset by clone.
6. Settings: show the tested-model status of the BYOK default model, and offer the probe as an explicit, quota-labelled action.
7. Dashboard data (recent runs, pending approvals), Mode B prominence, and an experiment-replay entry point (audit §E).
8. Keep axe AA, 375 px layouts and reduced motion green (e2e 14/14 today).
