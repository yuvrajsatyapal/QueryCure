# ADR-0032: Experiment replay outcome, creation marker and report schema 2

- **Status:** Proposed (2026-10-30). Design D1–D12 owner-approved 2026-10-30 ([REPLAY_OUTCOME_AUDIT §12–§13](../../reports/REPLAY_OUTCOME_AUDIT_2026-10-27.md)). The pieces below are implemented locally but **not active**. Accepting this ADR is the activation approval.
- **Context:** an experiment replay seals `verified_recommendation` whenever its own engine finds a winner (`experiment_replay._close`), and `report-builder@1` derives the recommendation from the replay run's own candidates, which never exist. 56 of 94 local replays sealed a verified outcome; 28 of those replayed an investigation that verified nothing.

## Decision

1. **A replay never creates or improves a verification (I1, I7–I14).** The replay's outcome comes from the pure classifier `replay/outcome.py`. Its inputs are the replay's source snapshot and its comparison; the replay's own engine winner is not an input. Only rule 9 yields `verified_recommendation`. It requires a non-replay source that sealed a clean `verified` recommendation, measured by the replayed experiment (matching result digest), and a `reproduced` comparison in the same environment for that candidate.
2. **Source snapshot by link, not copy (audit §14.4).** `start_replay` links the source's sealed manifest and report JSON to the replay run in the creation transaction (`input.replay_source.*`). No migration is needed (a new artifact kind would need one).
3. **Durable creation-time marker (audit §16).** The replay's creation event (`replay.status_changed`, `from: null`) carries `source_snapshot: {schema_version: 1, manifest, report_json}`, written in the same transaction. Events are append-only for `qc_app`, never swept, and sealed in the events digest. `load_source_snapshot` decides as follows:
   - no marker and no links: legacy (`None`);
   - marker with missing or different links: error;
   - links without a marker: error;
   - malformed marker or more than one creation event: error;
   - sealed replay whose links differ from its sealed manifest: error.

   Errors fail closed: the classifier maps them to `inconclusive: source_snapshot_missing`.
4. **Sealed basis.** `run.concluded` gains an optional `replay_basis` (`{code, source_outcome, comparison_status, comparison_mode}`), written only when set (the ADR-0026 pattern). Builders map it; they never reclassify.
5. **`report-builder@2` / report schema 2 / `report-md@2`.** These wrap the frozen v1 functions.
   - **Non-replay reports:** v1 plus `schema_version`, `builder_version` and `recommendation.origin = "run"`.
   - **Replay reports** also get `replay_result` and a headline and next steps keyed by the basis. `recommendation` is the source run's (`origin: "source_run"`, `source_run_id`) only for `reproduced_source_recommendation`; otherwise it is `none`. `replay.replay_of` is taken from the snapshot, so a rebuild never depends on the source run's rows.
   - **Contradictions:** records that contradict the basis raise `ReportContractError`, so a contradictory report is never sealed. Report replay records `rebuild_mismatch` instead of raising.
6. **Historical reports are never changed.** `report-builder@1` / `report-md@1` stay registered and current until activation. The UI shows a notice next to, never inside, v1 replay reports.

## Activation (separate approval)

A single change:
- `_close` calls `load_source_snapshot` (an error counts as `None`) and the classifier;
- passes `Conclusion(final_status, outcome, replay_basis)`;
- sets `registry.CURRENT_BUILDER/RENDERER/SCHEMA_VERSION` to `report-builder@2` / `report-md@2` / `2`.

The two must ship together: v2 refuses the legacy winner-based outcome (tested). Deploy the frontend first (it already renders schema 2), then the API and worker together.

The file-level plan, the deploy order, the handling of replays in flight at activation, monitoring queries and rollback are in [REPLAY_OUTCOME_AUDIT §17.10](../../reports/REPLAY_OUTCOME_AUDIT_2026-10-27.md).
- **Ship first:** this change set inactive, so v2 is registered everywhere and new replays carry their snapshot marker before any v2 report is sealed.
- **Open decision:** v2 current for all new reports (this ADR, recommended) or for replay runs only.
- **Rehearsal, local only (audit §17.6):** a real-stack browser rehearsal ran the activated path end to end without intercepting the report endpoint. It used a test-only worker (`backend/tests/rehearsal/activated_worker.py`) that applies this exact change in-process.

## Consequences

- Most same-machine replays will seal `inconclusive` (ADR-0023 margin). That is honest; the copy says inconclusive is not a rejection.
- v2 can never be removed from the registry once a v2 report exists.
- Emergency rollback: revert the activation change only. New replays then return to the old defect. The safer fallback A′ makes rule 9 return `inconclusive`.
- A new basis code needs a new builder version, because v2 mirrors the classifier's codes instead of importing them.
