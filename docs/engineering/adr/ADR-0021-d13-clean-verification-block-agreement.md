# ADR-0021: Block agreement for the clean `verified` gate (D13): no change to `bench@2`

- Status: **Proposed** (2026-10-13). Awaiting an owner decision. Nothing in the engine, rules, schedule or tests has changed.
- Area: Benchmarking / Verification
- Relates to: [ADR-0008](ADR-0008-benchmark-statistics.md), [ADR-0018](ADR-0018-robust-sample-quality-gate.md), [ADR-0019](ADR-0019-noise-warning-verification-and-corroborated-regression.md) (residual risk R18), [ADR-0020](ADR-0020-container-worker-default-for-local-benchmarks.md)
- Evidence: [analysis/d13](../analysis/d13/README.md): harness, raw data from 3,050 real experiments, 135,000 simulated experiments

## Context

ADR-0019 left one known limitation, documented by the strict-xfail test `test_known_limitation_tight_bias_in_most_blocks_is_not_verified`. The clean `verified` path (gate 6) has no block check. A tight, arm-specific bias in 5 of 6 blocks is therefore verified: the baseline is 2× slower in blocks 1–5, block 0 shows no difference, and the iid bootstrap CI is [2.000, 2.000]. D13 asked whether `bench@3` should add block agreement to gate 6 and/or use more, smaller blocks. The owner asked for this to be investigated first, by measuring false-verification and false-inconclusive rates rather than individual fixtures.

## What was measured

**Rates.**
- *False verification* is P(clean `verified`) when the true speedup is below `min_effect` (1.10). It is measured at 1.0, 1.05 and 1.07.
- *False inconclusive* is P(not verified) at a true effect above `min_effect`.
- 95% Wilson intervals are given in brackets.

**Real PostgreSQL** (`bench@2` defaults, host relay on Docker Desktop; see analysis/d13 for the setup):
- `bench@2` re-scored from the raw blocks reproduced all 3,050 stored verdicts.
- Effect is the measured median; injected effects are a fixed baseline delay.

| True effect | Block size | Load | n | `bench@2` verified |
|---|---|---|---|---|
| 1.0 (neutral scan + PK) | 5 / 2 / 1 | no / yes | 1,450 | **0.0%** [0, 0.26] |
| 1.05 (injected) | 5 / 1 | no | 400 | **0.0%** [0, 0.95] |
| 1.07 (injected) | 5 / 1 | no | 400 | **0.0%** [0, 0.95] |
| 1.18 (injected) | 5 | no | 150 | 81.3% [74.3, 86.8] |
| 1.18 (injected) | 5 | yes | 100 | 49.0% [39.4, 58.7] |
| 1.18 (injected) | 1 | no / yes | 150 / 100 | 94.0% / 56.0% |
| 1.42 (injected) | 5 / 1 | no | 100 / 100 | 98.0% / 92.0% |
| ≈5.5 (composite index) | 5 / 1 | no | 50 / 50 | 88.0% / 94.0% (the rest: gate 4b) |

So all 2,250 experiments with a true effect below `min_effect` ended unverified, with an upper bound of 0.17%. Two more real checks:
- **Neutral arms** were `rejected: no_improvement` in 32 of 1,450 runs (2.2%). The nominal one-sided rate is ≤ 2.5%.
- **The iid bootstrap CI is close to calibrated on this host.** Over 2,700 per-param-set results at block size 5, 5.8% fell outside ±1.96 of the CI-implied standard error, against a nominal 5%. At block size 1 the figure was 3.8%.
- **There is no detectable position effect.** The arm that runs first in a block was not systematically slower: −0.6% ± 0.6% (scan), +0.7% ± 0.8% (PK), −0.9% ± 0.8% (under load).

**What each safeguard costs on the real data.** The table shows the share of the 1.18× `bench@2` verifications each safeguard keeps, at block size 5:

| Safeguard (added to gate 6) | 1.18× clean (bench@2: 81.3%) | 1.18× load (49.0%) | 1.42× (98.0%) | Catches the xfail fixture |
|---|---|---|---|---|
| every block ratio ≥ 1.0 | 78.7% | 47.0% | 97.0% | no |
| every block ratio ≥ `min_effect` (like S-blocks) | **52.7%** | **22.0%** | 96.0% | **yes** |
| one-sided sign test over blocks (p ≤ 0.05, i.e. 6 of 6 > 1.0) | 78.7% | 47.0% | 97.0% | only because its clean block is an exact tie |
| paired-block t lower bound ≥ 1.0 | 79.3% | 48.0% | 98.0% | no |
| paired-block t lower bound ≥ `min_effect` | 62.0% | 31.0% | 98.0% | no (lower bound 1.32) |
| block bootstrap lower bound ≥ `min_effect` | 78.7% | 43.0% | 98.0% | no (lower bound 1.50) |

