# ADR-0022: Phase 4 implementation decisions for verification, finalization and replay

- Status: Accepted (2026-10-13, implementation decisions within ADR-0009/0015/0019; none changes a released contract)
- Area: Verification / Replay / Evals

## Context
Phase 4 implemented the Benchmark Auditor (ADR-0009), atomic finalization and report replay (ADR-0015, REPLAY_ENGINE §5–§8), and experiment replay (REPLAY_ENGINE §9). The designs left some questions open, and the owner's Phase 4 instructions added the AI re-investigation start. Each choice below is additive: `bench@1`/`bench@2` rules, canonicalization profiles and released builders are unchanged.

## Decisions

1. **The auditor is downgrade-only in the database too.** `verification_results` has `CHECK (verdict = engine_verdict OR (engine_verdict IN ('verified','verified_with_noise_warning') AND verdict = 'inconclusive'))` and `auditor_downgraded = (verdict <> engine_verdict)`. A code bug cannot store an upgrade.
2. **Deterministic audit checks before the LLM.** Eleven checks (`audit/checks.py`). The most important re-scores the persisted blocks with the experiment's *own* engine version (`engine.score(..., total=stored)`) and requires the stored verdicts and statistics to come back exactly. A failed check downgrades. The LLM narrative may add cited `downgrade` concerns. If it fails, the audit is `deterministic_only`.
3. **The terminal decision is a content event.** `finalize_run` writes `run.concluded` (final status, outcome, stop reason, synthesis summary, materiality, usage, error) as the last event before the cutoff. `report-builder@1` therefore reads only records and events `1..cutoff`, never graph state or mutable run-row columns, and a rebuild is byte-identical.
4. **Every terminal path finalizes.** `write_report`, `fail_run` (dead letter, configuration error) and API cancel of queued or awaiting runs all call `finalize_run`. The terminal node no longer emits `node.completed` after the seal. `link()` refuses sealed runs, and the approval-expiry sweep skips them.
5. **Strict byte verification.** Report replay requires the stored bytes to *be* the canonical form (re-canonicalized bytes == stored bytes) *and* to hash to the reference digest. A whitespace-only edit is therefore `integrity_failed`.
6. **`container_runtime` is a material environment field** in replay comparison. ADR-0020 turned the field into the measurement path (container network vs host relay, about ten times apart in round trip). REPLAY_ENGINE §9.3 had listed "container runtime version" as minor.
7. **Experiment replay is scored with the source rules and measured by the current engine.** The replay experiment stores the source `engine_version`. The comparison treats "measured by the current `ENGINE_VERSION`" as the replay's engine, so a `bench@1` source is always `cross_environment`. A new precondition code, `source_experiment_incomplete`, covers experiments without a result.
8. **The comparison is stored as content** (artifact kind `replay_comparison`, migration 0012). The replay run's own report can then be rebuilt and replayed.
9. **AI re-investigation: start contract only.** `POST /investigations/{id}/reinvestigate` needs explicit consent (`confirm_new_llm_run: true`), a configured key and free capacity today. It creates a new `reinvestigation` run that links the parent's inputs by reference and has its own budget. The conclusion diff stays Post-MVP.
10. **Eval replay of live-measurement prompts.** Prompts that embed new sandbox measurements (the auditor, Optimization Engineer rounds ≥ 2) cannot match a recording exactly. The replay client keeps exact matching for everything else. For those two agents only, it falls back to the next unused recorded answer of the same output shape. When the live run then takes a path the recording lacks, the case is `DIVERGED`, which is never a pass. Mode C cases are scored when recorded.

## Alternatives considered
- Storing a "report inputs" snapshot artifact at finalization instead of `run.concluded`. Rebuilding from a snapshot proves only that the builder is deterministic, not that the records are unchanged.
- Recording benchmark results in eval recordings to make Mode C replays deterministic. That would mean prerecorded measurements inside a "live" eval, and it hides the engine's behavior on the host.
- Treating `container_runtime` as minor, per the original text. That would call a relay-vs-container pair "reproduced" across a ten-times difference in measurement path.

## Consequences
- 418 integration tests cover sealing, fault injection, every report-replay code, experiment replay through the real worker and sandbox, and re-investigation.
- Mode C evals cannot be green in CI replay. Their evidence is the recorded run (both PASS on 2026-10-13).
- REPLAY_ENGINE §8.2 and §9.3, AGENT_SYSTEM, API_DESIGN and TESTING_STRATEGY describe these choices.
