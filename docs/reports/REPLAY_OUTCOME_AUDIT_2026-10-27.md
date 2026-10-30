# Experiment replay outcome audit and correction proposal (2026-10-27)

Read-only audit at `dd63b24` (`main`, local). It traces how an experiment replay run gets its sealed outcome and recommendation, checks the reported inconsistency against the code and the local Docker metadata DB, and proposes a versioned correction. **Status: design approved by the owner 2026-10-30 (§13); implementation authorized for the classifier and the source snapshot only, not activated. §13 supersedes §12, and §12 supersedes §6.2, §8, §9 and §11 where they differ. The backend defect is not resolved.** Nothing in the backend, API, schema, report builders, renderers, replay engine or any sealed artifact was changed.** The local DB was queried only inside `BEGIN READ ONLY … ROLLBACK`. No production or Neon access.

## 1. Executive summary

A sealed experiment replay report can say *Verified recommendation* in its headline, *No change is recommended* under Recommendation, and *inconclusive* under Experiment replay, all at once. The cause is that three different questions are answered from three unrelated sources, and none of them is the one the replay is about:

| Report field | Answers | Source today |
|---|---|---|
| `outcome` / `headline` | "Did this replay verify a recommendation?" | `execute_experiment_replay` → `_close(outcome=VERIFIED_RECOMMENDATION if result.winner else INCONCLUSIVE)`: the replay's **own single engine run** has any `verified` arm |
| `recommendation` | "Which candidate is recommended?" | `report-builder@1` `_winner()` over the **replay run's own** `optimization_candidates`, which never exist for a replay → always `status: "none"` |
| `replay.comparison.status` | "Did the replay reproduce the original?" | `compare_experiments` (REPLAY_ENGINE §9) — the only replay-specific answer, but it decides nothing else |

Neither the source run's sealed outcome nor the comparison status feeds the replay's outcome. So a replay can **upgrade** an inconclusive investigation to `verified_recommendation` on the strength of one sandbox experiment that skipped replication (ADR-0019), the Benchmark Auditor (ADR-0009) and the materiality gate (ADR-0017). Locally this happened 28 times.

Recommended correction (smallest complete one): **(a)** classify a new replay run's outcome from the source run's sealed outcome and the comparison status, so a replay can confirm or fail to confirm the original but never upgrade it; **(b)** snapshot the source run's verified outcome and recommendation into the replay run's own records at start; **(c)** release `report-builder@2` + `report-md@2` (report schema 2, additive) that build replay reports from (a) and (b) and reference the original candidate with its provenance; **(d)** let the frontend render schema 2 and annotate, without changing, sealed `report-builder@1` replay reports. No migration, no API change, no new dependency, no rewrite of any sealed report.

## 2. Verified findings

### 2.1 Local data (metadata DB, read only, 2026-10-27)