On the real data, none of them prevented a false verification, because there were none to prevent. Every one of them costs some true verifications. The only rule that fixes the xfail fixture costs 27–29 percentage points at 1.18×.

**Simulation.** The simulation uses the real `bench@2` code, the real schedule and 500 experiments per cell. The table shows P(clean verified) at block size 5 for true effects 1.0 / 1.05 / 1.20; the full tables are in `results/sim_tables.md`.

| Disturbance | `bench@2` | + every block ≥ `min_effect` | + paired-t ≥ `min_effect` |
|---|---|---|---|
| iid + spikes | 0.0 / 0.0 / 96.4 | 0.0 / 0.0 / 69.0 | 0.0 / 0.0 / 84.2 |
| linear drift | 0.0 / 0.0 / 72.8 | 0.0 / 0.0 / 54.8 | 0.0 / 0.0 / 66.6 |
| step change | 0.0 / 0.0 / 58.0 | 0.0 / 0.0 / 41.2 | 0.0 / 0.0 / 49.6 |
| AR(1) correlated jitter | 0.0 / 0.0 / 60.2 | 0.0 / 0.0 / 34.0 | 0.0 / 0.0 / 44.6 |
| bursts | 0.0 / 0.0 / 59.0 | 0.0 / 0.0 / 30.4 | 0.0 / 0.0 / 31.2 |
| first-segment penalty (10%) | 0.0 / 2.2 / 70.0 | 0.0 / 0.6 / 10.2 | 0.0 / 0.8 / 25.8 |
| baseline delayed ×1.3 in a block, p = 0.5 | **27.0** / 39.0 / 97.8 | 1.0 / 4.2 / 81.4 | 5.2 / 13.0 / 86.4 |
| baseline delayed ×2 in a block, p = 5/6 (xfail family) | **53.2** / 51.6 / 53.2 | 26.6 / 29.4 / 52.2 | 53.2 / 51.6 / 53.2 |
| baseline delayed ×1.15 on every sample | **44.0** / 98.0 / 100 | 16.6 / 72.0 / 99.8 | 25.2 / 88.6 / 100 |

Schedule changes under `bench@2`, for true effects 1.05 / 1.10 / 1.20:

| Disturbance | Block size 5 | 5, counterbalanced | 2 | 1 |
|---|---|---|---|---|
| AR(1) | 0.0 / 3.6 / 60.2 | 0.0 / 3.4 / 58.8 | 0.0 / 0.6 / 64.2 | 0.0 / 0.4 / 64.4 |
| bursts | 0.0 / 1.2 / 59.0 | 0.0 / 0.4 / 56.6 | 0.0 / 2.2 / 69.0 | 0.0 / 1.6 / 74.4 |
| first-segment penalty | 2.2 / 15.2 / 70.0 | 0.0 / 1.0 / 83.6 | 0.0 / 6.2 / 78.8 | 0.0 / 3.4 / 81.6 |

## Findings

1. **Time-structured disturbances do not cause false verification in `bench@2`.** This covers drift, steps, correlated jitter and bursts. In the simulation the rate was 0.0% at 1.0× and 1.05× in every such model and schedule. On the real host it was 0 in 2,250 experiments, including runs under competing load. Interleaving with shuffled order does its job: these disturbances widen the CI and lower power, but they do not shift the estimate toward a win.
2. **The xfail family is a different kind of threat, and gate 6 cannot fix it.** The fixture's pattern is a bias in 5 of 6 blocks. From the data alone it cannot be told apart from a real effect masked by a disturbance in 1 of 6 blocks. Statistics that summarize blocks (the paired-t and block bootstrap CIs) are dominated by the 5 consistent blocks and verify it anyway. Only "every block ≥ `min_effect`" rejects it. Even that rule still verifies **26.6%** of neutral arms under the general version of the pattern, and it cannot detect a bias that is present in all blocks (16.6% at a ×1.15 bias, and that only because it is stricter). The real defence against arm-specific bias is outside a single experiment: separate clones and seeds in independent replicates, and the environment. ADR-0019 already says that a bias which recurs across runs on one host is not detectable.
3. **That threat was not observed on real hardware.** If block-level arm-specific disturbances at even the ×1.3 / p = 0.5 level were common here, the 650 neutral runs at block size 5 would have produced about 175 false verifications (27%). They produced none, and neither did the 800 runs at block sizes 1–2.
4. **Block agreement has a large, measured cost.** At a real 1.18× effect, "every block ≥ `min_effect`" turns 28.6 points of correct verifications into `inconclusive` (49 points → 22 under load). In the simulation it is worse under correlated noise (AR(1) 60 → 34 at 1.20×). Weaker rules (every block ≥ 1.0, sign test, paired-t ≥ 1.0, block bootstrap) cost 1–3 points, and none of them fixes the fixture.
5. **Smaller blocks are not free under `bench@2`.** In the simulation they help near the threshold: correlated jitter at 1.10× drops from 3.6% to 0.4%, and power at 1.20× is higher. Real calibration at block size 1 is slightly conservative (3.8% vs 5.8%). The real power gains (94% vs 81% at 1.18×) were measured at different times, so they are confounded and should not be relied on. But `bench@2`'s own block checks require *every* block to agree: R-blocks for regressions and S-blocks for the noise path. With 30 one-sample blocks those checks become far stricter. The simulated noise-warning path under bursts at 3× falls from 34.8% to 22.2%, and the raw-block S-blocks / R-blocks would have to be redefined on pooled windows. That is a rule change.
6. **Counterbalanced arm order** only removes a first-segment penalty (15.2% → 1.0% at the 1.10× boundary in the simulation). On this host that penalty was below the measurement resolution (|effect| ≤ about 1.5%).

