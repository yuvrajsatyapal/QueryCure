# Phase 4 Report — Verification & Replay

- **Dates:** 2026-10-13 → 2026-10-13 (UTC)
- **Outcome (owner-reviewed 2026-10-16):** implementation complete. Exit criteria #1, #3 and #4 are met. #2 is met in the form TASKS T4.7 sets ("reproduced or a documented inconclusive"), but ROADMAP's stronger replay criterion ("agreeing verdicts and overlapping CIs") is only **partially demonstrated**: it held in part of the 14 measured pairs because of noisy measurements; see §5.
- **Owner decisions (2026-10-16):** D9 approved, margin kept at `m = 1.25` and not widened to raise reproduction success ([ADR-0023](../../engineering/adr/ADR-0023-d9-experiment-replay-equivalence-margin.md)). `bench@1`/`bench@2` semantics and every released replay contract stay as they are. The Mode C eval divergence stays documented as R19; `DIVERGED` is never a pass.
- **Tasks completed:** T4.1–T4.9 ([TASKS.md](../TASKS.md)), plus two owner-requested extras: the AI re-investigation start contract and `GET /runs/{id}/verifications`.
- **Tasks deferred:**
  - The re-investigation conclusion diff stays Post-MVP (REPLAY_ENGINE §10).
  - The model override on re-investigation is not implemented.
  - Idempotency-Key on `POST /experiments/{id}/replay` is not implemented.
- **Also done:** the four outstanding real-model evaluations, each with the pinned free model and no paid fallback (31 of 45 free requests used on 2026-10-13).
  - Phase 2 cases `orders_injection_in_schema` and `orders_plain_explain`: PASS. Phase 2 is now complete.
  - Phase 3 cases `orders_sandbox_composite_index` and `rewrite_trap_sandbox`: PASS when recorded.

## 1. What was implemented

**For a user:**
- A finished investigation now has a sealed final report. The UI and Markdown/JSON exports show the exact SQL, the approvals, measured results with their provenance, correctness, the auditor's review, a recommendation limited to the sandbox scope, limitations and next steps.
- Every number in the report carries a provenance label, and a "Why?" opens its lineage: evidence, artifact digest and JSON pointer, and the plan node.
- "Verify report" checks the stored record against its digests, with no model calls and no SQL.
- "Re-run experiment" re-measures an approved experiment in a fresh sandbox. The confirmation dialog shows the exact SQL. The page then compares the new measurements with the original.
- "Re-investigate" starts a new model run, with explicit consent.
- The tournament tab gains the Benchmark Auditor's verdicts and a plan diff (baseline vs candidate).

**Technically:**

| Capability | Modules | Notes |
|---|---|---|
| T4.1 schema | migrations `0011`, `0012` | `verification_results` (append-only, DB CHECK: downgrade-only), `investigation_reports`, `replay_manifests` (append-only), `replay_attempts` (state machine), artifact kind `replay_comparison` |
| T4.3 plan diff | `plans/diff.py`, `GET /runs/{id}/plans/diff` | Weighted, order-preserving child alignment (same relation outranks same node type). Output: merged preorder, metric deltas, `new_indexes_used` |
| T4.2 Benchmark Auditor | `audit/checks.py`, `audit/loader.py`, `agents/nodes/benchmark_auditor.py`, prompt `benchmark_auditor@1` | 11 deterministic checks, the key one being a re-score of stored blocks under the experiment's own rules. A failed check downgrades verified → inconclusive. An optional LLM narrative can only add cited downgrade concerns. `deterministic_only` on model failure |
| T4.4 reports | `reports/inputs.py`, `reports/builders/v1.py` (`report-builder@1`), `reports/renderers/md_v1.py` (`report-md@1`), `reports/registry.py`, `reports/provenance.py` | Pure and versioned. Reads records and events `1..cutoff` only. The unlabeled-number scan runs in tests and on real reports |
| T4.5 finalization | `replay/finalize.py`, `replay/events_digest.py` | One transaction: `run.concluded` → cutoff → events digest → report → manifest → seal → status → `report.ready`. Every terminal path calls it (graph, dead letter, configuration error, API cancel) |
| T4.6 report replay | `replay/report_replay.py`, `api/routers/reports.py` | Ordered checks. Every failure is collected, and the status is the most severe. Stored bytes must be canonical. Retired builders yield `verified_stored_only` |
| T4.7 experiment replay | `replay/experiment_replay.py`, `replay/comparison.py`, worker job `experiment_replay` | Preconditions are checked again. Same config and seed. Scored with the source engine's rules. New experiment, new samples. Drift bootstrap, verdict table, winner check, environment classes. The comparison is stored as content. The replay run is finalized and has its own manifest |
| Re-investigation | `POST /investigations/{id}/reinvestigate` | Consent, configured key, free capacity. New `reinvestigation` run with a parent link, inputs by reference, its own budget |
| T4.8 UI | `components/report/*`, `components/replay/ReplayView.tsx`, `components/lineage/LineageDrawer.tsx`, `components/plan/PlanDiffView.tsx`, routes `/app/reports/[runId]`, `/app/replay/[runId]` | Mode-aware replay wording: cross-environment results are never called "reproduced". Archived-format fallback |
| T4.9 evals | `evals/recording.py`, `evals/runner.py`, `evals/scoring.py` | Mode C cases recorded. Live-measurement prompts can use a same-agent fallback, and a divergence gets its own status. Auditor metrics |

