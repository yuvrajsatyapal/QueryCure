# ADR-0019: Corroborated regressions and `verified_with_noise_warning` by independent replication (`bench@2`)

- Status: Accepted (2026-10-12). Owner decisions: ADR-0018 approved in principle with documented assumptions; D11 resolved as specified here (not a plain waiver of gate 4b).
- Area: Benchmarking / Verification
- Amends: [ADR-0018](ADR-0018-robust-sample-quality-gate.md) (gate 5 preconditions), [ADR-0008](ADR-0008-benchmark-statistics.md) (adds a replication rule), BENCHMARK_ENGINE §6–§7. Does not change [ADR-0009](ADR-0009-deterministic-verification-authority.md): rules still own verdicts, and the Benchmark Auditor (Phase 4) may downgrade this outcome like any other.

## Context

ADR-0018 left two problems.

1. **Its regression shortcut leans on an assumption that is only partly true.** "Noise only widens a bootstrap CI" holds for noise that is *independent of the arm*. It fails for noise that hits one arm more than the other, or for evidence that is biased:
   - A burst of background load that lands on one arm's samples in several blocks shifts that arm's median. It does not just widen it.
   - Timed-out samples are excluded from the statistics. If the **baseline** loses its slow tail this way, its median is biased fast, and the candidate looks regressed.
   - With n between 10 and 20, the percentile bootstrap of a median is coarse. ADR-0008 already calls small n a known weakness.
   A single experiment cannot tell an arm-specific disturbance from a real regression, so a decisive rejection needs corroboration inside the data.

2. **D11.** On Docker Desktop, sub-millisecond winners have about 0.1 ms of absolute jitter. Their robust CV exceeds 0.25 even when the effect is 177×. The proposed fix was to waive gate 4b when the CI lower bound is at least 2 × `min_effect`. The owner rejected a plain waiver: the gate exists because a noisy experiment can produce a **misleadingly narrow CI**. The iid bootstrap assumes independent samples, and block-correlated disturbances, drift and bimodality break that. A large lower bound from one experiment does not repair that.

## Statistical assumptions (made explicit)

These hold for both `bench@1` and `bench@2` unless noted. Each one says which check defends it.

| # | Assumption | What breaks it | Defence |
|---|---|---|---|
| A1 | Samples within an arm × param set are exchangeable (iid enough for the percentile bootstrap of the median) | Drift, block-correlated bursts, cache phase changes | Interleaved blocks, so drift hits all arms. Since `bench@2`: block-level agreement for decisive conclusions (§Decision 1, 2) |
| A2 | Disturbances are independent of arm assignment, so they widen the CI and do not shift it | A burst that coincides with one arm's runs; per-clone effects (file layout, page cache) | Shuffled arm order inside blocks. Block agreement (one experiment). Independent replicates with fresh clones and seeds (D11 path) |
| A3 | No informative censoring: excluded samples are not systematically the slow (or fast) ones | Timeouts on the baseline remove its slow tail, so a regression looks larger | Gate 2 caps failures at 10%. Since `bench@2`: a decisive regression or a noise-warning verification needs a baseline with zero failures |
| A4 | n large enough for the median CI | n < 20: coarse, discrete quantiles | Gate 4a n ≥ 10 for anything. `bench@2`: n ≥ 20 to reject for regression, n ≥ 30 for the noise path |
| A5 | Arms are independent (the bootstrap resamples each separately and ignores pairing within blocks) | Shared disturbances make arms positively correlated | Ignoring a positive correlation makes the ratio CI **wider**, so this is conservative |
| A6 | The speedup is stationary: one effect size for the whole experiment | Bimodal plans, plan flips mid-run, warm-up not finished | Warm-up runs. Block agreement. Replicate CIs must overlap |

## Decision

`ENGINE_VERSION` becomes **`bench@2`**. Gates 1–4a, 4b and 6 keep their `bench@1` definitions. The changes are additive.

### 1. Gate 5: a regression must be corroborated before it can reject

A param set *indicates* a regression when its speedup CI upper bound is below `max_regression` (unchanged). It **rejects** (`rejected: regression`, gate 5) only when all of these hold for that param set:

- **R-n:** n ≥ 20 on both arms (`REGRESSION_MIN_SAMPLES`), the same floor ADR-0008 uses for "stricter rules below 20".
- **R-censor:** the baseline has no failed samples (timeouts or errors) on that param set (A3).
- **R-blocks:** at least 3 measured blocks contain samples of both arms, and in **every** one of them the block-median ratio `median(baseline block) / median(candidate block)` is below `max_regression`. This is a sign-type test across interleaved blocks, and the CI condition must hold as well.
  - *Refined during implementation (2026-10-12, before release):* the first draft counted a block as slower when its ratio was below 1.0. Measured on real PostgreSQL, a block with no true difference falls below 1.0 about half the time. Even for a ~4 ms scan, block ratios for a neutral index ranged from 0.54 to 1.57. So "< 1.0" corroborated an arm-specific disturbance in 5 of 6 blocks roughly half the time. Requiring each block to be below `max_regression` lowers that rate, but it is still probabilistic (see Consequences).

