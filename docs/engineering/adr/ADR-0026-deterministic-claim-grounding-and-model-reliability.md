# ADR-0026: Deterministic claim grounding and bounded model reliability

- Status: Accepted (2026-10-17); amends ADR-0016 (fallback policy) and AGENT_SYSTEM §5, §10
- Area: Agents / LLM / Evidence integrity / Reports

## Context

The end-to-end audit of 2026-10-17 ([report](../../reports/E2E_AUDIT_2026-10-17.md)) found:

1. **O1.** The configured router `openrouter/free` produced 1 valid structured output in 10 calls. Each failing agent paid the full retry budget again: up to 4 attempts × 120 s per logical call, plus repair and citation retries.
2. **O2.** In run 2, AI-written text contradicted the measurements, although every claim was cited:
   - the report summary recommended "creating the index *and running ANALYZE*", but ANALYZE was `inconclusive`;
   - it promised an index-only scan for `SELECT *`;
   - the auditor quoted a "2.9‑4.4×" range that combined point estimates from two different experiments, so it matched no stored interval.

   Citations prove that a claim points at evidence. They do not prove that the claim agrees with it.
3. **O3.** Sandbox clones copy planner statistics (`pg_statistic`, `reltuples`), but `CREATE DATABASE … TEMPLATE` resets the cumulative counters (`pg_stat_*`). The evidence text said "0 seq scans / 0 index scans; last analyzed never", so agents hypothesised stale statistics and proposed `ANALYZE`.
4. **O6/O7.** The free allowance counted attempts that never reached the provider. A total outage ended as a plain `inconclusive` with no reason.

Constraints:
- `report-builder@1` / `report-md@1` are released and frozen (ADR-0015), and sealed reports must replay byte for byte.
- Eval recordings match prompts exactly (ADR-0024).
- The free tier allows about 50 requests a day.

## Decision

1. **Claim grounding (`agents/claims.py`, `claims@1`).** A deterministic, sentence-level checker runs at every boundary where model prose becomes a record:
   - findings, plus analyst summaries;
   - hypotheses (statement and notes, in `hypothesis` mode);
   - the synthesis summary;
   - candidate `expected_benefit` and `risks`;
   - the auditor's summary and concerns;
   - once more in `write_report`, against final candidate statuses.

   It only removes sentences; it never rewrites or adds text. Its rules:
   - a speed-up must equal a measured point estimate or CI bound, within the stated precision or 2%;
   - a range must equal one stored interval;
   - nothing is quantified before a benchmark exists;
   - a percentage must derive from a measured speed-up;
   - a latency must match a recorded timing (3%, or 10% when marked approximate);
   - "N× overestimate" is an estimate ratio, checked against plan nodes (5%);
   - an index-only scan is impossible for `SELECT *` unless a recorded plan shows one;
   - a scan type stated as fact must appear in a recorded plan (proposals may name others);
   - nothing is "verified" before a benchmark, and a named arm's stated status must match its verdict;
   - after benchmarking, a recommended action must map to a verified candidate;
   - "never analyzed" contradicts present planner statistics, and reset counters are not evidence;
   - staleness stated as fact needs evidence of staleness.

   Removed claims are recorded with the agent output (`citations.claim_check`). For the summary they are recorded in the `run.concluded` payload (`narrative_check`), which `report-builder@1` does not read. They never trigger a retry: the check is deterministic, and a retry would spend scarce calls on the same filter.
2. **No new report builder.** Grounding happens before text enters records, so `report-builder@1` renders validated text for new runs without a byte change to its own logic. Sealed reports are untouched and replay as before. Surfacing `narrative_check` and measured materiality (O4) in the report needs `report-builder@2`, which is deferred.
3. **Statistics provenance.** `schema_evidence(origin=…)` classifies each table separately for:
   - `planner_stats`: `present` (some `pg_stats` rows), `row_estimate_only` or `absent`;
   - `counters`: `live`, `reset_by_clone` or `unavailable`;
   - `freshness`: `never_analyzed`, `stale` (`n_mod_since_analyze` > 50 + 10% of rows, PostgreSQL's autovacuum analyze default, with a recorded analyze time), `not_stale` or `unknown`.

   Mode C context marks clone counters as reset and omits them from the summary text. Live tables that have a recorded analyze time keep their previous text.
4. **Bounded model reliability.**
   - Timeouts are retried once (other transient errors up to 3 times).
   - `LLMUnavailableError` keeps the transport cause.
   - A 404 or "no endpoints" is `LLM_MODEL_UNAVAILABLE`, which is not retried.
   - An optional free fallback model gets one full attempt when the primary is unavailable or still invalid after repair. There is no ping-pong, and quota, paid usage and rejected keys never reach it.
   - A per-run circuit breaker (`ModelHealth`, `LLM_CIRCUIT_THRESHOLD` = 2) skips a model after consecutive failed logical calls. When every model is open, agents fail fast with `LLM_CIRCUIT_OPEN` and spend no calls.
5. **Default model.** The pinned `nvidia/nemotron-3-super-120b-a12b:free` is the documented default; the code default already was. `openrouter/free` is discouraged as the primary and allowed only as a fallback. `llm/models.py` lists models with recorded evidence, and the worker warns at startup about any other model. `python -m querycure.llm.probe` checks a model with exactly one request, opt-in and never at startup.
6. **Run-level failure reason (O7).** If a run used the model and no call succeeded, `write_report` records `MODEL_UNAVAILABLE` with counts by cause. It goes into the run error, an `error` event in the sealed log, and `RunDetail.error_message`.
7. **Quota accounting (O6).** `DailyQuota` excludes `LLM_CONNECTION_ERROR` attempts.

## Consequences

- An LLM can still explain findings, but it can no longer put a figure, a scan type, a verification status or a recommendation in a record that the measurements contradict.
- Grounding is conservative. A sentence mixing one supported and one unsupported claim is removed whole. Prospective claims about scan types survive only in hypothesis mode or when hedged. False positives cost prose, never verdicts.
- Changed prompts mean re-recording. The Mode C context text changed (O3), and a recorded smoke finding claiming "index-only retrieval" for `SELECT *` is now removed (O2). The affected eval cases need re-recording with real calls, under the daily quota.
- `claims@1` is versioned in `narrative_check`. A behaviour change means a new checker version, recorded with new runs.
