# ADR-0017: Deterministic optimization-materiality gate after synthesis

- Status: Accepted (2026-10-12)
- Area: Agents / Verification

## Context
The Phase 2 baseline eval `pk_lookup_already_optimal` failed calibration. The pinned free model (`nvidia/nemotron-3-super-120b-a12b:free`) proposed `missing_index` with **high** confidence for a 50-row settings table read in 0.039 ms. The plan does show a textbook pattern: a Seq Scan whose filter removes 49 of 50 rows. But no index can make that query meaningfully faster: execution is already below the 0.358 ms planning time, and the whole table fits in one page.

This is a judgment about materiality (is enough at stake to act on?), not about diagnosis. It can be computed from evidence we already hold, and models are poor at it (they pattern-match "Seq Scan + filter → index").

## Options considered
1. **Prompt guidance** in the synthesis prompt (`supervisor_synthesis@2`): every recording would have to be redone from scarce free requests (≈ 50/day), and the behaviour would remain a model property that varies by model and run.
2. **A latency cutoff** ("ignore queries under 1 ms"): simple but wrong both ways. A 0.5 ms query run 9 million times a day matters. A 0.04 ms index lookup on a 2-million-row table is already optimal, while the same latency from a Seq Scan on a table that is about to grow is not.
3. **A deterministic multi-signal check on evidence, applied after synthesis** (chosen).

## Decision
`evidence/materiality.py` computes a verdict from evidence only: `material`, `not_material` or `undetermined`. The signals are:

- **Workload frequency.** A matched `pg_stat_statements` row whose share of the captured statement time is ≥ 5% makes the query `material`, whatever its per-call latency. Rows are matched by query text with literals and `$n` normalised to one placeholder (`sql/fingerprint.match_key`); unparseable text never matches.
- **Measured latency against the query's own fixed overhead.** An analysed plan is required: without a measured execution time (plain EXPLAIN) the verdict is `undetermined`.
- **Spills.** A sort or hash spilling to disk makes the query `material`.
- **Data touched.** Scans read more than 1,000 rows (`actual_rows × loops + rows removed by filter`): `material`.
- **Table size.** A Seq-Scanned table that the catalog (`table_stat`) says holds more than 1,000 rows: `undetermined`, because a Seq Scan's cost grows with its table.

`not_material` requires every signal to agree: small data, a small Seq-Scanned table, execution time ≤ planning time, no spill, and not hot. Anything unmeasured leaves the verdict `undetermined`, and the gate only acts on `not_material`.

On `not_material`, in `synthesize_hypotheses`, after the citation validator and ranking:
- hypotheses are **kept and visible**, capped at `low` confidence; the reasons are appended to `uncertainty_notes`, and the materiality evidence is added to `contradicting_evidence`;
- the materiality evidence becomes `no_action_evidence`, and `write_report` ends the run **`no_action_needed`** (stop reasons still take precedence);
- the verdict is stored in state and in the interim report (builder `interim-report@2`, report schema 2), and an `agent.summary` event says "Not worth optimizing: …".

The model never sees the verdict and cannot override it, in line with the rule that deterministic checks outrank LLM output (ADR-0002, BENCHMARK_ENGINE).

## Consequences
- Calibration is now a property of the system, not of the model: `pk_lookup_already_optimal` passes on the **same recorded model output** that failed, with no prompt change and no re-recording.
- Thresholds (1,000 rows, 5% share) are named constants with a rationale in code. They are conservative: a wrong `undetermined` costs nothing, and only `not_material` changes the outcome.
- Offline runs have no catalog sizes or workload statistics. There the verdict rests on the plan alone, so `not_material` needs a measured plan whose execution time is below its planning time.
- The workload share is computed over the top statements captured, so it is an upper bound on the true share; this errs towards `material`.
- Report schema changes go through a new builder version (`interim-report@2`); `@1` reports are unchanged (ADR-0015).
