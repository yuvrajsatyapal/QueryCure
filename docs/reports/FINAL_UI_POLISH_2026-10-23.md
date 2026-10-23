# Final UI polish: audit and specification (2026-10-23)

Scope: polish after UI Passes 1–4 (`e8da80b`). No redesign, no new feature area. Frontend only; every item below reads data the API already returns. No backend, contract, schema, benchmarking, `claims@1`/`claims@2` or sealed-report change.

## 1. Audit

| Area | Already implemented | Gap |
|---|---|---|
| Results hierarchy | Header shows status pill and the outcome as small muted text. The verdict block (outcome, deterministic headline, recommendation badge, primary measurement, callouts) exists only inside the **Report** tab. Default tab is **Findings**. | A finished run opens on hypotheses; the recommendation, its verdict, its CI and the limitations need a tab switch. |
| Candidate readability | Candidates appear as `oc_70a238eea02a` plus the raw DDL in muted mono (tournament, analytics, report rounds); the approval card shows the kind label. | No short human description. Analytics rows (distribution, forest plot) show only the key. |
| Statistical explanations | `VERDICT_EXPLANATION` in the report; warnings in words (§3.17). | IQR, robust CV, CI, transport floor and speedup are never defined in the UI. Nothing says "faster" is not the same as "verified". |
| Result correctness | Backend records per arm × param set an `ArmFingerprint` (`rows`, `multiset`, `ordered`, `truncated`) and `consistent`, plus `order_is_total`, in `ExperimentResult` (`GET /experiments/{id}`). Gate 3 of the rules (`benchmark/rules.py`) is the correctness gate, so `RuleVerdict.gate` tells whether correctness passed (`null` or ≥ 4), failed (`3`, with reason and detail) or was not reached (`1`, `2`). `correctness_check` evidence and the report's `correctness` rows use "same rows" = equal `rows` and `multiset`. | UI_UX §3.8 "Correctness panel" not built. **Frontend-only is possible**: no new field is needed. |
| Responsive / a11y | axe in light and dark on investigation, plan, tournament, connections, palette; 390 px checks. | New elements must be covered. |

Backend gaps found (not fixed here, no approval requested because nothing below needs them):
- The per-param-set correctness outcome (`CorrectnessOutcome`) is not persisted; only the first failing param set reaches `RuleVerdict.reasons`. The panel therefore shows the recorded fingerprints per param set and the gate-3 outcome per candidate, and says that only the first failure is recorded.
- Whether the query has an `ORDER BY`/`LIMIT` is not in the result; only `order_is_total` is. The panel words the order rule from `order_is_total` alone.

## 2. Specification

### 2.1 Result summary (investigation page)
- Component `ResultSummary`, placed between the page notices and the trace/results grid, shown only when the selected run has a sealed report (`GET /runs/{id}/report`, the same query key as the Report tab, so one fetch). Not shown while the run is active, for unsealed runs (pre-Phase-4, `NOT_FINALIZED`) or unsupported report schemas; the Report tab keeps explaining those.
- Content, in reading order, all from the sealed report as stored (nothing recomputed):
  1. Outcome label and the deterministic headline.
  2. Recommendation: verdict badge, candidate description (§2.2) and key, then the primary measurement: param set, speedup, 95% CI, provenance. Then `VERDICT_EXPLANATION` for the status.
  3. Warnings as callouts: sandbox only, prerecorded, stub model, partial. Then **every** recorded limitation (not truncated).
  4. Actions: "Full report" (Report tab), "Benchmark details" (Tournament tab, sandbox runs only).
- The AI-written summary stays in the Report tab (not duplicated here).

### 2.2 Candidate descriptions
- `describeCandidate({ kind, ddl, querySql })` in `lib/benchmark/candidate.ts`, pure and deterministic, parsing only the three allowlisted DDL forms (`sql/ddl_allowlist.py`):
  - `CREATE INDEX … ON t [USING m] (a, b) [INCLUDE (c)] [WHERE p]` → "Index on t (a)", "Composite index on t (a, b)", plus "· hash" (non-btree method), "· includes c", "· partial".
  - `CREATE STATISTICS [(kinds)] ON a, b FROM t` → "Extended statistics on t (a, b) · dependencies".
  - `ANALYZE t [(cols)]` → "Refresh planner statistics on t".
  - `query_rewrite` → "Query rewrite".
  - Several statements → joined with " + ". Anything unparseable → the kind's generic label ("Index candidate"), never a guess.
