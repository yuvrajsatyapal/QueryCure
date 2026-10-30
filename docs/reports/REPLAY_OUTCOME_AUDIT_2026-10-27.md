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

## 14. Implementation checkpoint (2026-10-30)

**Status: Classifier and snapshot implemented locally — awaiting review. Replay correction not activated.** Uncommitted on `main` until the owner reviews the code and results. `_close` still seals the legacy winner-based outcome; `report-builder@1` / `report-md@1` stay current; no sealed report, digest, migration, API model or frontend file changed.

### 14.1 Classifier contract (`backend/src/querycure/replay/outcome.py`)

`classify_replay_outcome(snapshot: ReplaySourceSnapshot | None, comparison: Mapping | None) -> ReplayClassification(run_status, outcome, basis, source_outcome, comparison_status, comparison_mode)`, with `claims_reproduction` and `as_basis()` (the future `run.concluded.replay_basis` payload). Pure: it reads only its two arguments and never the replay's engine winner. No caller in the execution path.

Rules, first match wins:

| # | Condition | Run status / outcome | Basis |
|---|---|---|---|
| 1 | no comparison | completed / `inconclusive` | `comparison_missing` |
| 2 | comparison `failed` (replay execution) | failed / none | `comparison_failed` |
| 3 | no snapshot | completed / `inconclusive` | `source_snapshot_missing` |
| 4 | comparison's `original_experiment_id` ≠ snapshot's source experiment | `inconclusive` | `source_snapshot_mismatch` |
| 5 | unknown status / not `reproduced` | `inconclusive` | `comparison_unrecognized` / `comparison_<status>` |
| 6 | mode ≠ `same_environment` | `inconclusive` | `cross_environment` |
| 7 | source run kind `experiment_replay` | `inconclusive` | `source_is_replay` |
| 8 | source outcome `NULL` or final status ≠ `completed` | `inconclusive` | `source_not_completed` |
| 9 | source `verified_recommendation`: recommendation missing, not verified, no candidate or no measured result digest → `source_recommendation_missing`; `verified_with_noise_warning` → `source_noise_warning`; measured result digest ≠ replayed experiment's `result_sha256` → `recommendation_from_other_experiment`; candidate absent from the comparison pairs or a pair not `reproduced` → `recommended_candidate_not_compared`; else | `inconclusive`, else **`verified_recommendation`** | …, else `reproduced_source_recommendation` |
| 10 | source `no_action_needed` | `no_action_needed` | `reproduced_source_no_action` |
| 11 | otherwise (`inconclusive`, `unverified_recommendations`) | `inconclusive` | `source_not_verified` |

### 14.2 Snapshot contract (`backend/src/querycure/replay/source_snapshot.py`)

- **Storage (deviation, see 14.4):** no copy. In the transaction that creates the replay run, `start_replay` links the source run's own sealed manifest and report JSON artifacts to the replay run as `input.replay_source.manifest` and `input.replay_source.report_json`. Both are content-addressed, digest-checked on every read (`get_artifact`), never updated by the app role and never deleted by retention, and the replay's own manifest lists them with their digests when it is sealed.
- **Capture:** inside `check_preconditions`, after `verify_report(source)` passed and the approval digests matched, `capture_source_snapshot` reads exactly the manifest and report digests that report replay verified and derives the typed `ReplaySourceSnapshot` (`snapshot_from_sealed`, pure). Fields: `schema_version`, source run id and kind, source experiment id, its sealed `result_sha256` and environment digest, manifest and report digests, builder version, final status, outcome, and the report's `recommendation` restricted to `status`, `candidate_key`, `kind`, `ddl`, `query_sql`, `primary_measurement`, `scope`. No evidence lists, hypotheses, summaries, LLM text or credentials.
- **Validation (fails closed as the existing `source_integrity_failed`, D6):** manifest schema 1; manifest and report belong to the source run; the manifest names this report; final status and outcome agree between them; run kind and outcome are known values; the replayed experiment is in the manifest with a result digest equal to the stored experiment row's result; the report has a complete recommendation. For a non-replay source that sealed `verified_recommendation`: the recommendation is verified (or noise-warning), names a candidate and a measured result digest, that digest is one of the source's sealed experiment results, and when it is the replayed experiment the candidate is one of its arms. A missing source run row (D6a) is `source_integrity_failed: source run missing` instead of an exception. Replay-kind sources are recorded as sealed, including the empty recommendation of upgraded v1 replays; the classifier never passes their outcome on (D10).
- **Atomicity:** the run, its links (config, query, parameters, snapshot), approval, attempt and job are one transaction. A fault at link or attempt insertion leaves no run, attempt, job or snapshot link (tested).
- **Reconstruction:** `load_source_snapshot(conn, replay_run_id)` re-derives the snapshot from the replay's own links (snapshot roles plus `input.experiment_config`, which holds the source experiment's config) and its `parent_run_id`. It returns `None` for runs without a snapshot (every replay started before this change, and non-replay runs) and raises `SourceSnapshotError` for incomplete or inconsistent links. Derivation is deterministic; deleting or changing the source run, its report rows, manifest row, links or experiments afterwards does not change it (tested inside a rolled-back owner transaction).
- **Not added yet:** `ReportInputs.replay_source`. The v1 loader is untouched; the field is added with `report-builder@2`.

### 14.3 Tests

| File | Covers |
|---|---|
| `tests/unit/replay/test_replay_outcome.py` (43) | 32 decision-table rows (every §12.3 row, D1–D12, the fail-closed additions); basis payload; replay winner not an input; determinism and no mutation; invariants over 15,523 input combinations: no upgrade, only the fully eligible case verifies, no replay-of-replay laundering, drift and environment mismatch never reproduce, missing provenance never verifies, only a failed comparison fails the run, `claims_reproduction` ⇔ reproducing basis |
| `tests/unit/replay/test_source_snapshot.py` (24) | exact field set, nothing extra copied, deterministic canonical bytes and round trip, isolation from later input changes, other-experiment and inconclusive/failed/replay-kind sources, 16 rejected inconsistencies (run, report, outcome, schema, kind, recommendation, experiment hash, unsealed or mismatched measured result, candidate not an arm) |
| `tests/integration/test_experiment_replay.py` (+7 cases, real sandbox PG 17) | valid finalized source linked and sealed in the replay manifest, snapshot equals the source's records, replay report still `report-builder@1` schema 1 and verifies, legacy outcome still sealed (not activated), classifier gives a contract-valid basis on real records; snapshot unchanged after source run changes and deletion; missing source run; source integrity failure (tampered report); inconsistent records → `not_replayable`, no run; rollback on a fault at snapshot link and at attempt insert. Unfinalized sources stay covered by the existing test. |

Results: see 14.6.

### 14.4 Deviations from the approved design

1. **Snapshot stored by link, not as a new `replay_source` artifact.** `artifacts.kind` has a CHECK constraint (migrations 0008/0010/0012), so a new kind needs a migration, which is not authorized. Linking the source's own sealed manifest and report JSON needs none, copies nothing, and leaves one source of truth. The snapshot becomes a typed view derived from sealed records instead of a stored JSON document. Starting a replay already links source artifacts (`input.query`, `input.param_sets`), so this follows an existing pattern.
2. **Extra fail-closed rules** (I14): `source_snapshot_mismatch`, `comparison_unrecognized`, `source_recommendation_missing`, `recommended_candidate_not_compared`; an unknown comparison mode is treated as cross-environment; a source with an outcome but a non-`completed` final status is `source_not_completed`.
3. **Basis codes split:** §12.3's `reproduced_source_outcome` became `reproduced_source_no_action` (D7) and `source_not_verified` (rule 11), so `claims_reproduction` is true only for the two reproducing bases.
4. **Start path behaviour (active now, outcome unchanged):** new replays carry the two snapshot links (one more manifest entry each), and a source whose sealed records are inconsistent is refused with `source_integrity_failed` and a detail. Previously such a source started a replay.
5. `ReportInputs.replay_source` deferred to step 3 (14.2).

### 14.5 Remaining work and limitations

- **Not started, needs approval:** `_close` activation and `run.concluded.replay_basis`; `report-builder@2`, `report-md@2`, report schema 2 (`replay_result`, `recommendation.origin`, the §13.3 headlines); frontend schema 2 and the §13.4 legacy notices; REPLAY_ENGINE §7/§8.2, ADR-0032, DECISIONS.md.
- **Historical replays have no snapshot.** Replays started before this change (all 94 local ones) return `None` from `load_source_snapshot`; if one were finalized after activation it would seal `inconclusive: source_snapshot_missing`. Their sealed v1 reports stay byte-identical and are only annotated in the UI (§13.4).
- **Shared artifacts.** The snapshot artifacts are shared with the source run, as `input.query` already is. Artifacts are never deleted today; a future artifact retention design must treat linked artifacts as live while any run links them.
- **Demo bundles** export a fixed role list that does not include the snapshot roles. That only matters if a replay run is ever exported as a demo bundle; none is today.
- **Deploy skew:** an attempt queued by an old API has no snapshot; after activation it would seal `inconclusive` (rule 3), which is safe.