The earlier count of 91 is now **94** replay runs (3 were added by this session's screenshot harness, all sealed `inconclusive`). The ratios hold:

| Check | Result |
|---|---|
| Replay runs / sealed | 94 / 94, all `report-builder@1`, none deleted |
| `optimization_candidates` / `verification_results` rows owned by replay runs | **0 / 0** |
| Sealed `verified_recommendation` | **56** (47 comparison `inconclusive` + 9 `reproduced`) |
| Sealed `inconclusive` | 38 (all comparison `inconclusive`) |
| Sealed JSON `recommendation.status` / `candidate_key` | **`none` / null on all 94**, whatever the outcome |
| Comparison statuses seen | only `reproduced` (9) and `inconclusive` (85: `insufficient_evidence` 60, `drift_undetermined` 10, `verdict_inconclusive` 15) — `not_reproduced`, `not_replayable` and `failed` comparisons are **code paths only, no local data** |

Replay outcome against the source run and the two engine results:

| Replay sealed outcome | Source sealed outcome | Replay engine winner | Source engine winner | Source replicated | Source candidate status | Runs |
|---|---|---|---|---|---|---|
| `verified_recommendation` | `inconclusive` | yes | no | no | `inconclusive` | **25** |
| `verified_recommendation` | `inconclusive` | yes | no | yes | `inconclusive` | **3** |
| `verified_recommendation` | `verified_recommendation` | yes | yes | no | `verified` | 19 |
| `verified_recommendation` | `verified_recommendation` | yes | no | yes | `verified_with_noise_warning` | 9 |
| `inconclusive` | `verified_recommendation` | no | yes | no | `verified` | 8 |
| `inconclusive` | `inconclusive` | no | no | no / yes | `inconclusive` | 22 + 8 |

Of the 56 `verified_recommendation` replays: 28 replayed an investigation that verified nothing (an upgrade by one experiment), and 47 did not reproduce the original (comparison `inconclusive`). Only the 9 `reproduced` replays of verified sources are defensible, and even those seal an empty recommendation. Example: run `bcecb985…` (source outcome `inconclusive`, comparison `inconclusive: insufficient_evidence`); its sealed Markdown reads *"**Verified recommendation.** A candidate change was verified…"*, then *"No change is recommended."*, then *"Comparison: **inconclusive**"*, and its only next step is *"Re-run this experiment (experiment replay)…"* on a run that is itself a replay.

These numbers describe this developer database (stub and free-model runs at sf=0.01, mostly harness-driven). They show which code paths fire; they are not a reproduction rate.

### 2.2 Where each defect originates

| Affected field | Layer | Defect |
|---|---|---|
| Run/manifest/report `outcome` | **Classification** (`experiment_replay.py:535-537`) | Uses `result.winner` of the replay experiment. Ignores `comparison["status"]` and the source run's outcome. A comparison of `not_reproduced` or `not_replayable` (compare-time precondition) also seals `verified_recommendation` when the replay found a winner. |
| `headline`, `next_steps` | **Report building** (`builders/v1.py:358-391`) | Keyed only by `outcome`, written for investigation runs: claims "verified in an isolated sandbox", and proposes an experiment replay of the replay. |
| `recommendation` | **Report building** (`builders/v1.py:200-212, 279-303`) | Derived from the run's own candidates; replays have none, so always `none`. The original candidate is never referenced. |
| Contradictory Markdown | **Presentation of a built report** (`md_v1.py:62-90, 272-296, 298-330`) | Faithfully renders the three inconsistent fields. Not a renderer bug. |
| Result card / report page | **Presentation** (`ResultSummary.tsx:69,104`; `ReportView.tsx:306,320,419`) | Faithfully renders the sealed report. Not a frontend bug. |
| Run picker, trace events | **Presentation of the run row / events** (`RunPicker.tsx:106`; `lib/events/describe.ts:14,56`) | Show `verified recommendation` for these replays because the run row and `run.concluded` carry it. |
| Investigation list / dashboard | not affected | `start_replay` does not move `investigations.latest_run_id`, so lists keep showing the source run's outcome. |
| Execution, measurements, comparison | not defective | The replay experiment, engine verdicts and §9 comparison behave as specified. |

Secondary observations (not causes of the contradiction):

- `compare_experiments` applies `winner_changed` only when the original had a winner (`comparison.py:275-277`); a replay winner that the original never had is not flagged. Harmless once the outcome no longer comes from the replay winner.
- A replay re-runs only the source's primary experiment. For a `verified_with_noise_warning` source (three replicates, ADR-0019) the comparison is usually `insufficient_evidence` by construction. A known limitation, not addressed here.
- No test asserts a replay run's outcome or its sealed recommendation (`tests/integration/test_experiment_replay.py`, `tests/unit/reports/test_report_v1.py`), which is how this shipped.

## 3. Lifecycle and authoritative fields

```
POST /experiments/{id}/replay (api/routers/runs.py)
└─ experiment_replay.start_replay                          experiment_replay.py:165
   ├─ check_preconditions                                  :96   verify_report(source) must be ok; approval digests; sandbox
   ├─ INSERT investigation_runs (kind=experiment_replay, parent_run_id=source run)   :198
   ├─ link input.experiment_config / input.query / input.param_sets                  :210-230
   ├─ INSERT approval_requests (approved, round 0)                                   :232
   ├─ insert_attempt (replay_attempts, queued)                                       :255
   └─ queue.enqueue(experiment_replay)                                               :274
worker: jobs/handlers.py → execute_experiment_replay                                 :361
   ├─ create_experiment(replay_of_experiment_id=source)                              :410
   ├─ benchmark.engine.run_experiment (same config + seed, same engine version)      :436
   │    └─ verdicts per arm → tournament.rank → result.winner   (engine.py:406, tournament.py:58)
   ├─ store experiment.result, record evidence                                       :463-482
   ├─ comparison.compare_experiments → pairs, status, failure_code                   comparison.py:162, :287
   ├─ store replay.comparison, emit replay.compared                                  :502-525
   └─ _close(outcome = winner ? verified_recommendation : inconclusive)  ◄ DEFECT    :305, :526-540
        └─ finalize.finalize_run                                                     finalize.py:199
             ├─ emit run.concluded {final_status, outcome, …}  (last sealed event)   :227
             ├─ reports.inputs.load_report_inputs (records + events ≤ cutoff)         inputs.py:67
             ├─ registry.build(report-builder@1) → report JSON  ◄ DEFECT (rec/headline) builders/v1.py:215
             ├─ RENDERERS[report-md@1] → Markdown                                    md_v1.py
             ├─ investigation_reports (outcome, builder_version, …)                  :277
             ├─ manifest (final_status, outcome, report digests) + replay_manifests  :299-322
             └─ run row status/outcome, report.ready
read path:  GET /runs/{id}/report → ResultSummary / ReportView (frontend/src/components/report)
            report replay: replay/report_replay.verify_report rebuilds with the *stored* builder_version (:305-338)
```

Authoritative sources (REPLAY_ENGINE §5): a finalized run's terminal status and outcome are `final_status`/`outcome` **in its manifest**, which `finalize_run` copies from the `Conclusion`; the report JSON's `outcome` comes from the sealed `run.concluded` event; the run row and `investigation_reports.outcome` are copies. `recommendation` is computed only by the builder. The comparison is a stored artifact (`replay.comparison`) and the `replay_attempts.status`.

## 4. Semantics (proposed invariants)

Four distinct concepts. None implies another.

| Concept | Question | Authority | Lives in |
|---|---|---|---|
| **Original investigation outcome** | Did the investigation verify a recommendation from its own evidence? | Source run's sealed manifest `outcome` | Source run |
| **Candidate verification** | Did candidate *k* pass correctness and performance rules, after auditor downgrade and replication? | `optimization_candidates.status` / `verification_results` of the run that proposed *k* | Investigation runs only |
| **Recommendation** | Is a candidate supported well enough to recommend? | Builder, from a verified candidate of an investigation run | Investigation runs; a replay may only *reference* one |
| **Experiment replay outcome** | Did a new measurement reproduce the original experiment under §9? | `comparison.status` (= terminal `replay_attempts.status`) | Replay run |

Invariants:

- **I1. A replay never upgrades.** A replay run's outcome is never more favourable than its source run's sealed outcome.
- **I2. A replay never verifies a candidate and never creates a recommendation.** A replay engine verdict is a measurement (`verified` arm in this experiment), not a candidate verification: no auditor, no replication, no materiality gate.
- **I3. A replay confirms only by reproduction.** A replay may carry its source's outcome only when the comparison is a reproduction; otherwise it is `inconclusive`, and the comparison status says why.
- **I4. Every replay report names its source.** Source run, experiment, report digest and outcome, and the referenced candidate, all labelled with provenance `source_run`.
- **I5. Self-contained rebuild.** A replay report is a pure function of the replay run's own sealed records (the source facts are snapshotted into them), so report replay never depends on the parent run staying available.
- **I6. Sealed is sealed.** Existing reports, manifests, events and run rows are not edited; corrected semantics apply to new runs through a new builder version.

## 5. Options considered

| Option | Correctness | Migration risk | Complexity | Backward compat. | Replay determinism |
|---|---|---|---|---|---|
| A. Fix `_close` classification only | Outcome right; report still seals an empty recommendation and self-referential next steps, so a reproduced verified replay still reads *Verified* over *No change is recommended* | None | Small | Full | Unaffected |
| B. `report-builder@2` only | Report would disagree with the manifest/run-row outcome (builder reads `run.concluded`); overriding it breaks the §5 single authority | None | Medium | Full | Breaks authority rule |
| C. New outcome values (`replay_reproduced`, …) | Most expressive | **Migration**: CHECK constraints on `investigation_runs.outcome` and `investigation_reports.outcome` (0003, 0011), API enum, filters, labels | Large | Needs care in every outcome consumer | Unaffected |
| D. Frontend-only (hide the headline/recommendation on replays) | Hides, does not fix; sealed JSON/Markdown and exports still contradict | None | Small | — | — |
| **E. A + snapshot + `report-builder@2`/`report-md@2` + frontend schema 2 (recommended)** | Fixes outcome, recommendation and wording at their source | None (no DDL; one new artifact role, which is free text) | Medium | Full: v1 stays registered, old reports rebuild byte-identical | Preserved; replay reports become more self-contained |

## 6. Proposed architecture (option E)

### 6.1 Source snapshot at replay start

In `start_replay`, after `check_preconditions` has verified the source report (`verify_report` ok), store a canonical `qc-json-v1` artifact `kind = replay_source` and link it to the replay run as role `input.replay_source`:

```json
{
  "schema_version": 1,
  "source_run_id": "…", "source_experiment_id": "…",
  "source_manifest_sha256": "sha256:…", "source_report_json_sha256": "sha256:…",
  "source_builder_version": "report-builder@1",
  "source_final_status": "completed", "source_outcome": "verified_recommendation",
  "source_recommendation": { "status": "verified", "candidate_key": "c1", "kind": "create_index",
    "sql_sha256": "…", "ddl": ["…"], "query_sql": null, "round": 0,
    "primary_measurement": { "...": "copied from the source report, with its source evidence_id" } }
}
```

Values are copied from the source's stored, just-verified report JSON and manifest, never recomputed. It is part of the replay's manifest (`artifacts`), so its digest is sealed with the replay.

### 6.2 Replay outcome classification (new runs)

A pure function `replay_run_outcome(source_outcome, comparison_status)` used by `_close`:

| Comparison status | Run status | Run outcome |
|---|---|---|
| `reproduced` | completed | **source outcome** (I3) |
| `reproduced_with_drift` | completed | source outcome — **decision D1** |
| `inconclusive` | completed | `inconclusive` |
| `not_reproduced` | completed | `inconclusive` — **decision D2** |
| `not_replayable` (compare-time) | completed | `inconclusive` — **decision D3** |
| `failed` | failed | none (unchanged) |
| execution failure / cancel | failed / cancelled | none (unchanged) |

`result.winner` no longer influences the outcome. The source outcome comes from the snapshot (6.1).

### 6.3 `report-builder@2`, report schema 2, `report-md@2`

- New `reports/builders/v2.py` and `reports/renderers/md_v2.py`; `registry.CURRENT_BUILDER/RENDERER/SCHEMA_VERSION` move to `@2`/`2`. `v1` and `md_v1` stay registered and untouched, so sealed v1 reports still rebuild byte-identical.
- For non-replay runs, v2 output equals v1 except `schema_version`/`builder_version` (v2 may reuse v1's frozen helpers; v1 is never edited).
- `ReportInputs` gains `replay_source: dict | None = None`, loaded from `input.replay_source`. v1 never reads it, so v1 rebuilds are unaffected (guarded by a golden test).
- For `experiment_replay` runs, schema 2 adds a top-level `replay_result` (additive; all schema-1 fields keep their types):

```json
"replay_result": {
  "status": "reproduced", "failure_code": null, "comparison_mode": "same_environment",
  "source": { "run_id": "…", "experiment_id": "…", "outcome": "verified_recommendation",
              "report_json_sha256": "sha256:…", "provenance": "source_run" },
  "replay_engine_winner": "c1", "replay_engine_winner_provenance": "measured"
}
```

- `recommendation` on a replay: when the run outcome is `verified_recommendation` (only possible via I3), it is the **source** recommendation with `"origin": "source_run"`, `source_run_id` and its source evidence IDs; otherwise `status: "none"`. Never derived from the replay's own engine winner — **decision D4**.
- Headline and next steps keyed by (comparison status × source outcome), e.g. *"The original verified recommendation was reproduced by a new sandbox measurement."*, *"The replay could not confirm the original result (insufficient evidence)."*, *"The original investigation verified no recommendation; this replay re-measured it and makes none."* No self-referential "replay this experiment" step except after an `inconclusive` comparison.
- Missing comparison (`replay.comparison` absent) or missing snapshot (should be impossible for v2 runs) → headline says so, `recommendation.status: "none"`, entry in `missing`.

### 6.4 Frontend

- `SUPPORTED_REPORT_SCHEMAS = [1, 2]`; types for `replayResult`. Until this ships, schema 2 already falls back to the stored Markdown (REPLAY_ENGINE §7.4), so deploying the frontend first or together is safe.
- `ResultSummary` / `ReportView`: on replay reports show the replay status as its own line (*Reproduced*, *Reproduced with drift*, *Not reproduced*, *Inconclusive*) with a link to the source run, and the referenced candidate labelled *from run N*.
- Sealed `report-builder@1` replay reports: rendered exactly as stored, plus a fixed, clearly separated note derived only from stored metadata (`builder_version == report-builder@1 && run.kind == experiment_replay`): *"Built by report-builder@1: this headline comes from the replay's own measurement, not from the comparison with the original. See Experiment replay for reproducibility."* — **decision D5**. No value in the report is changed or recomputed.

### 6.5 Not changed

No migration, no DB schema change, no API endpoint or response-model change (the report JSON is passed through), no change to the benchmark engine, comparison algorithm, margin (ADR-0023), canonicalization profiles or finalization protocol. New docs: REPLAY_ENGINE §8.2 gains "Replay run outcome and report", §7 lists `report-builder@2`/`report-md@2`; a new ADR-0032 records I1–I6 and the decisions below; DECISIONS.md indexes it.

## 7. Historical sealed reports

- All 94 local replay reports (and any elsewhere) stay as sealed: same JSON/Markdown bytes, digests, manifests, `run.concluded` events and run rows. Report replay keeps rebuilding them with `report-builder@1`/`report-md@1` and they keep verifying.
- Their stored `outcome` is not reinterpreted. The only addition is the UI note in 6.4 (outside the sealed artifacts, decision D5).
- `run_row_differs_from_manifest` cannot fire, because no row is touched.
- No backfill, no re-finalization. A user who wants a corrected replay starts a new experiment replay, which is sealed by v2.

## 8. Test matrix

All new-path cases: run outcome = `_close` result; recommendation/summary = builder@2 + md@2; provenance requirements apply to every case: `replay_result.source` names the source run, experiment and report digest with provenance `source_run`; replay measurements carry `measured`/`prerecorded`; the report rebuilds byte-identical under report replay.

| # | Case | Comparison | Run outcome | `recommendation` | Displayed summary |
|---|---|---|---|---|---|
| 1 | Source verified, replay reproduces | `reproduced` | `verified_recommendation` | source candidate, `origin: source_run` | Reproduced; original recommendation of run N reproduced |
| 2 | Source verified, replay drifts | `reproduced_with_drift` | per **D1** | per D1 (source candidate if D1 = source outcome) | Reproduced with drift: same verdict, effect size changed beyond ±25% |
| 3 | Source verified, replay contradicts (`verdict_changed`, `direction_reversed`, `winner_changed`) | `not_reproduced` | `inconclusive` (**D2**) | `none` | Not reproduced: reason code; original recommendation not confirmed |
| 4 | Source verified, replay inconclusive (`insufficient_evidence`, `drift_undetermined`, `verdict_inconclusive`) | `inconclusive` | `inconclusive` | `none` | Inconclusive: reason; original recommendation neither confirmed nor contradicted |
| 5 | Source inconclusive, replay engine has a winner | any | `inconclusive` (never verified; today 28 local cases seal verified) | `none` | Original verified nothing; replay measurement noted with provenance, makes no recommendation (**D4**) |
| 6 | Replay engine has no winner | any | as rows 1–4 by comparison | as rows 1–4 | Unchanged by the missing winner |
| 7 | Candidate correctness failure in the replay (fingerprint differs) | `not_reproduced: result_fingerprint_changed` | `inconclusive` | `none` | Not reproduced: result rows changed |
| 7b | Same correctness rejection on both sides | `reproduced` | source outcome (`inconclusive`) | `none` | Reproduced the original rejection |
| 8 | Source run or candidate unavailable at start | — | no run (`not_replayable`) | — | Precondition failure (**D6**: new code `source_unavailable` vs existing codes) |
| 9 | Compare-time precondition (workload digest / row profile changed) | `not_replayable` | `inconclusive` (**D3**) | `none` | Not comparable: precondition field |
| 10 | DDL fails in replay only | `failed: ddl_failed` | run failed, no outcome | `none` | Failed: ddl_failed |
| 11 | Comparison missing at finalization | — | `inconclusive` | `none` | No comparison recorded; `missing` entry |
| 12 | Existing sealed `report-builder@1` replay report | stored | stored (unchanged) | stored | Rendered as stored + v1 note (D5); report replay `verified` |
| 13 | New v2 report sealing | any | — | — | report replay rebuilds JSON and Markdown byte-identical; manifest contains `input.replay_source` |
| 14 | Non-replay run sealed by v2 | — | unchanged | unchanged | v2 JSON equals v1 except `schema_version`/`builder_version` (golden) |
| 15 | v1 golden rebuild with the new `ReportInputs.replay_source` field | — | — | — | every existing v1 fixture rebuilds byte-identical |
| 16 | Frontend schema 2 / schema 1 / unknown schema | — | — | — | renders 2, renders 1 (+ note for replays), Markdown fallback for 3 |

Placement: pure classification and builder cases as unit tests (`tests/unit/replay/`, `tests/unit/reports/test_report_v2.py`) written first; snapshot, `_close` and sealing cases in `tests/integration/test_experiment_replay.py` with stub engine results; report replay for both builder versions in the existing report-replay integration tests; frontend in Vitest plus one e2e assertion on a replay report.

## 9. Decisions requiring approval

| # | Question | Recommendation |
|---|---|---|
| D1 | Does `reproduced_with_drift` confirm the source outcome? Same verdict and code, but the speed-up changed beyond ±25%. | Confirm the source outcome, and state the drift in the headline. The verdict reproduced; the size did not. |
| D2 | `not_reproduced` → `inconclusive`? The vocabulary has no "contradicted" outcome without a migration (option C). | Yes, `inconclusive` now; the replay status carries *not reproduced* explicitly. Revisit with option C if a distinct outcome is wanted. |
| D3 | Compare-time `not_replayable`: run `completed`/`inconclusive`, or `failed`? | `completed`/`inconclusive`: the measurement exists and is sealed; only the comparison is impossible. |
| D4 | May a replay report mention its own engine winner when the source verified nothing? | Yes, only in `replay_result` as a labelled measurement, never in headline/outcome/recommendation. |
| D5 | Annotate sealed v1 replay reports in the UI? | Yes, a fixed note from stored metadata only; no recomputation. |
| D6 | Precondition when the source run is soft-deleted or its report is unreadable | Treat as the existing `source_integrity_failed` unless a separate `source_unavailable` code is wanted (that would change REPLAY_ENGINE §8.2's code table). |
| D7 | Source outcome `no_action_needed` with a reproduced comparison | Carry it (I3 applies uniformly). Flagged because no local data exercises it. |
| D8 | Replays of noise-warning sources re-run only the primary experiment | Out of scope; document as a limitation in the v2 replay limitations text. |

## 10. Risks

- **Two builder versions in circulation.** Mitigated by the golden tests (14, 15) and by report replay already dispatching on the stored version.
- **v2 reusing v1 helpers.** Safe only while v1 is frozen (it is, ADR-0015); retiring v1 must not delete its code while v2 imports it.
- **Deploy skew.** A backend sealing schema 2 before the frontend accepts it shows the Markdown fallback, which is correct but plainer. Ship the frontend first or together.
- **Run picker and trace events** keep showing `verified recommendation` for old replays (run row and sealed events). Accepted under I6; the replay status could be added to the run picker later from `replay_attempts`.
- **Wording.** The new headlines are product copy; review them with the owner before release.

## 11. Implementation sequence (after approval)

Each step committed separately on `main`, with tests first and the verification commands from CLAUDE.md §7:

1. `replay_run_outcome` pure function + unit tests (cases 1–7, 9). No caller yet.
2. `input.replay_source` snapshot in `start_replay`; `ReportInputs.replay_source`; integration tests (8, 13 partial) and the v1 golden guard (15).
3. `_close` uses `replay_run_outcome`; integration tests per comparison status (1–7, 9–11).
4. `report-builder@2`, `report-md@2`, schema 2, registry bump; unit tests (1–11, 14) and report-replay tests for v1 and v2 (12, 13).
5. Frontend: schema 2 types and rendering, v1 replay note; Vitest + e2e (16).
6. Docs: REPLAY_ENGINE §7/§8.2, ADR-0032, DECISIONS.md, UI_UX §3.6, CURRENT_PHASE.

Steps 5 can land before 4 (it is safe against schema 1). Workstream 4 Stage 3 stays paused until the owner decides.

## 12. Design review and finalized contract (2026-10-27)

Owner design review of §§4–11, checked against REPLAY_ENGINE §§5, 7, 8.2, 9, ADR-0015, ADR-0019, ADR-0023 and the code at `94d8c18`. **Status: design finalized — awaiting explicit backend implementation approval.** No code, migration, API, dependency, sealed artifact or database row was changed; nothing was committed. Where this section differs from §6.2, §8, §9 or §11, this section wins.

### 12.1 What the review changed in the proposal

Reading the code turned up six facts the original proposal did not account for. Each changes the contract:

| # | Fact (where) | Consequence |
|---|---|---|
| R1 | The ±25% tolerance is not provisional. ADR-0023 accepted `m = 1.25` (owner decision D9, 2026-10-16) as a 95% bootstrap-CI equivalence test on the speed-up drift, and rules out widening it to raise the reproduction rate. | D1 uses the existing contract and statuses. Any other tolerance needs a new ADR. |
| R2 | `comparison_mode = cross_environment` must never be called "reproduced" (REPLAY_ENGINE §9.2). The proposal's §6.2 ignored the mode. | A `reproduced` comparison confirms the source only in `same_environment`. |
| R3 | A source run can itself be an `experiment_replay` run: `check_preconditions` accepts any finalized run with a completed experiment. Its outcome may be one of the 56 upgraded `report-builder@1` replays. | Carrying a replay source's outcome would launder an upgrade through a second replay. Replay sources never pass their outcome on. |
| R4 | A source's verified recommendation can rest on a different experiment than the one being replayed: another round, or a replicate (`check_preconditions` accepts both; `_winner` takes the measurement from the round's replicate-0 experiment). | The source outcome is carried only when the replayed experiment is the one whose measurement the recommendation cites: `recommendation.primary_measurement.source.artifact_sha256` equals the replayed source experiment's `result_sha256`. |
| R5 | Failed and cancelled source runs pass the preconditions when their experiment completed (they are finalized with a partial report). Their outcome is `NULL`, but a `completed` replay run must have an outcome (`CHECK` in migration 0003). | The replay seals `inconclusive`. |
| R6 | Sources with `no_action_needed` or `unverified_recommendations` cannot reach a replay today. `write_report.decide` returns `inconclusive` for any run that has an experiment row (`benchmarked`) before it considers `no_action_needed`, and the preconditions require a completed experiment. | D7 is kept as a rule for completeness. It is tested only at the pure-function level and documented as unreachable. No integration test can create that source honestly. |

Two simplifications to §6:

- **The classification basis is sealed, not recomputed.** `_close` stores the classifier's reason as an optional `replay_basis` object in the `run.concluded` payload. This follows the ADR-0026 `narrative_check` precedent: the key is written only for experiment-replay runs, so every other run's payload bytes are unchanged. `report-builder@2` maps that code to text and never re-runs the classification. The outcome, headline, recommendation and Markdown therefore all come from one sealed decision, so they cannot drift apart. The alternative (the builder re-runs the same pure function on the snapshot and comparison) would duplicate the decision inside a frozen builder. It was rejected.
- **`report-builder@2` wraps v1 instead of importing its private helpers.** `v2.build_report` calls the frozen `v1.build_report` and overrides only `schema_version`, `builder_version`, `recommendation.origin` and, for replay runs, `headline`, `next_steps`, `recommendation` and `replay_result`. Non-replay output equals v1 except those three fields, by construction.

### 12.2 D1–D8: final decisions

| # | Decision | Rationale | Conflicts / open |
|---|---|---|---|
| **D1** Performance drift | Comparison statuses stay as specified (REPLAY_ENGINE §9.1, ADR-0023). Each user-level state maps to one of them: *performance reproduced within tolerance* = `reproduced` (drift CI ⊂ [0.8, 1.25]); *correctness reproduced but performance materially drifted* = `reproduced_with_drift` (CI entirely outside the band); *not reproduced* = `not_reproduced`. A fourth state the brief left out is *correctness reproduced, performance undetermined* = `inconclusive` (`drift_undetermined`, `insufficient_evidence`, `verdict_inconclusive`). *Result correctness reproduced* is not an aggregate status today. Schema 2 adds the derived `replay_result.correctness_reproduced` = every pair compared and no pair `result_fingerprint_changed` (`null` when no pairs exist). **A drifted replay seals `inconclusive`**, keeps `reproduced_with_drift` as its comparison verdict, and cannot claim reproduction. | The original verified recommendation includes an effect size that passed the materiality gate (ADR-0017). Drift beyond the accepted margin means that effect was not reproduced. The run picker, trace events and `run.concluded` show only the outcome. If a drifted replay sealed `verified_recommendation`, those surfaces would show material drift as full confirmation, which is the "silent" classification D1 forbids. | **Reverses** the audit's §9 D1 recommendation (carry the source outcome). ±25% comes from ADR-0023, not from this decision. |
| **D2** Not reproduced | `not_reproduced` seals `inconclusive`: the CHECK constraints allow only four outcomes, and option C (new values) needs a migration. The comparison verdict `not_reproduced` and its code stay in `replay.comparison` and `replay_result` and lead the headline and the UI replay line: *Not reproduced: …; the original recommendation is not confirmed*. | `inconclusive` here means "this replay does not support the original conclusion". It does not mean "undecided between two outcomes". The explicit verdict carries the contradiction. | None. A distinct "contradicted" outcome stays possible later through option C plus an ADR. |
| **D3** Comparison unavailable | Compare-time `not_replayable` (workload digest or row profile changed), a missing comparison artifact, a missing or unreadable snapshot, and a source run with no outcome all seal `completed` / `inconclusive`. Each has a `replay_basis` code and a headline that names the reason. Reproduction is never inferred. | The new measurement exists and is sealed; only the comparison or its basis is missing. `failed` stays reserved for execution failures (REPLAY_ENGINE §8.2). | None. |
| **D4** Replay's own winner | Shown only as `replay_result.replay_measurement.engine_winner`, with the measurement provenance (`measured` / `prerecorded`) and the fixed label *replay measurement, not a verification*. It never drives the outcome, headline or `recommendation`, and `result.winner` is removed from `_close`. | A replay runs no auditor (ADR-0009), no replication (ADR-0019) and no materiality gate (ADR-0017). | None. |
| **D5** Historical reports | Every sealed `report-builder@1` report, manifest, event, row and digest stays byte-for-byte. `report-builder@1` and `report-md@1` stay registered and unedited. The UI may show a fixed note next to (never inside) a stored v1 replay report, selected only by `builder_version == "report-builder@1" && run.kind == "experiment_replay"`. Wording is in §12.3, row 11. | ADR-0015 freeze. Stored artifacts are the record (REPLAY_ENGINE §7 rule 1). | None. |
| **D6** Missing source run | No new code. A source that is not finalized gives `source_not_finalized`; a missing or unverifiable report or manifest gives `source_integrity_failed`, with `detail` naming the failed check. Both already exist. Two narrow hardenings, behind tests: (a) `check_preconditions` uses `.first()` instead of `.one()` for the source run row and returns `source_integrity_failed` (*source run missing*) instead of raising. This is reachable only by an integrity bug, because the API ownership query joins the run. (b) A source report JSON without the fields the snapshot needs gives `source_integrity_failed` (*source report unreadable*). A source removed after start is already handled: the worker raises `InvalidStateError`, the job dead-letters, and the attempt fails with its existing code. | Existing codes describe these cases accurately, and REPLAY_ENGINE §8.2's code table stays unchanged. | Observation, out of scope: `get_user_experiment` does not filter soft-deleted runs or investigations. |
| **D7** No-action original | A reproduced, same-environment `no_action_needed` source seals `no_action_needed`. Any other comparison gives `inconclusive`. A replay never produces `verified_recommendation` from it. | Owner decision. Sealing the source's outcome is a confirmation, never an upgrade. | Unreachable today (R6). Tested as a pure function only. |
| **D8** Noise-warning originals | A source whose recommendation status is `verified_with_noise_warning` can never be confirmed by a replay. The replay re-runs one experiment and cannot repeat the three-experiment agreement (ADR-0019). The outcome is `inconclusive`, basis `source_noise_warning`, and the limitation text says so. By construction the comparison is never `reproduced` anyway: the primary experiment's candidate verdict was `inconclusive`, so pairs are `verdict_inconclusive`. The explicit rule is defence in depth. | Never claim full reproduction where the original verification requirements were not repeated. | None. |

New decisions from the review (recommended; owner to confirm with the rest):

| # | Decision |
|---|---|
| **D9** | `reproduced` + `cross_environment` seals `inconclusive`, basis `cross_environment`, UI label *Consistent across environments* (REPLAY_ENGINE §9.2). It is never called reproduced. |
| **D10** | A source run of kind `experiment_replay` never passes its outcome on. Basis `source_is_replay`. Following the chain to the root investigation was rejected: it adds a recursive lookup, and v1 replay outcomes in the chain are unreliable. |
| **D11** | `verified_recommendation` is carried only when the replayed experiment is the recommendation's measured experiment (R4). Otherwise basis `recommendation_from_other_experiment`. |
| **D12** | A failed or cancelled source (outcome `NULL`) gives `inconclusive`, basis `source_not_completed` (R5). Such replays stay allowed: re-measuring a completed experiment is still meaningful, and blocking them would need a new precondition code. |

### 12.3 Replay outcome contract (new runs only)

Classifier, a pure function in a new module `replay/outcome.py`, evaluated in this order. The first matching rule wins.

```
classify(snapshot | None, comparison | None) -> (run_status, outcome | None, basis)
1  comparison is None                                   -> completed, inconclusive, comparison_missing
2  comparison.status == "failed"                         -> failed,    None,         comparison_failed
3  snapshot is None                                     -> completed, inconclusive, source_snapshot_missing
4  comparison.status != "reproduced"                    -> completed, inconclusive, comparison_<status>
5  comparison.comparison_mode != "same_environment"     -> completed, inconclusive, cross_environment       (D9)
6  snapshot.source_run_kind == "experiment_replay"      -> completed, inconclusive, source_is_replay        (D10)
7  snapshot.source_outcome is None                      -> completed, inconclusive, source_not_completed    (D12)
8  source_outcome == verified_recommendation:
     rec.status != "verified"                           -> completed, inconclusive, source_noise_warning    (D8)
     rec measured experiment != replayed experiment     -> completed, inconclusive, recommendation_from_other_experiment (D11)
     else                                               -> completed, verified_recommendation, reproduced_source_recommendation
9  source_outcome == no_action_needed                   -> completed, no_action_needed, reproduced_source_outcome (D7)
10 otherwise (inconclusive, unverified_recommendations) -> completed, inconclusive, reproduced_source_outcome
```

Execution failures and cancellation (`_fail`, `RunCancelledError`, dead letter, `cancel_replay_attempt`) do not reach the classifier. They are unchanged: run `failed` / `cancelled`, outcome `NULL`.

**Critical invariant (I1, enforced by the classifier):** the only rule that yields `verified_recommendation` is 8, and it requires a source outcome of `verified_recommendation` from a non-replay source. A replay never upgrades an investigation's verification status, and the replay's engine winner is not an input.

Decision table. *Outcome* = persisted run / manifest / report outcome. *Rec. provenance* = what `recommendation` holds. *Claim* = whether the report may say "reproduced".

| # | Case | Comparison verdict (stored) | Outcome | Rec. provenance | Headline (schema 2) | User-facing explanation | Claim |
|---|---|---|---|---|---|---|---|
| 1 | Verified original, reproduced, same environment, replayed experiment is the recommendation's | `reproduced` | `verified_recommendation` | source candidate, `origin: source_run`, source run ID, source evidence IDs | The original verified recommendation was reproduced by a new sandbox measurement. | Correctness and speed-up matched the original within ±25% (95% interval). This confirms the original recommendation from run N; the replay verified nothing new. | **Yes:** reproduction of the original |
| 2 | Verified original, performance drift | `reproduced_with_drift` | `inconclusive` (D1) | `none`; source candidate shown only in `replay_result.source_recommendation` | Same verdict and result rows, but the speed-up changed beyond ±25%: the original recommendation is not confirmed. | The direction and correctness held; the size of the effect did not, so the original claim is not confirmed. | No (correctness only) |
| 3 | Verified original, not reproduced (`verdict_changed`, `direction_reversed`, `result_fingerprint_changed`, `winner_changed`) | `not_reproduced` + code | `inconclusive` (D2) | `none`; source candidate in `replay_result` | Not reproduced: \<reason\>. The original recommendation is not confirmed by this replay. | The new measurement contradicts the original on \<reason\>. Treat the original recommendation with caution. | No |
| 4 | Verified original, inconclusive comparison (`insufficient_evidence`, `drift_undetermined`, `verdict_inconclusive`) | `inconclusive` + code | `inconclusive` | `none`; source candidate in `replay_result` | The replay could not confirm or contradict the original result: \<reason\>. | Inconclusive is not a rejection. A quieter host or more samples may decide. | No |
| 5 | Verified original, reproduced, `cross_environment` | `reproduced` | `inconclusive` (D9) | `none`; source candidate in `replay_result` | Consistent across environments: not a reproduction of the original setup. | The environments differ in material fields; ratios may not transfer. | No ("consistent across environments" only) |
| 6 | Verified original with noise warning | usually `inconclusive: verdict_inconclusive` | `inconclusive` (D8) | `none`; source candidate in `replay_result` | One experiment cannot repeat the original's three-experiment agreement, so the original noise-warning recommendation is not confirmed. | The noise-warning verification needs replicates that a replay does not run. | No |
| 7 | Verified original, recommendation measured by a different experiment | any | `inconclusive` (D11), or by rows 2–5 | `none`; source candidate in `replay_result` | This replay re-measured experiment X; the original recommendation rests on experiment Y, so it is not confirmed here. | Replay the recommendation's own experiment to check it. | Experiment-level only, when `reproduced` |
| 8 | Inconclusive original, replay engine has a winner | any | `inconclusive` | `none`; replay winner only in `replay_result.replay_measurement` (D4) | The original investigation verified no recommendation; this replay re-measured it and makes none. | The replay's own best arm is a single measurement, not a verification (no auditor, replication or materiality check). | Experiment-level only, when `reproduced` |
| 9 | No-action original, reproduced, same environment | `reproduced` | `no_action_needed` (D7) | `none` | The original no-action conclusion was reproduced by a new measurement. | Unreachable today (R6). | Yes (no-action only) |
| 10 | Failed or cancelled original | any | `inconclusive` (D12) | `none` | The original run did not complete, so this replay has no conclusion to confirm. | The new measurement is shown for reference. | Experiment-level only, when `reproduced` |
| 11 | Source replay run | any | `inconclusive` (D10) | `none` | This replay re-measured another replay; only an investigation's own outcome can be confirmed. | Replay the original investigation's experiment instead. | Experiment-level only, when `reproduced` |
| 12 | Missing source outcome or recommendation at start | — | no run: `not_replayable` | — | — | `source_not_finalized` / `source_integrity_failed` with detail (D6). | — |
| 13 | Missing original candidate (recommendation's measured experiment ≠ replayed one; recommendation without a primary measurement) | any | `inconclusive` (D11) | `none` | As row 7. | As row 7. | No |
| 14 | Comparison unavailable (compare-time `not_replayable`, comparison missing, snapshot missing) | `not_replayable` + field / absent | `inconclusive` (D3) | `none` | No comparison with the original was possible: \<reason\>. | The new measurement is sealed; the comparison precondition failed or was not recorded. | No |
| 15 | Replay execution failure (`sandbox_unavailable`, `ddl_failed`, `timeout`, `budget_exhausted`, `internal_error`) or cancel | `failed` / `cancelled` + code | none (run `failed` / `cancelled`) | `none` | Unchanged v1 partial-report headline, plus *Replay failed: \<code\>*. | Nothing was compared. | No |
| 16 | Historical `report-builder@1` replay report | stored | stored (unchanged) | stored | Stored, byte-identical | UI note outside the report (D5): *"Built by report-builder@1: this summary comes from the replay's own measurement, not from the comparison with the original run. The Experiment replay section shows whether the original was reproduced."* | Stored value; not reinterpreted |

### 12.4 Architecture (recommended) and alternatives

**Recommended: option E, narrowed.** Five pieces, no migration, no new dependency, no API change.

1. **Source snapshot.** Artifact `kind = replay_source`, role `input.replay_source`, `qc-json-v1`. `start_replay` writes it in its existing transaction, right after `check_preconditions` has verified the source report. It contains only verbatim copies from the source's verified manifest and report JSON: `schema_version`, `source_run_id`, `source_run_kind`, `source_experiment_id`, `source_experiment_result_sha256`, `source_manifest_sha256`, `source_report_json_sha256`, `source_builder_version`, `source_final_status`, `source_outcome`, and `source_recommendation` (`status`, `candidate_key`, `kind`, `ddl`, `query_sql`, `primary_measurement` with its `evidence_id` and `source` digest) or `null`. It contains no evidence lists, hypotheses, LLM text or credentials, and no recomputed values. Because it is linked to the replay run, the replay's manifest seals it.
2. **Classifier** `replay/outcome.py` (§12.3), called by `_close`. The resulting basis is written to `run.concluded` as `replay_basis: {code, source_outcome, comparison_status, comparison_mode}`, only for replay runs.
3. **`report-builder@2` / report schema 2** (`reports/builders/v2.py`): it wraps v1 (§12.1) and adds `recommendation.origin` (`"run"` or `"source_run"`). Replay runs also get `replay_result` = {`comparison_status`, `comparison_failure_code`, `comparison_mode`, `correctness_reproduced`, `basis`, `claims_reproduction`, `source` {run, kind, experiment, final status, outcome, manifest and report digests, builder version, `provenance: "source_run"`}, `source_recommendation` (with `provenance: "source_run"`), `replay_measurement` {`engine_winner`, `provenance`, `label`}}. When the sealed outcome is `verified_recommendation`, the replay's `recommendation` is the snapshot's recommendation with `origin: "source_run"` and `source_run_id`. Otherwise it is `status: "none"`. It is never derived from the replay's own experiment. Every schema-1 field keeps its type. `ReportInputs` gains `replay_source: dict | None = None`; v1 never reads it.
4. **`report-md@2`** (`renderers/md_v2.py`): it reuses md_v1's frozen section functions for every section except, on replay runs, the header label, Recommendation and Experiment replay. Those are rendered from `replay_result` with explicit *source run* / *replay measurement* labels.
5. **Frontend**: `SUPPORTED_REPORT_SCHEMAS = [1, 2]`, types for `replayResult` and `recommendation.origin`, and the replay status line plus *from run N* label in `ResultSummary` / `ReportView`. The D5 note is shown for v1 replay reports.

**How it meets the Phase 3 checks:**

| Check | How |
|---|---|
| 1. v1 artifacts untouched | v1 files are not edited and stay registered. A golden test rebuilds every v1 fixture with the new `ReportInputs` field. No row update, no backfill. |
| 2. Deterministic reconstruction | The builder reads only sealed inputs: the snapshot (in the manifest), the comparison artifact, `run.concluded` ≤ cutoff, and the existing records. No clock, no parent-run lookup for the new fields. Residual: v1's existing `replay_of` lookup of the source experiment's `run_id` is inherited unchanged. It predates this change, and the snapshot also carries the IDs. |
| 3. Minimal snapshot | The field list in item 1. A unit test asserts its exact key set. |
| 4. Original vs replay distinguished | `replay_result.source*` has `provenance: "source_run"`; `replay_measurement` has `measured` / `prerecorded` and its label; `recommendation.origin`. |
| 5. No contradiction | One sealed decision (`outcome` + `replay_basis`). Headline, next steps and recommendation are table lookups keyed by it. A property test over every basis code checks: `recommendation.status ≠ "none"` ⇔ outcome is `verified_recommendation` ⇔ `claims_reproduction` and basis `reproduced_source_recommendation`. The frontend renders those fields and computes nothing. |
| 6. API and report-replay compatibility | The API passes report JSON through unchanged. Schema 2 is additive, and older clients fall back to the stored Markdown (REPLAY_ENGINE §7 rule 4). `ReplayAttempt` and the comparison artifact keep their shape. The outcome enum is unchanged. Report replay already dispatches on the stored builder version. `run.concluded` gains one optional key, on replay runs only. |
| 7. Nothing unnecessary | One new pure module, one builder, one renderer, one artifact role (free text). No migration, dependency, endpoint or response model. |

**Alternatives considered:**

| Alternative | Verdict |
|---|---|
| A′. Classifier only, every replay seals `inconclusive`, keep `report-builder@1`. Smallest possible change: no snapshot, no new builder. | Stops every false upgrade immediately. But v1's headline then says *"The investigation could not reach a verified conclusion"* for a replay that did reproduce, and the report still never names the original candidate (I4). **Kept as the emergency fallback** if E is not approved: it needs only steps 1 and 3 below, with rule 8 returning `inconclusive`. |
| B. Builder@2 recomputes the classification. | Rejected (§12.1): duplicates the decision inside a frozen builder. |
| C. New outcome values (`replay_reproduced` …). | Rejected for now: migration on two CHECK constraints plus API, filter and label changes. Revisit only with an ADR. |
| Snapshot fields inside the comparison artifact. | Rejected: the comparison is returned by the `ReplayAttempt` API (`result`), so this would change an API payload, and it mixes the source's facts with the statistical result. |
| Builder reads the parent run's sealed report at build time (no snapshot). | Rejected: the rebuild would depend on the parent staying available (I5), and the classifier at `_close` would need a cross-run read of a report it did not verify itself. |
| Follow replay-of-replay chains to the root. | Rejected (D10). |

### 12.5 Implementation sequence and test matrix (prepared, not executed)

Order: TDD within each step. Each step is committed separately on `main` after the CLAUDE.md §7 checks, only after approval. Steps 1–4 are inert: v2 is registered but not current, and `_close` is unchanged. Step 5 is the single activation commit.

| Step | Files and functions | Tests written first |
|---|---|---|
| 1. Classifier | new `backend/src/querycure/replay/outcome.py`: `classify_replay_outcome`, `ReplayBasis` codes (constants) | `tests/unit/replay/test_replay_outcome.py`: every row of §12.3 (rules 1–10, all comparison statuses × modes × source kinds × source outcomes × recommendation status × experiment match). Property: over the full cartesian input space, the result is never more favourable than the source outcome (I1), and is `verified_recommendation` only under rule 8. |
| 2. Snapshot | `experiment_replay.start_replay` (+ helper `_source_snapshot` reading the source report JSON and manifest already verified in `check_preconditions`); `check_preconditions` `.first()` hardening (D6a); `reports/inputs.py`: `ReportInputs.replay_source`, loaded with `_role(…, "input.replay_source")` | unit: snapshot key set and verbatim copy, D6b unreadable report gives `source_integrity_failed`; integration (`tests/integration/test_experiment_replay.py`): snapshot linked, listed in the replay manifest, digest equal to stored; `not_replayable` creates neither a run nor a snapshot; `tests/unit/reports/test_report_v1.py`: **v1 golden guard**, all v1 fixtures byte-identical with `replay_source` set and unset. |
| 3. Builder and renderer v2 (registered, not current) | new `reports/builders/v2.py`, `reports/renderers/md_v2.py`; `reports/registry.py` adds them to `BUILDERS` / `RENDERERS` only | `tests/unit/reports/test_report_v2.py`: one fixture per §12.3 row 1–15 with headline, next steps, `recommendation` (origin, never the replay winner), `replay_result`, `correctness_reproduced`; consistency property (§12.4 check 5); non-replay golden: v2 = v1 except `schema_version`, `builder_version`, `recommendation.origin`; md_v2 provenance-label scan (as for md_v1) and *source run* / *replay measurement* labels; md_v2 never prints *Verified recommendation* for a replay unless basis is `reproduced_source_recommendation`. |
| 4. Frontend (safe before activation) | `frontend/src/lib/api/reports.ts` (`SUPPORTED_REPORT_SCHEMAS = [1, 2]`), report types, `components/report/ResultSummary.tsx`, `ReportView.tsx`, `ReportPanel.tsx` (D5 note) | Vitest `components/report/__tests__/report.test.tsx`: schema 2 replay rows 1, 2, 3, 8, 14 render the replay line and *from run N*; no *Verified recommendation* card for rows 2–8; schema 1 replay shows the stored text plus the D5 note; schema 1 non-replay shows no note; schema 3 shows the Markdown fallback. |
| 5. **Activation** | `experiment_replay.execute_experiment_replay` / `_close`: classifier replaces `result.winner`; `finalize.Conclusion` + `run.concluded` optional `replay_basis`; `registry.CURRENT_BUILDER/RENDERER/SCHEMA_VERSION` → `@2` / `2` | integration (local Docker metadata-db + sandbox-db only), with `compare_experiments` monkeypatched to return a fixed comparison per status: run / manifest / report outcome and `replay_basis` per §12.3; **regression: source sealed `inconclusive` + replay engine winner seals `inconclusive`, `recommendation.status == "none"`** (the 28-case defect); source `verified_recommendation` + `reproduced` seals verified with `origin: source_run` and the source candidate key; drift seals `inconclusive`; cross-environment seals `inconclusive`; replay-of-replay seals `inconclusive`; `report replay` of the new run gives `verified` (JSON and Markdown byte-identical); a pre-existing v1 replay run in the same DB still verifies; non-replay `replay_basis` key absent from `run.concluded`; events API payload contract test (additive key only). Source runs with a chosen sealed outcome are built by `finalize_run` with an explicit `Conclusion` over a real completed sandbox experiment. This fixture is new; its feasibility is checked first in step 2. |
| 6. Docs | REPLAY_ENGINE §7 (versions), §8.2 (*Replay run outcome and report*, the §12.3 contract), new ADR-0032 (I1–I6, D1–D12), DECISIONS.md index, UI_UX replay copy, CURRENT_PHASE, this report's status | — |

Full verification after step 5: backend ruff, format, mypy, unit, integration, security; frontend lint, typecheck, Vitest, build; Playwright e2e with one replay-report assertion (worker stopped per ADR-0020). Docker only, no Neon.

**Rollback.**
- Steps 1–4 are inert and can be reverted freely.
- Step 5 is the only switch. Preferred: fix forward.
- Emergency: revert step 5 alone. This restores the *old defect* for new replays. Fallback A′ (rule 8 returns `inconclusive`) is the safer emergency patch.
- Never remove v2 from the registry once a v2 report exists: those reports would drop to `verified_stored_only` (ADR-0015; retirement needs a DECISIONS.md entry).
- Snapshot artifacts on replay runs are harmless under v1.
- The frontend accepts both schemas, so it never needs rolling back.

**Deploy skew.**
- Replay started by an old API and executed by a new worker: there is no snapshot, so rule 3 applies (`inconclusive`, `source_snapshot_missing`). Safe.
- Started by a new API and executed by an old worker: old behaviour (v1), the known defect. Deploy the API and worker together, after the frontend.

### 12.6 Risks

| Risk | Area | Mitigation |
|---|---|---|
| A v2 rebuild depends on something mutable | Deterministic replay | Inputs limited to sealed artifacts and events ≤ cutoff; rebuild test in step 5; no clock. |
| Adding `ReportInputs.replay_source` changes a v1 rebuild | Compatibility | v1 golden guard (step 2); v1 never reads the field. |
| `run.concluded` payload changes for non-replay runs | Compatibility / determinism | Key written only for replay runs (ADR-0026 pattern); test asserts its absence elsewhere. |
| Snapshot copies a wrong or unverified value | Provenance | Taken only after `verify_report` succeeded, in the same transaction; verbatim copies; digest of the source report recorded beside it. |
| Classifier and builder disagree | Provenance | The builder never classifies; it maps the sealed `replay_basis`. |
| v1 helpers change under v2 | Determinism | v2 calls v1's public `build_report` and md_v1's section functions. v1 is frozen (ADR-0015), and v1 code is kept while v2 imports it. |
| Old v1 replays keep showing *verified recommendation* in the run picker and trace events | UX | Accepted under I6. The D5 note covers the report. A run-picker replay status from `replay_attempts` is possible later. |
| Most same-machine replays will now seal `inconclusive` | Product | Honest (ADR-0023 consequence). The copy says inconclusive is not a rejection. |
| Headline copy is product wording | UX | Owner review of the §12.3 headline column before step 3. |

### 12.7 Approval gate

Approval is needed for **D1–D12**, the §12.3 contract and headline copy, and the step order in §12.5. Until then the backend defect stays **unresolved**, no implementation starts, and Workstream 4 Stage 3 stays paused.

## 13. Owner approval and final invariants (2026-10-30)

The owner approved the design (9.4/10): decisions D1–D12, the §12.3 outcome contract and the §12.5 order, with the safeguards below. **Status: design approved. Implementation authorized only for the test-first classifier (§12.5 step 1) and the immutable source snapshot (step 2).** The classifier stays disconnected from `_close`. `report-builder@2`, `report-md@2`, report schema 2, frontend replay-result changes and activation (steps 3–5) are not authorized yet. Where this section differs from §12, this section wins.

### 13.1 Additional invariants

These make explicit what §12 implied. The classifier and the snapshot must enforce each one, and each has a test.

| # | Invariant | Enforced by |
|---|---|---|
| I7 | A replay never independently establishes a new recommendation. The only recommendation a replay can carry is the source run's, referenced with `origin: source_run`. | Rule 8 is the only rule that yields `verified_recommendation`; the replay's engine winner is not an input (D4). |
| I8 | A replay cannot improve the verification status of its original investigation. Its outcome is at most the source's sealed outcome (I1). | Rules 8–10; property test over the full input space. |
| I9 | A reproduced replay confirms the original evidence only within the replay's scope: one experiment, re-measured. It does not re-run the investigation (no diagnosis, no candidate generation, no auditor, no replication, no materiality gate). | Headline and limitation copy (§13.3); the classifier never reads anything but the snapshot and the comparison. |
| I10 | A cross-environment comparison never establishes full reproduction. | Rule 5 (D9). |
| I11 | A replay of a replay cannot propagate an inherited verified outcome, whatever that replay sealed. | Rule 6 (D10). |
| I12 | Only the original recommendation's matching experiment, identified by its stored result hash, can support confirmation. The recommendation's `primary_measurement.source.artifact_sha256` must equal the replayed source experiment's `result_sha256`. | Rule 8 (D11). |
| I13 | A noise-warning investigation (`verified_with_noise_warning`) cannot be fully confirmed by a single-experiment replay. | Rule 8 (D8). |
| I14 | Missing or unverified provenance fails closed. A missing comparison, missing or unverified snapshot, missing recommendation evidence, or any inconsistency between them gives `inconclusive` (or `not_replayable` at start), never a confirmation. | Rules 1, 3 and the consistency checks in 8; snapshot validation at start (D6). |

### 13.2 D1 clarified

ADR-0023 stays authoritative: the drift `D = S_replay / S_original` is classified by its 95% bootstrap interval against `m = 1.25`. This change does not touch the margin, the interval or the comparison algorithm. Material drift (interval entirely outside `[0.8, 1.25]`) produces the explicit comparison verdict `reproduced_with_drift`, which stays stored and displayed, and the persisted run outcome `inconclusive` (rule 4). A drifted replay never claims reproduction.

### 13.3 Headlines: "verified" versus "reproduced by replay"

The schema-2 headlines must never reuse the investigation's *Verified recommendation* wording for a replay. An investigation **verifies**; a replay at most **reproduces** what the investigation verified. Revised §12.3 headline column:

| §12.3 row | Investigation report (unchanged, v1 and v2) | Replay report (schema 2) |
|---|---|---|
| 1 | — | **Original recommendation reproduced by replay.** A new sandbox measurement of experiment X matched the original within ±25% (95% interval). The recommendation was verified by run N; this replay re-measured one experiment and verified nothing new. |
| 2 | — | **Original recommendation not confirmed: effect size drifted.** Same verdict and result rows, but the speed-up changed beyond ±25%. |
| 3 | — | **Original recommendation not reproduced:** \<reason\>. |
| 4 | — | **Replay inconclusive:** the original result was neither confirmed nor contradicted (\<reason\>). |
| 5 | — | **Consistent across environments, not a reproduction.** |
| 6 | — | **Original noise-warning recommendation not confirmed:** one experiment cannot repeat the original three-experiment agreement. |
| 7, 13 | — | **Original recommendation not checked by this replay:** it rests on experiment Y, and this replay re-measured experiment X. |
| 8 | — | **Re-measurement only:** the original investigation verified no recommendation, and a replay cannot create one. |
| 9 | — | **Original no-action conclusion reproduced by replay.** |
| 10 | — | **Re-measurement only:** the original run did not complete, so there is no conclusion to confirm. |
| 11 | — | **Re-measurement only:** this replays another replay; only an investigation's own outcome can be confirmed. |
| 14 | — | **No comparison with the original was possible:** \<reason\>. |
| 15 | — | **Replay failed:** \<code\>. |
| — | **Verified recommendation.** (`report-builder@1` wording, unchanged) | — |

The replay outcome badge for row 1 reads *Reproduced original recommendation*, not *Verified recommendation*. Copy is final only after the owner reviews it with step 3.

### 13.4 Historical compatibility notices (planned, not implemented)

Sealed `report-builder@1` replay reports stay byte-identical and keep verifying under report replay. Wherever the UI could imply independent verification, it adds a notice that is visually separate from the sealed content and never rewrites a stored value:

| Surface | Selector (stored metadata only) | Notice |
|---|---|---|
| Report view (`ReportView`, `ReportPanel`) | `builder_version == "report-builder@1"` and run kind `experiment_replay` | Banner outside the report body: *"Built by report-builder@1. This summary comes from the replay's own measurement, not from a comparison with the original investigation. A replay cannot verify a recommendation; see Experiment replay for whether the original was reproduced."* |
| Result summary (`ResultSummary`) | same | The stored outcome badge stays as stored, with a *legacy replay* marker and the same one-line explanation beside it. |
| Run selector (`RunPicker`) | run kind `experiment_replay` and the run's report built by `report-builder@1` | A *legacy replay* tag next to the stored outcome; the outcome text is not changed or hidden. |

These notices ship with frontend step 4 and need no backend change. Run rows, events, reports and digests are never edited (I6).

### 13.5 Order now authorized

1. This documentation (committed locally, not pushed).
2. Classifier `replay/outcome.py`, test first, with no caller in the execution path.
3. Source snapshot, test first, captured in `start_replay`'s transaction.
4. Verification, then a review checkpoint. Implementation stays uncommitted until the owner reviews it.
