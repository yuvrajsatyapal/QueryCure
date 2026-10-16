# ADR-0023: Experiment-replay equivalence margin (D9) stays at 1.25

- Status: **Accepted** (2026-10-16, owner approval). Proposed 2026-10-13 in [PHASE_4_REPORT](../../planning/reports/PHASE_4_REPORT.md) §2 and §10. No code, rule, profile or stored result changes.
- Area: Replay / Verification
- Relates to: [ADR-0015](ADR-0015-canonicalization-finalization-integrity.md) (equivalence-margin comparison), [ADR-0022](ADR-0022-phase4-verification-replay-implementation.md), [REPLAY_ENGINE §9.1](../../architecture/REPLAY_ENGINE.md), risks R1 and R19
- Evidence: [analysis/replay_variance](../analysis/replay_variance/README.md): 14 same-machine pairs of the `orders_ecommerce` composite-index experiment on real PostgreSQL 17

## Context

Experiment replay classifies a pair as `reproduced` only when the 95% CI of the speed-up drift `D = S_replay / S_original` lies inside `[1/m, m]` (REPLAY_ENGINE §9.1). The default `m = 1.25` (±25%) was set in ADR-0015 and left open as D9 until real same-machine drift had been measured.

The Phase 4 measurement (T4.7) gave:
- 2 of 14 pairs passed the gate-4 evidence check on both sides; the other 12 are `inconclusive: insufficient_evidence` (noise, R1).
- Of the two: 1 `reproduced` at 1.25; 1 `inconclusive: drift_undetermined`, with an upper drift bound of 1.26–1.43.
- Point drifts stayed inside 0.83–1.24 in 12 of 14 pairs. 0 pairs were `not_reproduced`; result fingerprints always matched.

## Decision

1. **`m` stays at 1.25.** `DEFAULT_MARGIN` in `replay/comparison.py` is unchanged.
2. **The margin is not widened to raise the reproduction rate.** Widening it would turn the `drift_undetermined` pair into `reproduced` while proving nothing new about reproducibility. A wider band weakens the equivalence test instead of improving the measurements.
3. **The low reproduction rate is a measurement-noise problem**, to be addressed by better measurement conditions or more evidence, never by a looser classification.
4. **Released contracts are untouched:** `bench@1` and `bench@2` semantics, canonicalization profiles, report builders and renderers, digest formats and every stored replay result. Each attempt already stores its margin in `result.config`, so stored comparisons keep their meaning whatever a future default is.

## Alternatives considered
- **Widen to 1.5.** The `drift_undetermined` pair would count as `reproduced`. Rejected: the band would then accept a 50% shift in the speed-up as "the same result", and the change would be motivated by the outcome it produces.
- **Choose `m` per workload or from observed variance.** Rejected for the MVP: the margin would depend on the data it judges, and comparisons across attempts would stop being comparable.

## Consequences
- ROADMAP Phase 4 criterion #2 is recorded as **partially demonstrated**: the implementation is complete and meets TASKS T4.7 ("reproduced or a documented inconclusive"), but the stronger roadmap wording (agreeing verdicts and overlapping CIs) held in only part of the 14 pairs on noisy hardware.
- Most same-machine replays on Docker Desktop will keep ending `inconclusive`. The UI and reports already say so honestly.
- Any later change to the default needs a new ADR, plus updates to REPLAY_ENGINE and the golden vectors (ADR-0015).