### 14.6 Verification (2026-10-30, local Docker only)

| Check | Result |
|---|---|
| `ruff check .`, `ruff format --check .` | clean (392 files) |
| `mypy src` (strict) | no issues, 219 files |
| Classifier unit tests | 43 passed |
| Snapshot unit tests | 24 passed |
| `tests/integration/test_experiment_replay.py` + idempotency | all passed (the 6 earlier replay tests unchanged and green) |
| Report replay, finalization, report v1 goldens (`test_report_replay.py`, `test_finalize.py`, `tests/unit/reports`) | 57 passed, no fixture changed |
| Full backend `pytest` (unit 1085 + integration 488 + security 162 collected) | **1732 passed, 2 skipped, 1 xfailed** (pre-existing skip and documented xfail) |
| Smoke evals (recorded, local scratch DB) | 5/5, no quota ledger entry (no real model requests) |
| Frontend | not run: no frontend file or shared type changed |

One new integration test failed on its first run because it expected HTTP 202 for a refused replay; the API already answers 422 `EXPERIMENT_NOT_REPLAYABLE` with the code in `details`. The test was corrected to the existing contract; no code changed for it. Mypy reports 23 pre-existing errors when run on `tests/integration/test_experiment_replay.py` directly (unchanged by this work; CI runs `mypy src`).

## 15. Snapshot integrity review and legacy compatibility (2026-10-30)

**Status: hardened and committed locally. Replay correction still not activated.** `_close`, report builders, frontend, migrations and API are unchanged.

### 15.1 Integrity gaps found and fixed (test first)

| Gap in §14 | Fix in `source_snapshot.py` | Test |
|---|---|---|
| Artifact kind not checked: any digest-valid JSON could sit under a snapshot role | `_verified` requires `replay_manifest`, `report_json`, `experiment_config` per role | `test_snapshot_artifact_of_the_wrong_kind_fails_closed` |
| A corrupted artifact raised `ArtifactIntegrityError` instead of failing closed as a snapshot error (start path: 500 instead of `source_integrity_failed`) | wrapped as `SourceSnapshotError` | `test_corrupted_snapshot_artifact_fails_closed[manifest, report_json]` |
| A non-terminal or unknown `final_status` was accepted | must be `completed`, `failed` or `cancelled` | 2 new unit rows |
| Legacy vs. corrupted decided by link presence alone | see 15.2 | `test_historical_…`, `test_sealed_new_replay_with_missing_snapshot_links_fails_closed[manifest, report, both]` |
| Snapshot links on a run that is not a replay were ignored if both were missing, otherwise misattributed | raises | covered by the discriminator branch |

Unchanged and confirmed: both links must exist exactly once with their roles; digests are re-checked on every read through the existing `get_artifact` (no second hashing or canonicalization); manifest and report must name the same source run; the manifest must name this report; final status and outcome must agree; the replayed experiment's sealed result digest must match; recommendation, candidate and measured-result checks as in §14.2.

### 15.2 Legacy versus new replays

The discriminator is the replay's **own sealed manifest** (existing, append-only, digest-verified). For a finalized replay, the snapshot roles it lists must equal the current links: listed but missing or different → error; not listed and not linked → legacy (`None`); linked but not listed → error. No heuristic (dates, counts) is used.

For an **unsealed** replay there is no sealed record yet, so the links are the only evidence. They are written in the start transaction together with the run (all or nothing, tested), and `qc_app` can neither UPDATE nor DELETE `artifacts` or `run_artifacts` (new security test). A replay with one link is an error. A replay that lost both links before sealing is indistinguishable from a pre-snapshot replay without a new persisted marker (that would need a field or event-schema change, not authorized). Both cases return `None`, which the classifier maps to `inconclusive: source_snapshot_missing`, so neither can produce a verified outcome. This is the residual item to settle before activation.

Local data (read-only, local Docker): all 94 historical replays return `None` and report replay `verified`, all `report-builder@1`.

### 15.3 Retention

No path can remove a snapshot artifact: `qc_app` has only SELECT and INSERT on `artifacts` and `run_artifacts` (no soft delete, no rewrite); the only DELETE role, `qc_retention`, is used solely by `ops/retention.py`, which never touches evidence tables; investigation deletion is a soft delete on `investigations` only; there are no foreign keys or cascades (ADR-0006). New tests pin the grants and that the sweep keeps artifacts and links. A future artifact-retention design must treat any `run_artifacts` link as a live reference.

### 15.4 Reconstruction

`load_source_snapshot` reads only the replay's own row (`kind`, `parent_run_id`, `finalized_at`), its links and its sealed manifest. Tested on unsealed and sealed replays with the source run's report, manifest, links, experiments and run row deleted (rolled-back owner transaction): the snapshot is identical. Two replays of one experiment link the same two content-addressed rows and load equal snapshots.

### 15.5 Start-path behaviour (active now)

New refusal conditions, all reported as the existing `source_integrity_failed` (HTTP 422 `EXPERIMENT_NOT_REPLAYABLE`, code in `details`, attempt `not_replayable`, no run): snapshot artifact missing, corrupted or of the wrong kind; manifest schema not 1; manifest or report of another run; manifest naming another report; final status or outcome differing or not terminal; unknown run kind or outcome; replayed experiment absent from the manifest or with another result digest; report without a complete recommendation; for a non-replay `verified_recommendation` source, recommendation evidence missing, measured result unsealed, or candidate not an arm. A missing source run row is now a refusal instead of an exception.

Historical sources: a read-only sweep of all 595 local experiments through `check_preconditions` (sandbox disabled, which is checked after the snapshot) refused none for snapshot reasons: 579 reached `sandbox_disabled`, 10 `source_not_finalized`, 6 `source_experiment_incomplete`, as before.

Visibility: the two links appear only in the replay's sealed manifest `artifacts` list. The run plan listing, demo export and artifact download (already owner-scoped through the source run) do not add exposure; `get_run_inputs` reads `input.%` but only for LLM runs, and re-investigations copy links from `latest_run_id`, which is never a replay. Safe to keep enabled before activation.

### 15.6 Verification

ruff, format (392 files), mypy strict (219 files) clean. Classifier 43, snapshot unit 26, `test_experiment_replay.py` 24, report replay / finalize / report goldens / artifact store / ops integrity 71, security 168. Full backend: **1750 passed, 2 skipped, 1 xfailed**. Smoke evals 5/5 recorded, no quota ledger entry. No golden fixture changed.

## 16. Workstream 5: creation marker, report schema 2, frontend (2026-10-30)

**Status: Versioned replay correction implemented locally — activation awaiting approval.** The backend defect is **still unresolved**. `_close` still seals the legacy winner-based outcome, and `report-builder@1` / `report-md@1` stay current. Nothing was committed, pushed or deployed. The decision record is [ADR-0032](../engineering/adr/ADR-0032-experiment-replay-outcome-and-report-schema-2.md) (Proposed).

### 16.1 Durable creation-time marker (closes the §15.2 residual)

- **Where:** the replay's creation event `replay.status_changed` (`from: null → queued`). `start_replay` writes it in the same transaction as the run, the links, the approval, the attempt and the job. It gains `source_snapshot: {schema_version: 1, manifest: "sha256:…", report_json: "sha256:…"}`, naming exactly the two links.
- **Why it is durable:** `qc_app` has SELECT and INSERT only on `investigation_events`, now pinned by a security test. Retention never touches events. The marker is sealed in the events digest. No migration and no API change: the key is optional and ignored by clients (API_DESIGN §3).
- **Decision in `load_source_snapshot`:**

  | Case | Result |
  |---|---|
  | No marker and no links | legacy (`None`) |
  | Marker, but one or both links missing | `SourceSnapshotError` |
  | Marker naming other digests than the links | `SourceSnapshotError` |
  | Links present without a marker | `SourceSnapshotError` |
  | Malformed marker (wrong type, schema, keys or digest form) | `SourceSnapshotError` |
  | More than one creation event | `SourceSnapshotError` |
  | Sealed replay whose links differ from its sealed manifest | `SourceSnapshotError` (unchanged) |

  For sealed runs, only events up to the cutoff are read.
- **Both links missing, unsealed** (the case §15.2 could not decide) now fails closed: `test_unsealed_marked_replay_with_missing_links_fails_closed[both]`.
- **Exploitability:** a new replay can look legacy only if its creation event lacks the marker. The current start code always writes it, since the run is refused without a captured snapshot. The event cannot be edited or removed by the app role. Once the replay is sealed, its sealed manifest still lists the snapshot roles, so dropping both the marker and the links is an error too (tested).
- **Local data (read only):** 0 snapshot links and 0 markers existed before this change, and all 94 replays have exactly one creation event. No replay anywhere is in the links-without-marker state, because `e99886d` was never pushed or deployed.

### 16.2 `report-builder@2` / schema 2 / `report-md@2` (registered, not current)