If any param set's regression is corroborated, the candidate is rejected; the first such param set in configuration order is reported. If regressions are only *indicated*, the verdict is `inconclusive: insufficient_evidence` at gate 5, and the detail names the failed condition. A regression signal can therefore never be dropped, and the candidate can never be verified past it. All it loses is the right to call the regression decisive.

This keeps ADR-0009's asymmetry and narrows it: noisy evidence may still reject, but not biased or thin evidence.

### 2. D11: a per-experiment noise screen, and the existing `inconclusive` stays

When an arm fails **only** gate 4b (every earlier gate passed), the engine records a **noise screen** for that arm in the result. Gate 6's effect condition is one of the screen's checks (S-effect), so a screen exists for every gate-4b stop and is eligible only when the effect is there. The verdict stays `inconclusive: insufficient_evidence` (gate 4), exactly as in `bench@1`. The screen is *eligible* only if every check passes:

| Check | Rule | Defends |
|---|---|---|
| S-n | n ≥ 30 on both arms, every param set (`NOISE_MIN_SAMPLES`), and ≥ 4 blocks with both arms | A4, block test power |
| S-censor | zero failed samples on both arms, every param set | A3 |
| S-noregress | every param set's CI **lower** bound ≥ `max_regression`. Clean `verified` only needs the upper bound ≥ `max_regression`; this path needs evidence of *no* harm, not merely no evidence of harm | "no per-parameter-set regressions" |
| S-effect | primary CI lower bound ≥ `min_effect` | gate 6 |
| S-separation | primary param set: `Q3(candidate) × min_effect ≤ Q1(baseline)`. The middle halves of the two distributions are separated by at least the required effect. This is distribution-free and does not use the bootstrap at all | the misleadingly narrow CI (A1, A6) |
| S-blocks | primary param set: in **every** block, the block-median ratio is ≥ `min_effect` | A1, A2 |

### 3. D11: `verified_with_noise_warning` needs agreement across independent experiments

A new deterministic function (`benchmark/replication.py`) assesses one candidate across **R = 3** experiments. The first experiment is the one the human approved. The other two are **replicates** that run only if the first ended with that arm screen-eligible and with no verified winner. The verdict is `verified_with_noise_warning` only if:

- **Independent:** distinct experiment ids, distinct seeds (each replicate gets its own interleaving schedule and bootstrap draws), and fresh clones per experiment (each experiment builds its own clones and drops them). Every replicate is `provenance = measured`. Prerecorded evidence never counts.
- **Comparable:** same `engine_version` (`bench@2`), same environment digest, same workload, baseline query, param sets and thresholds. The arm's exact SQL is identical, checked by `sql_digest`, which the engine also checks against the approval.
- **Each replicate passes on its own:** the arm is either cleanly `verified` or `inconclusive` at gate 4 with an eligible noise screen, and every param set's CI lower bound is ≥ `max_regression`.
- **They agree:** the primary param set's CIs have a common intersection (`max(lows) ≤ min(highs)`). A narrow CI that does not overlap its replicates shows that something varies between runs that a single CI does not capture. The result is then `inconclusive` (`replicates_disagree`).

The reported effect is conservative: the range runs from the **smallest** lower bound to the largest upper bound across replicates, and the warning states the largest robust CV observed. If fewer than three replicates complete (time budget, cancellation, sandbox failure), the arm keeps its `inconclusive` verdict.

**Approval scope.** The human approved exact SQL to run in disposable sandbox clones. Replicates run the same SQL, checked again by digest, in new disposable clones. They need no new DDL, data or target. The approval card says that a noisy result may be re-measured up to two more times. Replicates count against the run's benchmark time budget.

**Outcome mapping.**
- The candidate status is `verified_with_noise_warning`. This is a new value; existing statuses are unchanged.
- The run outcome is `verified_recommendation`. The report and the UI always show the warning text next to it, and they never shorten it to "verified".
- In the tournament, a noise-warning winner ranks by its smallest replicate CI lower bound.

## Options considered

1. **Waive gate 4b when the CI lower bound ≥ 2 × `min_effect`** (the original D11 recommendation). Rejected by the owner. A single experiment's iid CI is exactly what noise makes untrustworthy.
2. **Block bootstrap inside one experiment.** It addresses A1 but not A2: per-clone and per-run effects are shared by all of an arm's blocks. With 6 blocks per arm the block bootstrap is also very coarse.
3. **Raise `max_cv` for fast arms.** Arbitrary, and it hides the problem.
4. **Screen plus independent replication** (chosen). It costs measurement time, and only on the noisy path.