## 2. Important architecture decisions

| Decision | ADR / doc updated | Why |
|---|---|---|
| Auditor downgrade-only, enforced by a DB CHECK and by `domain.audit.audited` | ADR-0022 §1, DATABASE_DESIGN | A code bug cannot store an upgrade (ADR-0009) |
| Deterministic re-scoring before any LLM review | ADR-0022 §2, AGENT_SYSTEM | Catches records that drifted from their verdicts; the LLM adds concerns only |
| `run.concluded` content event | ADR-0022 §3, REPLAY_ENGINE §5, API_DESIGN | The builder depends only on sealed records, so rebuilds are byte-identical |
| Every terminal path finalizes; the terminal node emits no `node.completed` | ADR-0022 §4 | Nothing stays unsealed; nothing is written after the seal |
| Stored bytes must be canonical | ADR-0022 §5, REPLAY_ENGINE §2.4 | Re-canonicalization alone would hide whitespace edits (a test caught this) |
| `container_runtime` is material | ADR-0022 §6, REPLAY_ENGINE §9.3 | Since ADR-0020 the field is the measurement path (≈10× round-trip difference) |
| Replays scored by source rules, measured by the current engine | ADR-0022 §7 | Implements ADR-0019's compatibility rule |
| Comparison stored as content | ADR-0022 §8, migration 0012 | The replay run's report is rebuildable |
| Re-investigation start only | ADR-0022 §9, API_DESIGN | Owner request; the diff stays Post-MVP |
| Live-measurement eval replay → `DIVERGED` | ADR-0022 §10, TESTING_STRATEGY, RISKS R19 | Fresh measurements change prompts and control flow; never report that as a pass |
| D9 margin stays 1.25 (accepted 2026-10-16) | [ADR-0023](../../engineering/adr/ADR-0023-d9-experiment-replay-equivalence-margin.md), REPLAY_ENGINE §9.1 | Measured same-machine drift (§5) does not support widening it; a wider band would raise the reproduction rate only by weakening the equivalence test |

No released contract changed: `bench@1`/`bench@2` rules, canonicalization profiles, digest formats, interim builders, and stored Phase 1–3 artifacts are all untouched. Runs from earlier phases are not finalized and answer `not_replayable: not_finalized`.

## 3. Files changed
112 files, +14,001/−157 lines since `cbe6e18` (before the docs commit).