- **Builder:** v2 calls the frozen `v1.build_report`.
  - **Non-replay reports:** v1 plus `schema_version: 2`, `builder_version: report-builder@2` and `recommendation.origin: "run"`. Tested against every v1 case.
  - **Replay reports:** v2 reads the sealed `run.concluded.replay_basis` and never reclassifies. It then sets:
    - `headline` and `next_steps`, by basis code (§13.3 wording);
    - `recommendation`: the source's (`origin: source_run`, `source_run_id`) only for `reproduced_source_recommendation`, otherwise `none`;
    - `replay.replay_of`: from the snapshot, so the rebuild does not depend on the source run's experiment row (found by the integration test; v1 keeps that residual);
    - `replay_result`.
- **`replay_result` fields:**
  - `result`, one of `original_reproduced`, `performance_drift`, `not_reproduced`, `inconclusive`, `not_comparable`, `not_confirmed`, `unavailable`, `failed`, `cancelled`, `unclassified`;
  - `title`, `claims_reproduction`, `original_reproduced`, `basis`, `explanation`, `failure_code`;
  - `comparison_status`, `comparison_failure_code`, `comparison_mode`, `margin`;
  - `correctness_reproduced`, `performance_reproduced`, `material_drift`, `environment_comparable`, `material_differences`;
  - `experiment_match` {`replayed_experiment_id`, `replayed_result_sha256`, `recommendation_result_sha256`, `matches`};
  - `source` {run, kind, experiment, final status, outcome, manifest and report digests, builder, `provenance: source_run`};
  - `source_recommendation` (with `provenance: source_run`);
  - `replay_measurement` {`engine_winner`, `provenance`, `label: "replay measurement, not a verification"`};
  - `snapshot_error`.

  An unknown or absent value is `null`, never inferred.
- **Fail closed:** `ReportContractError` is raised, and finalization rolls back, when:
  - a favourable outcome has no basis;
  - the outcome differs from the one the basis implies;
  - the basis is unknown or malformed;
  - the basis disagrees with the comparison (status or mode) or with the snapshot (source outcome, presence, mismatch claim);
  - the reproducing basis lacks a clean verified source measured by the replayed experiment.

  `verify_report` records `rebuild_mismatch` for it instead of raising. A completed `inconclusive` replay without a basis is `unclassified`.
- **Renderer:** `report-md@2` reuses md_v1's sections. For non-replay reports only the version line differs (tested). Replays get:
  - their own header label;
  - *Replay measurement*, *Experiment Replay Result*, then *Original recommendation* (only when reproduced) or *Recommendation: This replay makes no recommendation of its own*, with the source candidate *shown for reference and not confirmed*;
  - *Comparison with the original*.

  *Verified recommendation* never appears in a replay's Markdown. The provenance-label scan passes for every scenario.
- **`ReportInputs`** gains `replay_source` / `replay_source_error`, loaded only for replay runs (snapshot errors are captured, not raised). v1 output is byte-identical with them set or unset (golden guard).
- **`Conclusion.replay_basis`** is written to `run.concluded` only when set. No production caller sets it.

### 16.3 Frontend

- `SUPPORTED_REPORT_SCHEMAS = [1, 2]`; schema 3 and later still fall back to the stored Markdown.
- **Schema-2 replay reports:** the builder's title as the heading (no repeated headline), an *Experiment replay result* section, *Original recommendation* only when the replay reproduced it, the replay's best arm as a labelled measurement, and no empty problem or hypotheses sections.
- **ResultSummary** shows the replay line.
- **Historical v1 replay reports:** a notice outside the sealed body in ReportPanel (*Earlier replay classification*), a *Legacy replay* marker in ResultSummary, and a *legacy replay* tag in the run selector. The selector tag covers sealed replays whose stored outcome is `verified_recommendation`, using the existing report endpoint's `builder_version`; there is no API change. Stored outcomes are never changed or hidden.
- **Fixtures** are real builder output for synthetic inputs (`frontend/src/test/fixtures/report-v2.json`). A backend test keeps them identical to the builder's output.

### 16.4 Deviations and limitations

1. A marker on the creation event instead of a new column, which avoids a migration.
2. `replay.replay_of` in v2 comes from the snapshot (correctness: a mutable parent-row dependency in rebuilds).
3. The run-selector tag is limited to replays with a stored verified outcome. Those are the only rows whose outcome reads as a verification, and the limit avoids one report fetch per replay. The report view and summary notices cover every v1 replay (§13.4 selector).
4. The v2 integration tests simulate activation inside the test only: v2 made current and `finalize_run` wrapped with the classifier. On this host the source investigation sometimes seals `verified_with_noise_warning`. The test then checks D8 instead of row 1 and emits a warning; row 1 ran end to end on a clean verified source in at least one observed run.
5. v1 replay rebuilds still depend on the source experiment row (frozen v1 residual, §12.4); v2 does not.

### 16.5 Activation prerequisites (not done)

1. Owner approval of ADR-0032.
2. One change in `_close`: `load_source_snapshot` (an error counts as `None`), then `classify_replay_outcome`, then `Conclusion(final_status, outcome, replay_basis)`, together with `CURRENT_BUILDER/RENDERER/SCHEMA_VERSION` set to v2. They must ship together: v2 refuses the legacy outcome (`test_v2_finalization_refuses_a_legacy_winner_outcome`).
3. Deploy order: frontend first, then API and worker together.
4. Re-run the full verification, including e2e on a real activated replay.

Rollback: revert step 2 only. Never unregister v2 once a v2 report exists.

### 16.6 Verification (local Docker only; no Neon)

| Check | Result |
|---|---|
| ruff, format, mypy strict | clean (397 files; 221 source files) |
| Full backend pytest | **1978 passed, 2 skipped, 1 xfailed** (pre-existing skip and xfail) |
| New/changed backend tests | v2 builder/renderer 159; v1 golden 23 (digests generated at `e99886d`, unchanged); frontend-fixture contract 1; marker unit 13; replay integration 52, was 24 (+20 marker and reconstruction, +8 v2 end to end); finalize `replay_basis` 1; security grants +3 |
| Smoke evals (recorded) | 5/5, no quota ledger entry |
| Sealed-report sweep (read only) | 676 reports before: 0 digest, builder or outcome changes after; 678/678 `verified` |
| Snapshot sweep | 94 historical replays: legacy; 1 new e2e replay: snapshot loaded |
| Frontend lint, typecheck, Vitest | clean; **500 passed** |
| Production build | passed (the first attempt failed on a stale `.next` font cache; a clean rebuild passed) |
| Playwright | **31/31** (full suite, worker container not running). It includes the new `replay-report.spec.ts`: six schema-2 cases, axe clean in dark and light, no horizontal overflow at 320, 375, 768 and 1440 px, reduced motion, and 24 screenshots in `test-results/ws5/` (gitignored). The lifecycle spec checks the historical notice on a real sealed v1 replay. Schema-2 pages use intercepted builder fixtures, because no real v2 report exists before activation. |

## 17. Workstream 5, Phases 3–6: consistency, rehearsal, verification, activation plan (2026-10-30)

**Status: Workstream 5 verified locally — replay outcome activation awaiting explicit approval.** `_close` still seals the replay's own winner (`experiment_replay.py:571-573`), and `CURRENT_BUILDER/RENDERER/SCHEMA_VERSION` are still `report-builder@1` / `report-md@1` / `1` (`reports/registry.py:34-36`). No migration, API change or dependency. Nothing pushed or deployed.

### 17.1 Final schema-2 contract (unchanged since §16.2)

- `run.concluded.replay_basis = {code, source_outcome, comparison_status, comparison_mode}` is the single sealed decision. The builder maps it and never reclassifies.
- `replay_result.result` ∈ `original_reproduced`, `performance_drift`, `not_reproduced`, `inconclusive`, `not_comparable`, `not_confirmed`, `unavailable`, `failed`, `cancelled`, `unclassified`, each with one title. Only `reproduced_source_recommendation` yields `verified_recommendation`, `claims_reproduction: true` and `recommendation.origin: "source_run"`. Every other replay has `recommendation.status: "none"`, and its engine winner appears only as `replay_measurement` ("replay measurement, not a verification").
- Contradictory sealed records raise `ReportContractError`, so they are never sealed. Report replay records `rebuild_mismatch` for them.

### 17.2 Durable snapshot-marker guarantees (unchanged since §16.1)

The creation event's `source_snapshot` marker is append-only for `qc_app` (pinned by security tests), never swept, and sealed in the events digest. A marked replay that loses either link, or whose links differ from the marker or the sealed manifest, fails closed (`source_snapshot_missing`, inconclusive). It never reads as legacy. Only replays created without a marker (all replays before this code is deployed) are legacy.

### 17.3 Deterministic scenario coverage

The virtual clock (`backend/tests/integration/virtual_clock.py`) fixes every benchmark sample per scenario; sandbox DDL, queries, row fingerprints, gates, statistics and the comparison all run for real. Each test asserts its own precondition (for example, a clean `verified` source), so no scenario can silently become another.

