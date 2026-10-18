# ADR-0028: Evidence-specific claim grounding (`claims@2`)

- Status: Accepted (2026-10-18); supersedes `claims@1` for new runs, amends ADR-0026 §1
- Area: Agents / Evidence integrity

## Context

`claims@1` (ADR-0026) removes sentences that contradict recorded evidence. It compares each sentence against everything the run recorded, pooled into flat lists: every speed-up and confidence bound, every interval, every latency, every scan type. Two weaknesses remained (backend hardening, 2026-10-18):

1. **Misattribution.** A speed-up measured for candidate A validates a sentence about candidate B. The same goes for a figure from one param set or one experiment used for another. Status checks needed the model to write arm IDs (`oc_…`), and in practice the model names "the composite index" or "ANALYZE". So "ANALYZE was verified" survived whenever any arm was verified, and "Running ANALYZE made the query 4.72x faster" survived because 4.72 was the composite index's figure.
2. **Coverage.** Regexes missed paraphrases: "4.7-fold", "a factor of 4.7", "a speed-up of 4.7", "reduced latency by 79%", absolute savings, "from 3.62 ms to 0.51 ms" (a baseline median and a candidate median from two different param sets), guarantees, advice against a verified change, estimate direction, and "fresh" statistics. One denial word anywhere in a sentence ("…, although ANALYZE was inconclusive") also disabled the recommendation check for the whole sentence. In the other direction, every descriptive mention of an unverified change was treated as a recommendation of it.

Constraints:
- `claims@1` behaviour must not change silently (ADR-0026).
- Sealed reports must replay byte for byte (ADR-0015).
- Eval recordings match prompts exactly (ADR-0024), and the free quota is about 45 requests a day.
- No new LLM call.

## Decision

1. **New checker version `claims@2` (`agents/claims_v2.py`).** `agents/claims.py` stays as the frozen `claims@1`, and its tests still run against it. Every grounding boundary listed in ADR-0026 §1 now calls `claims@2`. New runs record `checker: "claims@2"` in `narrative_check` and in each output's `claim_check`. Before this change, `claim_check` carried no version; claim checks stored before then are `claims@1`.
2. **Attribution before checking.**
   - **Clauses.** A sentence is split at clause boundaries (`;`, `, while`, `, but`, `, although`, …).
   - **Subjects.** Each clause is resolved deterministically to the subjects it names:
     - arms, by ID or by the action named (ANALYZE, a rewrite, extended statistics, or an index narrowed by its columns and by "composite" or "single-column");
     - "all candidates", but not "all *other* candidates";
     - param sets, by name;
     - whether it describes the baseline plan or a candidate plan.

     A clause that names no subject inherits the sentence's subjects.
   - **Narrowed context.** The `claims@1` rules run on a context narrowed to those subjects: their own speed-ups, intervals and medians; their own replicated range (auditor only); and their own measured plan's scan types. The baseline plan admits only baseline scan types: its EXPLAIN evidence plus its measured plan.
   - **Fallbacks.** With no subject, or with no attributed measurements recorded, the pooled `claims@1` check applies unchanged.
3. **Typed claims.** Quantitative statements that `claims@1` does not parse are extracted into `TypedClaim` objects (`speedup`, `percent`, `saving`, `transition`) and checked against the subjects' measurements:
   - a percentage *reduction* must equal 1 − 1/speed-up and can never reach 100%;
   - a saving must equal a baseline − candidate median difference;
   - a transition must be the baseline and candidate medians of one measurement.

   Other new rules:
   - a guaranteed improvement is unsupported (a negated guarantee is kept);
   - a named subject's stated status (verified, rejected, inconclusive) must match its verdict, with "only" tolerated when one subject matches;
   - "cleanly verified" contradicts `verified_with_noise_warning`;
   - advising against a verified change is a contradiction;
   - "under/overestimates" must match a recorded node's direction;
   - "estimates are accurate" contradicts an estimate off by 10× or more;
   - "statistics are up to date" contradicts stale evidence;
   - in a clause about estimates, "N×" is an estimate ratio wherever the word "estimate" sits.
4. **Recommendations.** The `claims@1` action rule applies only to clauses that recommend something (an imperative, or wording such as "should" or "recommend"). It is evaluated per clause, so a denial in another clause no longer hides it.
5. **Typed claims stay deterministic.** Requiring the models to emit structured claim objects was considered and rejected. It changes every prompt, so every eval recording would have to be re-recorded (more than the daily free quota). Free models also often fail stricter schemas (ADR-0026 O1), and an extra model-side format is not needed when extraction is deterministic.

## Consequences

- A figure, interval, status or saving can only stand for the candidate, param set and experiment it was measured for. The run-2 audit texts are still removed: all `claims@1` regression cases pass under `claims@2` (`test_claims_v2_compat.py`).
- Precision improves where `claims@1` was conservative:
  - descriptive sentences about unverified candidates' measured figures survive;
  - true statements about a candidate's measured plan survive in the auditor;
  - "underestimates … by 12×" is no longer read as a speed-up.
- Still pattern-based. A contradiction phrased in a form no rule recognises can pass, and a sentence that mixes a supported and an unsupported claim is removed whole. Verdicts remain deterministic (ADR-0009), so this is defence in depth.
- `write_report` does not load candidate plans, so its final reconciliation uses baseline plan types only (as `claims@1` did). The Optimization Engineer gets no action context, because its new proposals would otherwise read as recommendations of unverified earlier candidates.
- No prompt changed. The five recorded smoke evals still replay 5/5 with the same drop counts, and sealed reports are untouched (`report-builder@1` does not read claim checks).