| Area | Files / modules | Notes |
|---|---|---|
| Migrations | `0011_verification_and_replay.py`, `0012_replay_comparison_artifact.py` | 0011 was pushed first; the artifact kind went into 0012 instead of editing a published migration |
| Auditor | `audit/`, `domain/audit.py`, `agents/nodes/benchmark_auditor.py`, `agents/prompts/benchmark_auditor.py`, `agents/outputs.py`, `db/repositories/verification.py`, `agents/graph.py`, `agents/nodes/optimization_loop.py` | |
| Reports and finalization | `reports/inputs.py`, `reports/builders/v1.py`, `reports/renderers/md_v1.py`, `reports/registry.py`, `reports/provenance.py`, `replay/finalize.py`, `replay/events_digest.py`, `agents/nodes/write_report.py`, `agents/run.py`, `agents/runtime.py` | |
| Replay | `replay/report_replay.py`, `replay/experiment_replay.py`, `replay/comparison.py`, `db/repositories/replay.py`, `jobs/handlers.py` | |
| Engine (additive) | `benchmark/engine.py` (`total=` override for re-scoring, `engine_version=` passthrough), `db/repositories/optimization.py` (`replay_of_experiment_id`), `replay/artifact_store.py` (`get_artifact_by_id`, `load_json`, sealed `link`) | Defaults unchanged |
| API | `api/routers/reports.py`, `api/schemas/replay.py`, `api/routers/runs.py`, `api/routers/investigations.py`, `core/errors.py` | |
| Frontend | `lib/api/reports.ts`, `lib/report/*`, `components/report/*`, `components/replay/ReplayView.tsx`, `components/lineage/LineageDrawer.tsx`, `components/plan/PlanDiffView.tsx`, `components/tournament/TournamentPanel.tsx`, `components/investigation/*`, `lib/events/*`, two routes, `e2e/phase4-lifecycle.spec.ts`, `playwright.config.ts` (one worker) | |
| Evals | `evals/recording.py`, `evals/runner.py`, `evals/scoring.py`, `evals/__main__.py`, four new recordings | |
| Analysis | `docs/engineering/analysis/replay_variance/` | Script, 14 raw result files, README |

## 4. Tests executed (real output, 2026-10-13, PostgreSQL 17 + sandbox, Python 3.12, Node 22)

| Suite | Command | Result | Notes |
|---|---|---|---|
| Unit | `QC_REQUIRE_DB=1 uv run pytest -q tests/unit` | **727 passed, 1 xfailed** | The strict xfail documents R18 (unchanged) |
| Integration | `QC_REQUIRE_DB=1 uv run pytest -q tests/integration` | **418 passed** | Real metadata DB as `qc_app` and the real sandbox |
| Security | `QC_REQUIRE_DB=1 uv run pytest -q tests/security` | **123 passed** | |
| Backend total | `QC_REQUIRE_DB=1 uv run pytest -q` | 1268 passed, 1 xfailed | ruff, format and `mypy --strict` (185 files) clean |
| Evals, smoke (CI) | `uv run python -m querycure.evals run --suite smoke` | **5/5 PASS**, 0 diverged | Now runs in the CI integration job |
| Evals, full replay | `… run --suite full --save-results` | 5 PASS, 2 DIVERGED (Mode C, by design), 1 FAIL (`rewrite_trap_not_in`, never recorded) | [results](../../../backend/evals/results/20261013T173814Z-full-replay-nvidia_nemotron-3-super-120b-a12b_free.json) |
| Evals, recorded | `… --mode record …` | Phase 2: 2/2 PASS (13 calls). Phase 3 Mode C: 2/2 PASS (18 calls) | `orders_sandbox_composite_index` → `verified_recommendation` with the real auditor; `rewrite_trap_sandbox` → `inconclusive`, never verified |
| Frontend | `pnpm lint && pnpm typecheck && pnpm test && pnpm build` | **78 passed** (10 new), build OK | Needs Node 22: jsdom 30 does not load under the shell's default Node 20 |
| E2E | `pnpm exec playwright test` | **3 passed** | Includes the full lifecycle (§5) |
| CI | GitHub Actions | Green on the final commits; two earlier failures | `b0a03ba` had a lint error (fixed in `c7f5e8f`). `462a40a`'s e2e job failed because the Phase 3 sandbox spec's regex did not accept the `verified_with_noise_warning` badge that a noisy CI runner produced; fixed in the closing commit |

**Auditor downgrade rate (ADR-0009).**
- Verified-path case `orders_sandbox_composite_index` (recorded with the real model): 0 downgrades out of 1 verified candidate.
- Real-sandbox integration tests: a cited downgrade concern moved a real `verified_with_noise_warning` result to `inconclusive`, and nothing else changed.
- From now on, eval metrics record `audited_verdicts`, `audited_verified_by_engine` and `auditor_downgrades` per case.