- `test_replay_outcome_e2e.py`: 12 tests, 10 scenarios, all passing.
- Phase 5 found one older §16 test (`test_v2_replay_report_is_consistent_and_rebuilds_byte_identically`) still measuring with the host clock. It retried and then substituted rule 8a for row 1 on a noisy source, and it failed once in the full run when host noise sealed the source `inconclusive`. It now uses the virtual clock and asserts a clean `verified` source, so the substitution branch is gone.
- Two pre-existing defects in the Phase 2 files were fixed: an undefined `options` name in `test_v2_finalization_refuses_a_legacy_winner_outcome` (it would have raised `NameError`), and lint errors in the e2e module.

### 17.4 Cross-layer consistency matrix

`frontend/src/test/fixtures/replay-consistency.json` holds one row per scenario. It is read by:
- the real-stack integration tests (run row, manifest, stored comparison, `run.concluded`, report JSON, Markdown, API report, JSON and Markdown exports, report replay);
- `backend/tests/unit/reports/test_replay_consistency_matrix.py` (builder and Markdown);
- `frontend/src/lib/report/__tests__/replay-consistency.test.tsx` (report view, result summary, run selector).

The frontend fixture `report-v2.json` gained the six missing matrix scenarios. It is still real builder output, and existing entries are unchanged.

| Scenario | Outcome | Comparison (mode) | `replay_basis` | Title (report, summary, selector) | Recommendation | Legacy |
|---|---|---|---|---|---|---|
| reproduced | verified_recommendation | reproduced (same) | reproduced_source_recommendation | Original recommendation reproduced | source run | no |
| performance_drift | inconclusive | reproduced_with_drift (same) | comparison_reproduced_with_drift | Performance drift detected | none | no |
| not_reproduced | inconclusive | not_reproduced (same) | comparison_not_reproduced | Original result not reproduced | none | no |
| inconclusive_comparison | inconclusive | inconclusive (same) | comparison_inconclusive | Replay comparison inconclusive | none | no |
| cross_environment | inconclusive | reproduced (cross) | cross_environment | Results not directly comparable | none | no |
| noise_warning_original | inconclusive | reproduced (same)¹ | source_noise_warning | Noise-warning recommendation not confirmed | none | no |
| replay_of_replay | inconclusive | reproduced (same) | source_is_replay | Re-measurement only | none | no |
| mismatched_experiment | inconclusive | reproduced (same) | recommendation_from_other_experiment | Original recommendation not checked by this replay | none | no |
| snapshot_missing (missing or corrupted) | inconclusive | reproduced (same) | source_snapshot_missing | No comparison with the original was possible | none | no |
| historical_v1 | verified_recommendation (stored) | reproduced (same) | — (none sealed) | Verified recommendation + *legacy replay* notice | none | yes |

¹ A real comparison of a noise-warning original is `inconclusive` (gate 4); that path is tested too. Rule 8a's `reproduced` input is set at the comparison boundary.

Fields that do not exist are stated as such, never invented: v1 reports have no `replay_result`, basis or recommendation origin. No report was fabricated for a failed or unsealed run. The failed and cancelled results are covered by builder unit tests and the `15_execution_failed` component test, not by matrix rows.

### 17.5 Run-selector semantics and the event log

- **Before:** the selector printed the stored outcome, so a reproduced schema-2 replay read "verified recommendation". Only replays with a stored verified outcome were looked up, to tag legacy ones.
- **Now:** `runOutcomeLabel` (`frontend/src/lib/report/replay.ts`):
  - a schema-2 replay shows the builder's sealed title ("Original recommendation reproduced", "Performance drift detected", "Original result not reproduced", "Replay comparison inconclusive", "Results not directly comparable", "Replay failed", …);
  - a report-builder@1 replay shows its stored outcome plus the *legacy replay* tag (now every v1 replay, not only verified ones);
  - a failed replay whose report is not loaded shows "Replay failed";
  - a sealed verified replay whose report is still loading shows no outcome rather than "verified recommendation";
  - investigation runs are unchanged.
- **Data:** the existing report endpoint, one query per sealed replay on the same query key as the report view, `staleTime: Infinity` (sealed reports never change). No API change.
- **Event log:** `run.concluded` with a `replay_basis` reads "Concluded: completed · replay basis: reproduced source recommendation" instead of the bare stored outcome.

### 17.6 Real-stack browser rehearsal

- **Seam:** `backend/tests/rehearsal/activation.py` holds the test-only activation seam: registry v2 current, plus `finalize_run` (as `experiment_replay` sees it) wrapped by the classifier. `simulate_activation` in the integration tests now uses it too, so there is one seam.
- **Worker:** `backend/tests/rehearsal/activated_worker.py` is the production worker with that seam and the virtual clock applied in-process. It refuses to start unless `DATABASE_URL` is local and `LLM_PROVIDER=stub`. Nothing in `querycure` imports it, and the backend image copies only `src`.
- **Config:** `frontend/playwright.rehearsal.config.ts` reuses the e2e config and swaps only the worker command; the main config ignores the rehearsal spec.
- **Path exercised:** wizard → API → worker → stub agents → approval → sandbox benchmark → seal (source). Then API replay start (snapshot links and marker) → worker replay handler → real comparison → classifier → report-builder@2 / report-md@2 → sealing → real report API → page.
- **No interception:** `frontend/e2e/replay-rehearsal.spec.ts` never calls `page.route`. Every report read is awaited as a real `GET http://localhost:8100/api/v1/runs/{id}/report` response (status 200, not from a service worker).
- **Result:** 1/1 passed. Local run IDs: source `efa80827-fab0-4e86-8ac5-c4710b0baa61`, reproduced replay `e6870e9f-ca9c-48a6-9e33-ad0930db9a80`, drifted replay `82e5dd92-2ffa-4cfb-bf76-bd1a7ce4afe1`.
  1. Reproduced replay: run row, sealed report and API agree: `verified_recommendation`, `report-builder@2`, schema 2, basis `reproduced_source_recommendation`, comparison `reproduced` / `same_environment`, `recommendation.origin = source_run`, `source_run_id` = the source.
  2. The page shows "Original recommendation reproduced" as the only `h1`, never "Verified recommendation". The *Original recommendation* region names the source run, the replay result labels the replay winner a measurement, and the comparison section is present with no historical notice.
  3. *Verify report* reports "Integrity check passed against stored digests": the rebuild reproduces the sealed bytes. The exported Markdown has the same title and section, and the exported JSON equals the sealed report.
  4. Drifted replay: `inconclusive`, `performance_drift`, basis `comparison_reproduced_with_drift`, correctness reproduced, material drift, recommendation `none`. The page reads "Performance drift detected" with no original-recommendation section, and it verifies.
  5. Run selector: "#2 … · Original recommendation reproduced", "#3 … · Performance drift detected". No replay row says "verified recommendation" and no row is tagged legacy. The original run keeps "verified recommendation". Axe is clean on the menu in both themes.
  6. A real historical report-builder@1 replay from this DB keeps its stored outcome, shows the notice outside the sealed body, and verifies.
- **Side effect (local only):** the rehearsal sealed 8 schema-2 reports in the local dev metadata DB: two from a first attempt that failed on a spec selector, then three from each of two passing runs. Under simulated activation, investigation runs seal with v2 too, as activation intends. These reports require v2 to stay registered.

### 17.7 Visual QA

- **Screenshots:** `test-results/ws5-rehearsal/` (gitignored): `{reproduced,drifted,legacy}-{320,375,768,1440}-{dark,light}.png` and `run-selector-1440-{dark,light}.png`. All are real sealed reports, reviewed by eye. Earlier fixture-based shots are in `test-results/ws5/`.
- **Numbering:** sections are numbered 01–09 in order and match the contents list, with no `00`. One headline: the title is the `h1` and the headline body does not repeat it.
- **Mobile hierarchy:** candidate and verification scope come first, then source details. Full run IDs, experiment IDs and `sha256:` digests wrap and are never truncated.
- **Legacy notice:** readable at 320 px, above and outside the sealed body.
- **No misleading badges:** the only verification badge on a replay report is on the *Original recommendation* card ("Verified · tested scope", from the source run, "reproduced by this replay").
- **No clipping:** SQL and benchmark tables sit in focusable horizontal scroll containers, and page overflow is 0 at every width.
- **Spacing and typography:** consistent with v1 reports.
- **Observation:** the round table's numeric columns need horizontal scrolling at 320 px. This is pre-existing v1 layout, not changed here.
- **Not a defect:** the Next.js dev-tools badge in screenshots comes from the e2e dev server.

### 17.8 Historical compatibility

- **Sweep:** read-only report-replay sweep of every sealed report in the local metadata DB, inside a read-only, rolled-back transaction.
  - Before the full suites: **691/691 verified** (686 report-builder@1, 5 report-builder@2).
  - After them: **702/702 verified** (694 / 8). The 11 new reports came from this session's Playwright runs: 8 v1 from the main suite (production worker), 3 v2 from the second rehearsal.