## Decision (proposed)

**No change.** `bench@2`'s gate 6, its schedule, its block size and its verdict semantics stay as released. The strict-xfail test stays, because it documents a real limitation. Its framing gets corrected in the docs: the limitation is a property of single-experiment inference, not a missing gate-6 check.

Rationale: the smallest statistically defensible change has to buy a measurable reduction in false verification. On this host the measured false-verification rate is already 0 in 2,250 (upper bound 0.17%), and the simulated rate is 0 for every time-structured disturbance. The only safeguard that addresses the documented pattern still leaves a large share of that pattern verified. It also costs about 27–29 points of correct verifications at realistic effect sizes. That is not a good trade, and the evidence does not support it.

## If the owner wants a change anyway

These are ordered from least to most semantic impact. Each requires `bench@3`.

| Option | Effect | Compatibility implications |
|---|---|---|
| A. Report block diagnostics only: per-param-set paired-block CI, minimum block ratio, blocks agreeing. No verdict change | Transparency. The Phase 4 Benchmark Auditor can downgrade on it (ADR-0009) | New optional result fields: `ExperimentResult.schema_version` 3 with `exclude_if` for older schemas, so `bench@1`/`bench@2` bytes and digests are unchanged. OpenAPI and frontend types are regenerated. No migration |
| B. Gate 6 also requires a paired-block t lower bound ≥ 1.0 | Small cost (about 2 points at 1.18×). Rejects only experiments whose blocks conflict with the iid CI. Does **not** fix the xfail fixture | New reason code (for example `block_disagreement`) in `ReasonCode` and OpenAPI. `bench@2` stays frozen for replay. Replication requires `engine_version == ENGINE_VERSION`, so `bench@2` originals cannot be combined with `bench@3` replicates, and in-flight runs must finish on the version they started with |
| C. Gate 6 also requires every block ≥ `min_effect` | Fixes the fixture. 27–29 point power loss at 1.18×. Still about 27% false verification under the generalized pattern | As B, plus the eval table's tolerated outcomes need review: more gate-6 `inconclusive` results on positive cases |
| D. Block size 1–2 with block checks on pooled 5-sample windows | Better calibration and power near the threshold in the simulation. Keeps R-blocks / S-blocks working | `block_size` default changes. R-blocks / S-blocks are redefined, which is a rule change. About 5× more `benchmark_runs` rows per experiment (cost not measured with a real worker). Real-data validation on the container worker path is still needed |
| E. Counterbalanced arm order | Removes position bias. Not observed here | `build_schedule` changes, and resume and replay re-derive the order from the seed. The schedule algorithm must therefore be versioned with the engine, or stored `bench@1`/`bench@2` experiments would resume with a different order |

In every case, stored `bench@1`/`bench@2` verdicts are never re-scored, and prerecorded demo fixtures keep their engine version until they are re-recorded.

## Limitations of this analysis

- **One host, one measurement path.** All the real data comes from the host worker through the relay, not the ADR-0020 container path, and from two workloads at sf=0.1. Cloud or demo hardware could show disturbances that are tied to an arm, for example per-clone storage placement. Re-measure before relying on these numbers there.
- **Injected effects are a busy-wait added in the worker** to the baseline's timed region. They are genuine differences, but they do not exercise the plan or the cache the way a real index does.
- **The simulation model is a choice.** The arm-specific models were built to stress the gate and are defined per 5-sample segment. Real disturbances may be shaped differently.
- **A recurring bias that is stable across three runs remains undetectable** by any rule considered here (ADR-0019, residual risks).

## Consequences

- If accepted: R18 stays open with these measurements attached, D13 is closed as "no change", and the strict-xfail test keeps documenting the limitation. Revisit when the container path, cloud hardware or new workloads are measured, or when the Phase 4 Benchmark Auditor needs block diagnostics (option A).