## 5. Acceptance criteria

| Criterion (ROADMAP Phase 4) | Status | Evidence |
|---|---|---|
| 1. Report replay makes 0 LLM calls and all hashes verify; tampering one artifact fails replay | **Met** | `test_report_replay.py`: LLM transports patched to raise. All 10 codes are reached by fixtures: manifest missing, manifest digest mismatch, unsupported schema, unsupported profile, artifact purged, artifact digest mismatch, events purged, events gap, events digest mismatch, rebuild mismatch. A whitespace-only manifest edit fails too. The Playwright lifecycle shows "Integrity check passed against stored digests" |
| 2. Experiment replay on `orders_ecommerce` gives agreeing verdicts and overlapping CIs on the same machine | **Partially demonstrated.** Implementation complete and TASKS T4.7 ("reproduced or documented inconclusive") met; ROADMAP's stronger wording held only in part, because of noisy measurements. Margin unchanged at 1.25 (ADR-0023) | 14 same-machine pairs ([analysis](../../engineering/analysis/replay_variance/README.md)). 1 `reproduced` (container path), 1 `drift_undetermined`, 12 `inconclusive` from the gate-4 noise check, **0 `not_reproduced`**. Verdicts agreed in 7 of 14 pairs (2 both verified). Speed-up CIs overlapped on every parameter set in 12 of 14. Fingerprints always matched. Through the API: `test_experiment_replay.py` and Playwright |
| 3. `index_regression` → `rejected: regression`; `no_benefit` → never `verified_recommendation` | **Met** | `test_benchmark_eval_table.py` (integration, passing). The Mode C eval `rewrite_trap_sandbox` ended `inconclusive` |
| 4. Every number in the report has provenance | **Met** | `reports/provenance.unlabeled_numbers` returns empty on 9 report shapes (unit), on reports sealed in integration tests, and on the exported Markdown (`test_report_replay.py`). JSON measurements carry `provenance`, `evidence_id` and `source` {artifact digest, pointer} |
| Lifecycle E2E (owner): workspace → investigation → agents → candidate → approval → sandbox experiment → audit → final report → report replay; experiment replay through the real API, worker and sandbox | **Met** | `e2e/phase4-lifecycle.spec.ts` (stub LLM, real stack), also in CI |

## 6. Known limitations
- **Noise.** On Docker Desktop most single experiments and most replays end `inconclusive`: the gate-4 robust-CV check fails for a sub-millisecond candidate arm (R1). Replay inherits this by design.
- **Mode C evals cannot replay green** (R19, kept open by the owner on 2026-10-16). The recorded runs are the scored evidence. Replay checks the deterministic prefix, then reports `DIVERGED`, which is never counted as PASS.
- **Partial reports for early stops.** A run that dead-letters or is cancelled before `write_report` has no synthesis summary or materiality in its report, because those lived in graph state. The report still lists findings, hypotheses and evidence.
- **No migrations for old runs.** Runs from Phases 1–3 have only interim reports and are never retro-sealed (`not_finalized`), by design.
- **Not implemented:** re-investigation model override; the conclusion diff (Post-MVP); Idempotency-Key on experiment replay.
- **UI gaps:** the UI shows the latest run of an investigation. Replay runs are reached from the replay page and `/app/reports/[runId]`; there is no run picker yet.
- **Integrity is not authenticity** (REPLAY_ENGINE §6): no manifest signing (D8).
- **Tooling:** the frontend unit tests need Node 22; the local shell defaults to Node 20.

## 7. Security considerations
- New controls, each with a test:
  - sealing (emitter, `link()`, repositories, append-only grants on three new tables);
  - the downgrade-only DB CHECK;
  - replay re-validation (DDL allowlist plus approved-digest comparison in the API, approval-digest enforcement in the engine);
  - explicit consent for experiment replay (exact SQL shown) and for re-investigation;
  - zero LLM calls in both replays (transports patched to fail);
  - user scoping of every new endpoint (404 tests).