- **Byte identity:** a snapshot of every report (stored JSON and Markdown digests, artifact content hashes, builder, renderer, schema, outcome, manifest digest) was taken before the full backend and Playwright suites and compared after them. **All 691 rows are identical; none changed or disappeared.**
- **Golden fixtures and versions:** historical golden digests (`tests/fixtures/reports/v1_golden.json`) are untouched, and v1 builders and renderers stay registered.

### 17.8a Verification (2026-10-30, local Docker only; no Neon, no live model calls)

| Check | Result |
|---|---|
| ruff, ruff format, mypy strict | clean (403 files; 221 source files) |
| Full backend pytest | first run: 2000 passed, **1 failed** (the host-clock test in §17.3); after the fix, a full re-run: **2001 passed**, 2 skipped, 1 xfailed (both pre-existing) |
| Deterministic e2e scenarios | 12/12 (now also checking API builder and schema versions and both exports) |
| Matrix (builder and Markdown) | 11/11 |
| Smoke evals (recorded) | 5/5, no quota-ledger entry |
| Frontend lint, typecheck, production build | clean |
| Vitest | **567 passed** (was 500): +41 matrix, +selector and event-log cases |
| Playwright (full suite: axe, keyboard, reduced motion, overflow at 320/375/768/1440, lifecycle on a real v1 replay) | **31/31** |
| Real-stack rehearsal (no interception) | **1/1**, twice |
| Sealed-report sweep | 691 identical; 702/702 verify |

### 17.9 Remaining limitations

1. **History list and dashboard:** ~~they still print the latest run's raw stored outcome…~~ **Corrected in §18.2:** a replay is never an investigation's latest run, so these lists never showed a replay's outcome. The follow-up was done anyway as hardening (§18.1).
2. **Rehearsal scope:** the browser rehearsal covers the reproduced and drifted scenarios end to end. The other eight are covered on real sealed runs at integration level (API, exports, report replay) and at component level, not in a browser.
3. **Timing:** the rehearsal and the deterministic tests use the virtual clock, so real host timing is not part of the v2 proof. That is intentional, because thresholds and gates are unchanged.
4. **Rule 8a:** a real comparison cannot reach rule 8a; its input is set at the comparison boundary.
5. **Network:** the selector makes one cached report request per sealed replay of the open investigation.
6. **v1 residual:** v1 replay rebuilds still read the source experiment row (§16.4.5).

### 17.10 Activation plan (proposal — not executed)

**Step 0 — ship this commit inactive (frontend, API and worker).** It registers v2 everywhere, writes the creation marker and snapshot links for every new replay, and teaches the frontend schema 2. `e99886d` and the marker were never deployed, so every replay in production today is legacy (no marker). Replays created after step 0 carry their snapshot, so they can be classified at activation.

**Step 1 — the activation change, one commit:**
- `backend/src/querycure/replay/experiment_replay.py`:
  - **Completed comparison path (lines 562–576):** inside `_close`'s transaction, before `finalize_run`, call `load_source_snapshot(conn, run_id)` (on `SourceSnapshotError`, use `None`). Then call `classify_replay_outcome(snapshot, comparison)` on the same comparison dict the caller stores as `replay.comparison`. Finalize with `Conclusion(final_status=c.run_status, outcome=c.outcome, replay_basis=c.as_basis())`.
  - Delete the `result.winner` expression.
  - Failed and cancelled closes are unchanged. This is exactly `tests/rehearsal/activation.classifying_finalize`, moved into `_close`.
- `backend/src/querycure/reports/registry.py:34-36`: `CURRENT_BUILDER = builder_v2.BUILDER_VERSION`, `CURRENT_RENDERER = md_v2.MD_RENDERER_VERSION`, `CURRENT_SCHEMA_VERSION = builder_v2.REPORT_SCHEMA_VERSION`. All four builders and renderers stay registered.
- **Decision for the owner:** ADR-0032 makes v2 current for all new reports. Non-replay v2 differs from v1 only in `schema_version`, `builder_version` and `recommendation.origin`, and the rehearsal sealed investigation runs this way. The alternative, v2 for replay runs only, needs a per-kind selector in `finalize_run` and keeps two current builders. **Recommended: as ADR-0032 (all new reports).**
- **Tests in the same commit:**
  - `test_v2_is_registered_but_v1_stays_current` becomes "v2 is current; v1 stays registered".
  - `test_historical_v1_replay_keeps_its_stored_contract` builds its v1 replay with the registry pinned to v1.
  - `simulate_activation` / `tests/rehearsal/activation.py` become unnecessary: keep only the comparison-status override; the rehearsal worker becomes plain `querycure.worker`.
  - `frontend/e2e/phase4-lifecycle.spec.ts` expects the schema-2 replay title instead of the historical notice.
  - `test_v2_finalization_refuses_a_legacy_winner_outcome` stays and proves step 1 cannot ship half done.

**Step 2 — deploy order:**
1. Frontend first (renders schemas 1 and 2, replay-aware selector and event log).
2. Then API and worker together from the same commit. The API must have v2 registered before any worker seals v2, because report replay and retrieval look builders up by stored version. Step 0 guarantees this.
3. Never run an old worker against the activated API, or the reverse, for longer than one deploy.

**Partially completed replays at activation:**

| Replay state at deploy | What happens | Action |
|---|---|---|
| Sealed before activation | Keeps its v1 report forever, never rebuilt with v2 (verify uses the stored version) | none |
| Queued or running, created **without** a marker (before step 0) | **Superseded by §18.4:** sealed under its creation contract (v1, legacy outcome, tagged legacy), never reclassified as `source_snapshot_missing` | Drain first: `python -m querycure.ops replay-cutover-check` exits 0 |
| Queued or running, created **with** a marker (after step 0) | Classified normally | none |
| Reclaimed after a worker crash | `_close` is idempotent (terminal attempt check, `finalized_at`) | none |

**Monitoring after activation** (read-only SQL plus logs; every check should be 0 except the distribution):
1. **Contradictions:** v2 replay reports with outcome `verified_recommendation` whose `run.concluded.replay_basis.code` is not `reproduced_source_recommendation`, or whose `report.recommendation.origin` is not `source_run`.
2. **Version skew:** replay reports sealed with `report-builder@1` after the activation time.
3. **Missing basis:** replay runs completed after activation without a `replay_basis`.
4. **Refused seals:** `ReportContractError` in worker logs, or replay attempts failed at finalization.
5. **Rebuild failures:** report-replay attempts with `rebuild_mismatch`.
6. **Distribution:** basis codes per day. Expect mostly `comparison_inconclusive` on shared hosts (ADR-0023).

**Rollback:** revert step 1 only (`_close` and `CURRENT_*` together, one commit).
- v2 stays registered, so every sealed v2 report still retrieves and verifies. The frontend stays.
- Replays sealed after rollback are v1 legacy again (with markers), and the selector tags them legacy.
- Never unregister v2 and never edit a sealed v2 report. If the classifier itself is in doubt, fallback A′ (rule 9 returns `inconclusive`) is safer than rolling back.

**Activation prerequisites:**
1. Owner approval of ADR-0032 and of the scope decision above.
2. Step 0 deployed.
3. The history and dashboard follow-up (§17.9.1).
4. The replay queue drained or the exposure accepted.
5. The full verification re-run on the activated build, including `phase4-lifecycle` on a real activated replay.

## 18. Pre-activation consistency and safety (2026-10-30)

**Status: Pre-activation consistency verified locally — replay outcome activation awaiting approval.** `_close` still seals the replay's own winner (`experiment_replay.py:571-573`), and `registry.CURRENT_BUILDER/RENDERER/SCHEMA_VERSION` are still `report-builder@1` / `report-md@1` / `1`. No migration, API contract change or dependency. Nothing pushed or deployed. The owner approved report-builder@2 / report-md@2 as the future default for **all** new reports (§17.10's open decision), subject to the compatibility checks in §18.3; the default is not switched.

### 18.1 Outcome-labelling contract (every surface)

One classifier, `classifyRunOutcome(run, reportState)` in `frontend/src/lib/report/replay.ts`, decides what a run's outcome may say. Every surface formats its result: the run selector (`runOutcomeLabel`, lower case), History rows, Dashboard recent runs and outcome counts, the investigation header (`activityOf`), and the event log (`describe` with replay context).

| Run | Condition | Label | Tone |
|---|---|---|---|
| Ordinary | completed with an outcome | Stored outcome (*Verified recommendation*, *Unverified recommendations*, *No action needed*, *Inconclusive*; unknown → its words) | verified only for `verified_recommendation` |
| Ordinary | otherwise | Run status | status |
| Replay | queued, running, awaiting approval, cancelling | Run status; the stored outcome is never read | status |
| Replay | failed / cancelled | *Replay failed* / *Replay cancelled* | failed / neutral |
| Replay | completed, schema-2 report loaded | The builder's sealed title (*Original recommendation reproduced*, *Performance drift detected*, *Original result not reproduced*, *Replay comparison inconclusive*, *Results not directly comparable*, …) | verified only for *Original recommendation reproduced* |
| Replay | completed, report-builder@1 report loaded | *Legacy replay · {stored outcome}*, tooltip = the §13.4 notice | neutral (never the verified tone) |
| Replay | completed, report loading or not requested | *Replay completed* | neutral |
| Replay | completed, report request failed | *Replay completed · report unavailable* | neutral |
| Replay | completed, unknown builder or format | *Replay completed · see report* (tooltip names the builder) | neutral |