- Shown next to the key (key kept, mono) in: tournament ranking, benchmark comparison heading, analytics verdict list, approval card, report rounds, result summary.

### 2.3 Statistical explanations
- `StatsGlossary` (`<details>`, closed by default, "How to read these numbers") in the Tournament tab, text in `lib/benchmark/glossary.ts`: speedup, 95% CI, IQR, robust CV, transport floor, p95, and "Faster is not verified": a verified recommendation also needs identical result rows on every param set, every rule gate, no auditor downgrade, and, when noisy, agreement of independent experiments.
- Existing warnings and attribution unchanged.

### 2.4 Result correctness panel
- `correctnessView(result, arm)` in `lib/benchmark/correctness.ts` (TDD), shown under "Benchmark comparison" for the selected candidate:
  - Outcome from the rule verdict's gate: *Passed* (gate `null` or ≥ 4) "same rows as the baseline on every param set (tested data only, not SQL equivalence)"; *Failed* / *Inconclusive* (gate 3) with reason words and the recorded detail; *Not reached* (gate 1–2); *Not evaluated* (no verdict).
  - Order rule from `order_is_total`.
  - Per param set: baseline rows, candidate rows, same rows (rows + multiset hash, as the backend's `correctness_check`), same order (ordered hash), each arm's consistency and truncation, and short hashes (full hash in the accessible name).
  - Missing fingerprint → "no successful execution", never "match".
- Never claims "correct" or "equivalent".

### 2.5 Verification
Unit tests first for `describeCandidate`, `correctnessView`, `ResultSummary`; e2e additions to the sandbox-approval spec (summary, correctness panel, glossary, axe light/dark, 390 px). Lint, typecheck, unit, build, full Playwright against local Docker with the stub model.

## 3. Results

Implemented as specified (UI_UX §3.18). Files: `lib/benchmark/{candidate,correctness,glossary}.ts`, `components/report/ResultSummary.tsx`, `components/tournament/{CorrectnessPanel,StatsGlossary}.tsx`, wired into `InvestigationView`, `TournamentPanel`, `BenchmarkAnalytics`, `ApprovalCard`, `ReportView` (`Callout` exported, report rounds show the description). No backend, schema, contract, benchmarking, sealed-report or claims change; no new dependency.

**Change found in browser verification:** the first wording for a run without a verified recommendation ("none was measured as an improvement") over-claimed: an inconclusive run can be noisy or auditor-downgraded. It now says "No recommendation was verified" and points to the per-candidate verdicts.

### Verification (all local, stub model, local Docker; no Neon, no paid calls)

| Check | Result |
|---|---|
| Unit tests written first (red, then green) | `candidate` 6, `correctness` 8, `ResultSummary` 2, panel/glossary render 2 |
| `pnpm lint`, `pnpm typecheck` | clean |
| `pnpm test` | 40 files, **230 passed** (was 212) |
| `pnpm build` | passed (twice, before and after the wording fix) |
| Playwright, full suite | **18/18 on two consecutive runs** (1.0 min, 53.7 s), 0 server 500s or tracebacks in either log. `sandbox-approval.spec.ts` now also checks the approval-card description, the result summary (heading, sandbox callout, Full report → report article, Benchmark details → tournament), the ranking description, the correctness panel and fingerprint table, and the glossary, with axe (WCAG 2.1 A/AA) in light and dark and no sideways scroll at 390 px |
| Unchanged behaviour | `investigation.spec.ts` (trace → evidence → plan node, Cited by) and `phase4-lifecycle.spec.ts` (audit, report, verify, replay) pass unchanged; benchmark statistics and verdicts are read, never recomputed (the analysis unit tests on the recorded result still pass) |
| Browser check | e2e sandbox run at 1366 px dark and light and 375 px dark: summary, ranking, correctness panel (20/20 and 7/7 rows, matching hashes, auditor downgrade shown separately), no horizontal scroll at 375 px; no app console errors |

### Limitations
- The summary needs a sealed report; unsealed (pre-Phase-4) runs show only the header outcome, as before.
- The correctness panel cannot show a per-param-set engine outcome (not persisted; §1).
- Keyboard and screen-reader behaviour of the new elements is covered by axe and native elements (`<details>`, buttons, tables with captions, focusable scroll region); no manual screen-reader session was run.