- Unchanged:
  - only the sandbox executes candidate SQL, after approval;
  - no target-database DDL;
  - secrets never enter reports, which are built from records that never held them;
  - SSRF and the inspection gateway are untouched.
- Residual risks:
  - an attacker with database write access can rewrite records and digests consistently (D8);
  - auditor concerns are model text, fenced and cited, and can only downgrade.

## 8. What I should study
1. `replay/finalize.py`: why `run.concluded` comes before the cutoff and the status change after it; how one transaction gives idempotency. See LEARNING Phase 4.
2. `replay/events_digest.py` and `replay/report_replay.py`: gap detection, ordered checks, severity, why stored bytes must be canonical.
3. `reports/builders/v1.py` and `reports/renderers/md_v1.py`: purity, field presence, provenance on every number.
4. `audit/checks.py`: re-scoring from persisted blocks with the stored totality, and the `audited()` transition.
5. `agents/nodes/benchmark_auditor.py`: the deterministic audit is recorded even when the run stops mid-review.
6. `replay/comparison.py`: the equivalence-style classification, the seeded bootstrap of a ratio of ratios, environment classes.
7. `replay/experiment_replay.py`: preconditions, the approval created from consent, conditional attempt transitions, crash resume.
8. `plans/diff.py`: weighted LCS alignment of plan children.
9. `evals/recording.py`: record/replay of non-deterministic systems, and why `DIVERGED` is not a pass.

## 9. Interview-relevant implementation details
1. **Sealing a run without circular hashes.**
   - Problem: the report must embed the events digest, and the manifest must embed the report digest.
   - Options: a snapshot of builder inputs, or rebuilding from records.
   - Choice: a `run.concluded` content event closes the log, so the builder is a pure function of sealed records.
   - Test: fault injection after each of five steps leaves the run untouched, and the rebuild is byte-identical.
2. **A verifier that canonicalization fooled (bug).** The first report-replay test appended a space to the stored manifest, and replay still said `verified`: re-canonicalizing JSON erases whitespace. The fix requires the stored bytes to equal their canonical form *and* to match the digest.
3. **An auditor that cannot lie upwards.**
   - Authority is asymmetric: deterministic rules decide, and the LLM may only add cited downgrade concerns.
   - It is enforced three times: `audited()`, the node logic, and a database CHECK.
   - The strongest check needs no LLM: re-score the stored samples with the experiment's own engine version.
4. **Reproducibility needs an equivalence test.**
   - Overlapping CIs mean "no evidence of a difference", which is not the same as reproduced.
   - The drift CI must sit inside [0.8, 1.25].
   - On a laptop that gave 1 reproduced pair out of 14 and 12 honestly inconclusive, rather than 12 false "reproduced".
5. **A canonical-JSON range bug.** The first replay crashed storing a 64-bit bootstrap seed: qc-json-v1 refuses integers beyond ±(2^53 − 1). The fix: a 52-bit seed and a docstring explaining why.
6. **Record/replay meets live measurements.** Mode C eval replays diverge because new measurements create new evidence IDs, so the recorded auditor citations no longer resolve and the run takes another path. Instead of fabricating answers or calling it a pass, the runner reports `DIVERGED` and scores those cases at recording time.

## 10. Remaining work
- **D9:** closed 2026-10-16 ([ADR-0023](../../engineering/adr/ADR-0023-d9-experiment-replay-equivalence-margin.md)): `m = 1.25`, not widened.
- **Phase 5 priorities carried forward by the owner** (Phase 5 not started; needs authorization):
  1. Idempotency-Key support on `POST /experiments/{id}/replay`.
  2. Reliable deterministic/offline Mode C evaluation fixtures, so Mode C cases can be checked without live measurements (R19).
  3. Run picker and replay navigation in the investigation view.
  4. Remaining deployment and security hardening (ROADMAP Phase 5, incl. manifest signing D8).
- Other Phase 5 candidates: re-investigation model override; demo gallery with prerecorded replays.
- `rewrite_trap_not_in` (full suite) was never recorded. It is optional, from Phase 2.
- Risks updated: R19 added (kept open); R1 is unchanged and also limits replay.