- **Invariant (tested over every fixture × every status × every report state):** no replay label is *Verified recommendation*; outside the legacy context no replay label contains "verified recommendation"; the verified tone appears on a replay only with *Original recommendation reproduced*.
- **Tightened:** before, a completed replay whose report was still loading showed its stored `inconclusive` in the selector. It now shows nothing until the report says what that means.
- **Dashboard counts:** a completed replay is its own bucket, *Experiment replays*, never *Verified recommendation*. Failed and cancelled replays count under their status.
- **Event log:** on a replay run (detected from its `replay.*` events, which only replay runs record), `run.status_changed` drops the bare outcome. `run.concluded` names the sealed basis, or for v1 replays reads "stored outcome: … (legacy replay classification)". Ordinary runs are unchanged.
- **Investigation header:** a completed replay uses the classification of its sealed report (the query the Report tab already makes).
- **Historical v1 reports are unchanged.** The sealed summary still shows its stored title, always beside the legacy marker. The notice stays outside the sealed body and makes no claim about reproduction.
- **Deliberately not changed:** the replay page's Manifest viewer prints the sealed manifest's raw `final_status · outcome` fields as manifest content, not as a label.

### 18.2 List views: what they actually show (correction to §17.9.1)

- **Correction:** §17.9.1 said History and Dashboard print a replay's stored outcome when the replay is the latest run. **That never happens with the current API.** The list's `latest_run` is `investigations.latest_run_id`, and only investigation creation and re-investigation set it (`db/repositories/investigations.py`); `start_replay` does not. So did the outcome and status filters, which join on the same column.
  - **Local data (read only):** 102 investigations have replay runs, and 0 have a replay as their latest run.
  - **Pinned** by `test_a_replay_never_becomes_its_investigations_latest_run`: after a sealed replay, the source run stays latest, and neither list nor filter returns a replay.
  - The open investigation page also defaults to `latestRun`, so a replay is reached only by choosing it (run selector, replay page, report link). Those surfaces were already covered in §17.
- **What the History/Dashboard change therefore is:** defensive hardening, so lists stay correct if replays ever become latest runs, not a fix of a reachable defect. It is kept because it is the same shared classifier and costs nothing. Dashboard counts would then put replays in their own *Experiment replays* bucket. History would show a note when the verified filter matches a replay (unreachable today).
- **No N+1.** Lists read replay reports **from the query cache only** (`useCachedReplayReports`, `enabled: false`); a row never triggers a report request (unit-tested, and checked in `e2e/replay-labels.spec.ts` on real data).
- **API:** no change is needed while `latest_run` excludes replays. If a future change made replays latest runs, exact list titles would need an additive, nullable `RunSummary.replay_result = {result, title, builder_version}` filled from `investigation_reports` and the stored report's `replay_result` (one indexed LEFT JOIN, no migration). The outcome filter should then exclude `experiment_replay`. Not proposed for now.

### 18.3 Ordinary investigations under report-builder@2

`backend/tests/unit/reports/test_ordinary_v2_compatibility.py` builds every ordinary report shape with v1 and v2 from the same inputs. The inputs are synthetic unit-test fixtures, not measurements.

| Requested case | Matrix case |
|---|---|
| Verified recommendation | `verified` |
| No action needed | `no_action_needed` (new) |
| Inconclusive | `inconclusive` |
| Rejected candidate | `rejected` |
| Correctness failure | `mismatch` |
| Missing evidence | `missing_evidence` (new: no conclusion, query, hypotheses or experiments) |
| Noise warning | `noise_warning` |
| Failed execution | `failed_execution` (new: dead letter, failed experiment) |
| Cancelled execution | `cancelled` |
| Multiple experiments and parameter sets | `multiple_experiments` (new: 3 replicates × 2 parameter sets with a replication verdict) |
| Missing optional provenance | `no_optional_provenance` (new: no LLM calls, environment or usage) |
| Also | `downgraded` (auditor), `prerecorded`, `unbenchmarked` |

**Asserted for all 14 cases:**
1. **Exact additive difference:** the set of differing JSON paths between v1 and v2 is exactly `schema_version` (1 → 2), `builder_version` (`report-builder@1` → `report-builder@2`) and `recommendation.origin` (absent → `"run"`). No other path differs, and `replay_result` is absent.
2. **Semantics unchanged:** final status, outcome, stop reason, partial flag, headline, next steps, limitations and missing-evidence lists are equal.
3. **Verification unchanged:** rounds (candidate statuses, verdicts, auditor downgrades, measurements, confidence intervals, builds, correctness), evidence and the recommendation (minus `origin`) are equal.
4. **No invention:** a recommended candidate is one the run's own rounds verified (or verified with a noise warning); with no candidate the outcome is never `verified_recommendation`.
5. **Markdown:** report-md@2 differs from report-md@1 in exactly one line (the version line). The provenance-label scan passes, and the headline and recommended candidate appear in the Markdown.
6. **Determinism:** two builds and two renders are byte-identical.
7. **Export shape:** after snake → camel conversion, `schemaVersion`, `builderVersion` and `recommendation.origin` are as the frontend reads them.

- **Frontend:** `frontend/src/test/fixtures/report-v2-ordinary.json` is real builder output for the 11 requested cases (a new file; the backend test keeps it identical to the builder). `ordinary-v2.test.tsx` renders each with `ReportView` and `ResultSummary` and compares them to the same report as v1: the sections are identical, and so is the text apart from the version string. No replay wording or legacy notice appears.
- **Unchanged and still passing:** the v1 golden digests (`v1_golden.json`, generated at `e99886d`), the schema-3+ stored-Markdown fallback, and the existing non-replay v1/v2 equivalence tests.
- **Incompatibilities found:** none.

### 18.4 In-flight replay cutover

**What a replay depends on.** Its contract is fixed at creation:
- `start_replay` writes the snapshot links and the creation marker in one transaction.
- The worker handler runs the experiment, stores the comparison and calls `_close`.
- `_close` is idempotent: a terminal-attempt check, plus `finalize_run` returning the existing seal when `finalized_at` is set.
- Retries and reclaims resume the same run. Worker shutdown leaves the job reclaimable.

**Policy (preferred, operational):**
1. Hold new replay starts for the cutover window. There is no maintenance switch for `POST /experiments/{id}/replay` today, so this means deploying at a quiet time and re-running the gate right before the switch; adding a switch would be a separate, approved change. Existing jobs are never cancelled.
2. Let queued and running replays drain.
3. Gate: `python -m querycure.ops replay-cutover-check --url-env <VAR>` (new, read-only, in a `READ ONLY` transaction). It lists in-flight replays and the contract they were created under, and exits 1 while a `legacy` one is in flight.
4. Deploy API and worker together (the activation commit).
5. Resume replay starts after the post-deploy checks (§17.10 monitoring).

**Contract detection** (`querycure/replay/cutover.py`, inert: neither the worker nor the API calls it today):
- `legacy`: no marker and no links (started before step 0).
- `snapshot`: marker and/or links present, **including damaged or contradictory ones** (fail closed: never legacy).

**If draining is impossible (safety net, part of the activation patch).** A replay keeps its creation contract:
- A `legacy` replay that concludes after activation is sealed exactly as before activation: its legacy winner-based conclusion with `report-builder@1` / `report-md@1`, no `replay_basis`. The UI then tags it *Legacy replay*.
- It is **not** turned into `inconclusive: source_snapshot_missing`. That would read as "No comparison with the original was possible", which is wrong for a replay that simply predates snapshots.
- This replaces the §17.10 table row that accepted `source_snapshot_missing` for these replays.

**Tests** (`backend/tests/integration/test_replay_cutover.py`: real API, worker handler and sandbox PG 17, no LLM; activation simulated by the test-only seam, which now applies the same rule): 9 passed.

| Case | Result |
|---|---|
| Legacy replay queued at cutover | Check reports it `legacy`/`queued`; sealed v1 (builder, renderer, schema 1) with the legacy outcome, no basis, no `replay_result`; verifies; no longer in flight |
| Legacy replay running at cutover (worker died, job reclaimed) | Same, through the reclaim path |
| New replay, valid snapshot | `snapshot`; sealed v2 with a basis; outcome `verified_recommendation` iff basis `reproduced_source_recommendation`; verifies |
| New replay, snapshot link lost | Still `snapshot` (marker present); sealed v2 `inconclusive` / `source_snapshot_missing`; never legacy |
| Worker restart + duplicate delivery | Reclaimed job, then two more deliveries: 1 experiment, 1 report, 1 manifest, 1 `run.concluded`, bytes unchanged |
| API/worker version skew | Activated worker seals v2 while the API has v1 current: verifies, API serves `report-builder@2` / schema 2. Old worker seals a *marked* replay with v1 while v2 is current: verifies |
| Builder version unknown to the reader | v2 unregistered: report replay answers `verified_stored_only` + `builder_retired` (no failure, no rebuild); API still serves the stored report |
| Rollback after a v2 seal | The v2 report keeps its bytes and verifies; the next replay seals v1; both verify |
| Cutover gate | Exit 1 with one legacy replay queued (attempt still `queued`: the check changes nothing); exit 0 after the user cancels it |