## Compatibility and versioning

- **Stored `bench@1` verdicts are never re-scored.** `experiments.engine_version`, the result artifact's `engine_version`, and every `verification.completed` event keep `bench@1`. A `bench@1` verdict means what the `bench@1` rules said. Old rows have no noise screen and no replicates, and nothing upgrades them retroactively. To get a `bench@2` verdict, run a new experiment.
- **The rules are versioned in code.** `rules.evaluate` dispatches on the engine version. The `bench@1` path is kept frozen, so Phase 4 experiment replay can score a replay with the **source experiment's** rules. A test re-scores the committed `bench@1` fixtures and asserts their stored stats and verdicts are reproduced exactly. `engine_version` becomes a material field for replay comparison (REPLAY_ENGINE §9.3): comparing a `bench@1` source with a `bench@2` replay is `cross_environment`, never "reproduced".
- **Artifact bytes do not change.**
  - `ExperimentResult.schema_version` becomes `1 | 2`. Only schema 2 carries `noise_screens`. On a schema-1 result the field is `None` and is omitted from output (`Field(exclude_if=...)`), so the API's OpenAPI schema stays fully typed. Re-serializing a stored `bench@1` result or a committed prerecorded fixture therefore gives byte-identical canonical JSON and the same SHA-256 (tested).
  - `RuleVerdict`, `SpeedupStats`, `ArmMeasurement`, `EnvironmentFingerprint` and `ExperimentConfig` keep their shapes.
  - Replication verdicts are a new artifact kind (`replication_result`), not a change to old ones.
- **Database (migration 0010, expand-only):**
  - `experiments.replicate INT NOT NULL DEFAULT 0`; existing rows are replicate 0, and the uniqueness of a round's original experiment is unchanged;
  - candidate status gains `verified_with_noise_warning`;
  - the artifact kind gains `replication_result`.
  - The downgrade restores the old constraints and refuses to run while new values are present.
- **Within `bench@2`,** a verdict can differ from `bench@1` on the same samples in exactly one way: a regression that is indicated but not corroborated is `inconclusive` (gate 5) instead of `rejected`. Gate 4b outcomes are identical. The noise screen never changes a single-experiment verdict.
- **Prerecorded demo fixtures stay `bench@1`** until they are re-recorded. They are labeled with their engine version.

## Consequences

- Decisive regressions on clean, consistent evidence are unchanged: `index_regression` is slower in every block. Regressions seen in only some blocks, or seen against a baseline with timeouts, become `inconclusive`. They are never verified.
- Fast, noisy, clearly separated wins can be verified, with a warning, at the cost of two extra experiments. Slow or overlapping noisy cases stay `inconclusive`.
- **Measured (2026-10-12, Docker Desktop, PostgreSQL 17, host relay):**
  - `orders_ecommerce` at sf=1, composite index, 5 seeds, no injected noise: 3 runs were cleanly `verified` on the first experiment. The other 2 stopped at gate 4b (candidate robust CV 0.46 and 0.66) and became `verified_with_noise_warning`, with conservative ranges of 43.7–67.4× and 16.3–71.9×.
  - With 0–2 ms injected noise at sf=0.1, 11 of 14 runs reached `verified_with_noise_warning`. The other 3 ended `inconclusive: replicates_disagree`: the iid CIs of separate experiments did not overlap, a direct measurement of A1/A6 not holding between runs.
- **Residual risks:**
  - Block corroboration is a sign-type test with few blocks (6 by default). With sub-millisecond arms, or with only one undisturbed block, an arm-specific disturbance that covers most blocks can still be corroborated. The integration test needs 20 blocks with 5 undisturbed to make that unlikely (about 0.35⁵). This bounds, but does not remove, the risk raised by the owner.
  - The clean `verified` path (gate 6) has no block check. An arm-specific bias present in nearly every block, with tight distributions, would be verified by `bench@1` and `bench@2` alike (documented by an `xfail(strict)` unit test). Fixing it would change the clean verification rule, which is an owner decision.
  - A disturbance that is systematic *and* stable across three runs on the same host (for example a clone-layout artifact that recurs) cannot be told apart from a real effect. That is true of any same-environment measurement, and the report's known limitations already say so.
  - The block sign test assumes blocks are roughly independent. Slow drift spanning the whole run correlates them. Interleaving still spreads it across arms.
  - Separation uses quartiles. A long-tailed candidate whose fast majority is separated passes, and that is intended: the verdict is about the median.
