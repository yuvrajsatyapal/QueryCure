# ADR-0024: Deterministic Mode C evals from prerecorded measurement fixtures (R19)

- Status: **Accepted** (2026-10-16, Phase 5 priority 2, authorized by the owner's Phase 5 brief)
- Area: Evaluation / Benchmarking
- Relates to: [ADR-0022](ADR-0022-phase4-verification-replay-implementation.md) §10 (live-measurement eval replay, `DIVERGED`), [ADR-0009](ADR-0009-deterministic-verification-authority.md), [ADR-0019](ADR-0019-noise-warning-verification-and-corroborated-regression.md), [ADR-0016](ADR-0016-free-openrouter-models-only.md), risk R19

## Context

Mode C eval cases replay recorded model answers, but some prompts embed the experiment's measurements: the Benchmark Auditor's review, and later Optimization Engineer rounds. A replay re-benchmarks in the sandbox, so those prompts change on every run. Phase 4 matched them by agent ("same-agent fallback"). When the new measurements took the run down another path, the result was `DIVERGED`, never a pass (ADR-0022 §10). Mode C cases could therefore only be scored when recorded (R19). Agent decision quality and live performance were tested in the same run, so neither could be checked deterministically.

## Decision

1. **Separate the two concerns.** Mode C eval replay takes `--measurements fixture` (the default) or `--measurements live`.
2. **Record mode captures a measurement fixture.** While a case is recorded, the engine measures for real. Every replicate it produced (config, environment fingerprint, raw blocks, result), grouped by optimization round with the engine's replication verdict, is saved to `evals/fixtures/measurements/<case>/<model>.json`. Results are relabelled `provenance = "prerecorded"` at every layer, with `recorded_on` and a source note.
3. **The recorded run already sees the relabelled results.** Result digests include provenance, and evidence IDs and prompts include result digests. So the model is recorded on exactly the evidence a fixture replay will show it.
4. **Fixture replay is benchmark-free and exact.** A `FixtureMeasure` replaces the engine call in `run_experiment` (the `RunContext.measure` seam). It feeds the stored blocks and results through the same persistence hooks. No DDL or benchmark query runs in the sandbox for the experiment; context collection still reads the sandbox, as before. The replay client then uses **exact prompt matching only** (no same-agent fallback), so any difference is a failure to re-record, never a pass.
5. **The sandbox context is recorded too.** CI showed that a freshly built template gives different plan estimates: ANALYZE samples tables larger than 300 × `default_statistics_target` rows at random, and that leaks into the context prompts. Record mode therefore also stores the context reads (capabilities, plain EXPLAIN, schema snapshot) through a `RunContext.context_inspector` seam. Fixture replay serves them, and a read the recording never made is a mismatch. Fixture replay thus needs **no sandbox server at all**. `--capture-context` adds the context to an existing fixture, but only from a replay that matched every recorded prompt exactly. The template builder (`tpl@1`) and benchmark conditions are unchanged.
6. **Safety rails.**
   - Every arm's SQL digest is checked against the run's approval.
   - The run's experiment config must equal the recorded one; candidate row ids, which are generated per run, are remapped by arm key.
   - A round count beyond the fixture is refused, and unused recorded rounds fail the case.
   - The recorded replication verdict must still follow from the stored results under the frozen rules. It is checked on copies relabelled `measured` for that comparison only, because the rules refuse prerecorded evidence as replicates.
   - A mismatch is reported as a failure even if the graph turned it into an `inconclusive` candidate.
7. **Live mode stays.** `--measurements live` re-benchmarks and keeps ADR-0022 §10 semantics (`DIVERGED` is never a pass). It reports environmental variability honestly.
8. **Results name their inputs.** Every case result records the model, recording digest and date, measurement mode, fixture digest and date, all prompt versions, and `eval-scoring@1`.
9. **Nothing released changes.** `bench@1`/`bench@2` rules, canonicalization profiles, report builders and renderers, and digest formats are untouched. For live runs the evidence provenance remains `measured`; the only code change there is reading it from the result instead of a constant.

## Alternatives considered
- **Fuzzy prompt matching for measurement prompts.** Rejected: it hides real prompt changes and would score answers given for other numbers.
- **Reconstructing old recordings' measurements.** Impossible: recordings store prompt hashes, not prompts. Rejected anyway: pairing old answers with re-derived prompts would be fabrication.
- **Mocking the auditor entirely.** Rejected: it removes the agent under test.

## Consequences
- Both Mode C cases were re-recorded on 2026-10-16 with the pinned free model (`nvidia/nemotron-3-super-120b-a12b:free`, 30 of 45 free requests that day, including a 7-call attempt lost to an environment conflict). Fixture replay passes both, with byte-identical output across runs, and makes no model or benchmark calls. CI runs it in the integration job.
- Prerecorded measurements are labelled everywhere (fixture, results, blocks, evidence), so fixture runs can never pass as new measurements.
- A deliberate prompt or rule change now needs a re-record (a few free requests), as for every other case.
- R19 is closed as a risk; live-path variability stays documented under R1.