- **Local data:** `replay-cutover-check` against the local dev metadata DB reports `ready: true`, 0 in flight.
- **Not covered:** two workers delivering the same job concurrently (the queue's `FOR UPDATE SKIP LOCKED` claim prevents it; only sequential duplicates are tested).

### 18.5 Activation diff (proposal — not applied)

**1. `backend/src/querycure/replay/finalize.py`** — `finalize_run` gains an explicit version choice instead of reading globals mid-call:

```python
@dataclass(frozen=True)
class ReportVersions:
    builder: str
    renderer: str

async def finalize_run(conn, run_id, conclusion, *, fault=None, versions: ReportVersions | None = None):
    versions = versions or ReportVersions(registry.CURRENT_BUILDER, registry.CURRENT_RENDERER)
    ...
    report = registry.build(versions.builder, inputs, ...)          # was registry.CURRENT_BUILDER
    markdown = registry.RENDERERS[versions.renderer](report)          # was registry.CURRENT_RENDERER
    ... "renderer": versions.renderer ...                             # investigation_reports row
    manifest = await _manifest(..., renderer=versions.renderer)       # manifest md_renderer_version
```

`registry.py` adds `LEGACY_REPORT_VERSIONS = ReportVersions("report-builder@1", "report-md@1")` (or keeps the tuple in `finalize.py`).

**2. `backend/src/querycure/replay/experiment_replay.py`, `_close`:** inside its transaction, before `finalize_run`:

```python
contract = await replay_contract(conn, run_id)
versions = LEGACY_REPORT_VERSIONS if contract == "legacy" else None
conclusion = Conclusion(final_status=run_status, outcome=outcome, stop_reason=..., error=...)
if contract == "snapshot" and run_status is RunStatus.COMPLETED:
    try:
        snapshot = await load_source_snapshot(conn, run_id)
    except SourceSnapshotError:
        snapshot = None                          # fails closed: source_snapshot_missing
    c = classify_replay_outcome(snapshot, result)  # `result` is the comparison dict _close stores
    conclusion = dataclasses.replace(conclusion, final_status=c.run_status, outcome=c.outcome,
                                     replay_basis=c.as_basis())
await finalize_run(conn, run_id, conclusion, versions=versions)
```

- The completed call site (lines 564–576) keeps passing the winner-based outcome. It is used only for `legacy` replays, so it stays a legacy-only input.
- Failed and cancelled closes take the same `versions` rule: a legacy replay seals v1 whatever its end.

**3. `backend/src/querycure/reports/registry.py:34-36`:**
- `CURRENT_BUILDER = builder_v2.BUILDER_VERSION`;
- `CURRENT_RENDERER = md_v2.MD_RENDERER_VERSION`;
- `CURRENT_SCHEMA_VERSION = builder_v2.REPORT_SCHEMA_VERSION`.

All builders and renderers stay registered. Every new report, ordinary or replay, is v2 (§18.3), except legacy replays (v1, above). The schema version always comes from the builder's own output (`report["schema_version"]`, already how `investigation_reports` is filled), so schema and builder cannot disagree.

**4. Fail closed:** unchanged.
- v2 raises `ReportContractError` on any contradiction, and `_close`'s transaction rolls back, leaving no half-sealed run (`test_v2_finalization_refuses_a_legacy_winner_outcome`).
- The attempt stays non-terminal and the job retries, then dead-letters to `failed`. That path seals with v2's failed result and no outcome, so it is never contradictory.

**Tests in the activation commit:**
- `test_v2_is_registered_but_v1_stays_current` → "v2 is current; v1 stays registered".
- `test_historical_v1_replay_keeps_its_stored_contract` pins `versions=LEGACY_REPORT_VERSIONS`, or builds through a legacy-contract replay.
- `tests/rehearsal/activation.py` shrinks to the comparison-status override. `test_replay_cutover.py`, `test_replay_outcome_e2e.py` and the integration v2 tests then run against production code with no seam (`simulate_activation` → no-op).
- New unit tests for `finalize_run(versions=…)`: the manifest and the reports row record the chosen renderer; v1 with v2 current is byte-identical to the golden.
- `frontend/e2e/phase4-lifecycle.spec.ts` expects the schema-2 replay title.
- Expected behaviour: the §17.4 matrix rows plus §18.4 (legacy → v1 legacy).

**Rollback:** revert the activation commit only (§17.10).
- v2 stays registered. Replays sealed after rollback are v1 and tagged legacy.
- The `versions` parameter is harmless to keep.

### 18.6 Remaining risks

1. **List precision (latent):** if replays ever became latest runs, History and Dashboard would show *Replay completed* for replays whose report this session has not loaded, until an additive API field exists (§18.2). Not reachable today.
2. **Legacy safety net:** a legacy replay that concludes after activation keeps the old defect (a winner-based outcome) for that one run. It is visibly tagged legacy and is avoided entirely by draining (§18.4 step 2).
3. **Seam vs. patch:** the cutover tests prove the rule through the test seam, which swaps registry globals for one seal. The proposed patch passes versions explicitly. The tests move to the real code in the activation commit.
4. **Earlier §17.9 limitations 2–6** still hold.

### 18.7 Verification (2026-10-30, local Docker only; no Neon, no live model calls)

| Check | Result |
|---|---|
| ruff, ruff format, mypy strict (`src`) | clean (406 files; 222 source files) |
| Full backend pytest | first run: 2069 passed, **1 failed** (the new cutover-gate test: its in-flight query counted finalized replays whose attempt row was still `queued`; fixed in §18.4 by defining in-flight as "run not sealed"). Re-run: **2071 passed**, 2 skipped, 1 xfailed (both pre-existing) |
| New backend tests | ordinary v1/v2 matrix 61; cutover integration 10 |
| Smoke evals (recorded) | 5/5, no quota-ledger entry (no live model calls) |
| Frontend lint, typecheck, production build | clean |
| Vitest | **600 passed** (was 567) |
| Playwright full suite | **33/33** (was 31; +2 `replay-labels.spec.ts`: real data, axe dark and light, no overflow at 320/375/768/1440). An earlier run failed the new dashboard test once: it read a non-OK list response before the session existed; it now waits for an OK one |
| Screenshots | `test-results/ws5-preact/{history,dashboard}-{320,375,768,1440}-{dark,light}.png` (gitignored), reviewed. No replay rows appear, as §18.2 explains; ordinary labels are capitalised and consistent with the Dashboard pills, with no clipping |
| Sealed-report sweep (local dev DB, read only) | 702 before: **0 changed or missing** after (stored digests, content md5, builder, renderer, schema, outcome, manifest digest). 16 new reports from Playwright, all report-builder@1 (no activation). `verify-integrity`: 718/718 `verified`, 8303/8303 artifacts |
| Golden and fixture integrity | `v1_golden.json` and `report-v2.json` unchanged; `report-v2-ordinary.json` is new |
| Activation files | `registry.py`, `experiment_replay.py`, `finalize.py`: no diff. No migration |

## 19. Activation (2026-10-30/31, local only)

**Status: ACTIVATED LOCALLY — not deployed.** The owner accepted ADR-0032 and authorized the activation for local implementation, testing, documentation and a local commit. Nothing was pushed or deployed, and Neon was not accessed. Production still runs the pre-activation build; its cutover procedure is DEPLOYMENT §4c, "Replay outcome activation".

### 19.1 What changed (the §18.5 diff, plus one widening)

| File | Change |
|---|---|
| `reports/registry.py` | `ReportVersions(builder, renderer, schema_version)`, `CONTRACTS`, `LEGACY_REPORT_VERSIONS`, `current_versions()`, `check_versions()` (unknown, retired or mixed → `UnsupportedReportVersionError`). `CURRENT_*` = `report-builder@2` / `report-md@2` / `2`. All builders and renderers stay registered. |
| `replay/finalize.py` | `finalize_run(..., versions=None)`. The contract is checked before anything is written. The builder's output must name the chosen builder and schema. The reports row and the manifest record the chosen renderer (no globals read mid-seal). |
| `replay/cutover.py` | `report_versions_for(conn, run_id, kind)`: current, except a `legacy`-contract experiment replay → v1. It is now called by `finalize_run`. |
| `replay/experiment_replay.py` | `_close` classifies a completed `snapshot` replay with `classify_replay_outcome` on `load_source_snapshot(...)` (error → `None`) and the stored `replay.comparison` artifact, and seals `replay_basis`. The winner-based outcome is renamed `legacy_outcome` and is sealed only for `legacy` replays. Failed and cancelled closes are unchanged. |

**Widening of §18.5 (found while implementing):** replays are also sealed outside `_close`: by the dead-letter path (`jobs/handlers` → `agents/run.fail_run`), by `cancel_replay_attempt` (API cancel of a queued replay), and by the API's own cancel. §18.5 put the legacy-version rule only in `_close`, so a legacy replay that dead-lettered after activation would have sealed v2. The rule therefore lives in `finalize_run`'s default (`report_versions_for`), and every path keeps the creation contract. Each path is tested.

No migration, API change, new outcome value or dependency. The frozen v1 builder and renderer, the thresholds, the correctness rules and the comparison are unchanged.

### 19.2 Test-only activation substitutes retired

- `tests/rehearsal/activation.py` is deleted. `simulate_activation` became `fix_comparison_status`, which only fixes the comparison verdict at its boundary, for rule 9a. Everything downstream is production code.
- `tests/rehearsal/activated_worker.py` became `clocked_worker.py`: the production worker plus the virtual clock (timing only). The full Playwright suite uses the plain `python -m querycure.worker`.
- `tests/rehearsal/pre_activation.py` (new) reproduces the **old** build (v1 current, every replay `legacy`) inside a named `monkeypatch.context()`. Only the skew and rollback tests use it.
- **Guard:** `test_production_path_is_not_substituted` asserts the following:
  - `experiment_replay.finalize_run is finalize.finalize_run`;
  - `experiment_replay.classify_replay_outcome is outcome.classify_replay_outcome`;
  - v2 is current, and the old seam module no longer exists;
  - no test file other than `pre_activation.py` names `finalize_run`, `classify_replay_outcome`, `_close` or `CURRENT_BUILDER` as a patch target.
- **Tests updated for the new default (an expected value changed, never a weakened check):**
  - two graph tests and `test_report_replay`'s served-report test now expect `report-builder@2`;
  - the retired-builder test retires v2, the builder that sealed its run, so it keeps its meaning;
  - the snapshot test now asserts that the snapshot records the source's real builder (v2), and that the replay's sealed outcome and basis equal the classifier's on its records;
  - `test_v2_finalization_refuses_a_legacy_winner_outcome` calls the real `finalize_run` with v2 and the legacy conclusion.

### 19.3 Deterministic matrix and cutover on the activated code

- `test_replay_outcome_e2e.py` passes 13 tests: the 10 matrix scenarios (11 tests, because the missing and corrupted snapshot cases are separate; the noise-warning row is rule 9a with a real noise-warning source), the real-comparison noise-warning case, and the guard. They cover reproduced, drift, not reproduced, inconclusive, cross-environment, noise warning, replay of a replay, mismatched experiment, missing or corrupted snapshot, and historical v1. The historical-v1 row is now produced the way it happens in production: the replay is created by the pre-snapshot start code and concluded by the activated build.
- `test_replay_cutover.py` passes 13 tests:
  - legacy queued or running → v1;
  - valid snapshot → v2 with a basis;
  - lost link → `source_snapshot_missing`, never legacy;
  - restart plus duplicate delivery → one seal;
  - skew both ways; unknown builder;
  - rollback;
  - the gate; `latest_run`;
  - new: dead-lettered legacy (v1) and snapshot (v2) replays;
  - new: queued cancel of legacy (v1) and snapshot (v2) replays;
  - new: sandbox failure → `failed`, no outcome, no basis.
- New finalization tests: v2 by default everywhere it is recorded; explicit legacy seals v1 byte-identically while v2 is current; unsupported or mixed versions are refused with nothing written; a builder emitting another contract is refused.
- Not covered: two workers delivering the same job concurrently (prevented by `FOR UPDATE SKIP LOCKED`; only sequential duplicates are tested, as before).

### 19.4 Real-stack rehearsal (local Docker, stub model, no interception)

- **Plain production worker** (full Playwright, `phase4-lifecycle`): a stub investigation sealed with v2 (verified recommendation), then a real replay. On real host timing all four lifecycle replays in this session sealed `inconclusive` / `comparison_inconclusive` with v2, and each verified. The page reads "Replay comparison inconclusive", with no historical notice and no "Verified recommendation".
- **Clocked rehearsal** (`clocked_worker`, production classification and sealing, virtual clock only):
  - reproduced → `verified_recommendation` / `reproduced_source_recommendation`, `recommendation.origin = source_run`;
  - drift → `inconclusive` / `comparison_reproduced_with_drift`;
  - a real historical v1 replay keeps its stored outcome and legacy notice;
  - all verify, and the exports equal the sealed report.
- The run selector, header, result summary and event log use the sealed titles.
- **Historical v1 and ordinary v2 investigations:** covered in the same runs, plus `replay-labels.spec.ts` (History and Dashboard on real data).
- **Screenshots (gitignored), reviewed by eye:**
  - `test-results/ws5-rehearsal/{reproduced,drifted,legacy}-{320,375,768,1440}-{dark,light}.png` and `run-selector-1440-{dark,light}.png`;
  - `test-results/ws5-activation/{plain-inconclusive-report,ordinary-v2-report,replay-run-page}-{320,375,768,1440}-{dark,light}.png` (plain-worker replay);
  - `test-results/ws5-preact/` (History, Dashboard).
- **Accessibility checks** (by a temporary local spec, deleted, not committed):
  - axe clean at 320 and 1440 in both themes;
  - no horizontal page overflow at any width;
  - reduced motion emulated;
  - *Verify report* reachable by Tab and operable with Enter.
- **Correction during QA:** the first temporary QA run picked the newest v2 replay by basis, which was a clocked rehearsal replay, not a plain-worker one. Those shots were discarded and retaken on a plain-worker replay (`E2E lifecycle …`, run `12030f66-…`).
- **Known fragility, not this change:** `trace-layout.spec.ts` failed once in one full run with `sidebarTop` of `-0` against `0`. `Math.round` of a sub-pixel negative top gives `-0`, and `toBe` uses `Object.is`. It passed in the other full runs and twice alone; the file is unchanged here.

### 19.5 Verification (local Docker only; no Neon; no live model calls)

| Check | Result |
|---|---|
| ruff, ruff format, mypy strict | clean (406 files; 222 source files) |
| Full backend pytest (unit, integration, security, retention, replay, snapshot, builders, finalization, cutover) | first full run: 2086 passed, **4 failed** (v1 version pins, §19.2); fixed; clean re-run: **2090 passed**, 2 skipped, 1 xfailed (pre-existing) |
| Smoke evals (recorded) | 5/5; quota ledger unchanged (no entry for the day) |
| Frontend lint, typecheck, production build | clean |
| Vitest | 600 passed |
| Playwright full suite (plain worker) | run 1: 32 passed, 1 failed (the new lifecycle assertion matched two "Integrity check passed" texts: a locator bug, fixed); run 2: 32 passed, 1 failed (`trace-layout` `-0`, above); run 3: **33/33** |
| Rehearsal (`clocked_worker`) | 1/1 |
| Sealed-report integrity (local dev DB, read only) | baseline **726** reports (718 v1, 8 v2): **0 changed or missing** (JSON, Markdown and manifest digests and content, builder, renderer, schema, outcome, status). 31 new reports, all report-builder@2. `verify-integrity`: **757/757** reports `verified`, 8766/8766 artifacts |
| Golden fixtures | `v1_golden.json`, `report-v2.json`, `report-v2-ordinary.json`, `replay-consistency.json` unchanged |
| Monitoring (`infra/ops/replay_activation_monitoring.sql`, `since` = 2026-10-30T16:20:44Z) | all 10 checks **0**. Distribution: 4 `comparison_inconclusive`, 1 drift, 1 reproduced (all v2). Run with an earlier `since`, the same script flags the pre-activation defect (5 marked replays sealed `verified_recommendation` by v1), so the checks do discriminate |
| `replay-cutover-check` (local) | `ready: true`, 0 in flight, before and after |

### 19.6 Rollback readiness

Revert the activation commit only (DEPLOYMENT §4c). v2 stays registered, sealed v2 reports keep verifying (`test_rollback_after_a_v2_seal_keeps_v2_reports_and_returns_to_v1`, run here against the reverted build reproduced by `pre_activation`), and later replays seal v1 with the legacy tag. No rollback was needed locally.

### 19.7 Remaining risks and limitations

1. **Not deployed.** Production needs step 0 first, then the drain and gate, then the activation commit. The deploy order is in DEPLOYMENT §4c.
2. **Worker logs** were not scanned for `ReportContractError` locally, because Playwright discards the API and worker stdout. The database-side checks that a refused seal would trip (monitoring 9 and 10) read 0, and every new report verified.
3. **Host timing:** on this machine every plain-worker replay was `comparison_inconclusive`. The reproduced and drift outcomes were exercised end to end only with the virtual clock (thresholds unchanged, ADR-0023).
4. **Legacy safety net:** a legacy replay that concludes after activation still carries the old winner-based outcome (tagged legacy). Draining avoids it.
5. §17.9 items 4–6 still hold.

