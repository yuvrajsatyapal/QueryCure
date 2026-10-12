# ADR-0018: Robust dispersion for the sample-quality gate, checked after decisive regressions

- Status: Accepted (2026-10-12). Owner review (2026-10-12): approved in principle, on condition that the statistical assumptions are documented and decisive regressions cannot rest on insufficient or biased evidence. Both conditions are met by [ADR-0019](ADR-0019-noise-warning-verification-and-corroborated-regression.md) (`bench@2`); this record is kept as written for `bench@1`.
- Amended by: [ADR-0019](ADR-0019-noise-warning-verification-and-corroborated-regression.md) (gate 5 corroboration, D11 resolution)
- Area: Benchmarking / Verification
- Amends: [ADR-0008](ADR-0008-benchmark-statistics.md), BENCHMARK_ENGINE §6–§7

## Context
ADR-0008 makes speedups robust: the verdict uses the ratio of **medians** with a percentile-bootstrap CI. Gate 4 then required `CV = stdev / mean ≤ max_cv (0.25)` for both arms. On the first real sandbox runs (Phase 3, local profile, Docker Desktop on an Apple M2 shared with other dev servers, load average ≈ 5), we found the following:

- **A bare `SELECT 1` round trip through the published sandbox port already has a robust CV of 0.26–0.28** (median 355–451 µs, p99 ≈ 1.6–1.7 ms; 300 samples each, direct port and relay). Arms whose latency is a few round trips are therefore at the gate threshold from network jitter alone.
- **Classic CV is set by single spikes.** In three back-to-back runs of `orders_ecommerce` (sf=0.1, 30 samples per arm and param set), the composite-index arm had classic CV 0.30, 0.76 and 0.31. One 4 ms sample among 0.6 ms samples is enough. The bootstrap CIs of those runs were tight and far from 1 (for example [3.1, 3.8]×). Classic CV would have made all three `inconclusive`. Robust CV (below) passed all three.
- **Gate order hid decisive harm.** On `index_regression`, the candidate index was 4.6× faster for `open` and 5.5× **slower** for `escalated` (CI upper bound 0.25, far below `max_regression` 0.95). Gate 4 fired first on `open`'s dispersion, and the run ended `inconclusive` instead of `rejected: regression`.

## Options considered
1. **Keep classic CV and the gate order.** On this hardware nearly every sub-millisecond arm is `inconclusive`, and real regressions can be reported as inconclusive. The gate measures something the verdict does not use (mean and variance).
2. **Raise `max_cv`.** That is arbitrary, it is still dominated by the largest spike, and it weakens the gate on genuinely broad distributions.
3. **Use a robust dispersion measure that matches the median-based verdict, and let decisive regressions through first** (chosen).

## Decision
- **Robust CV** = `IQR / (1.349 · median)`. For normal data, IQR/1.349 estimates σ, so the threshold keeps its meaning. Unlike CV, it is not driven by a few spikes, yet it still flags broad or bimodal distributions (unit test: `1, 2, 3, 4 ms` cycling gives > 0.25). Classic CV is still computed and reported (`LatencySummary.cv`). The gate uses `robust_cv`, and `max_cv` keeps its default of 0.25.
- **Gate order** becomes: 1 build → 2 failures → 3 correctness → **4a** `n ≥ 10` → **5** regression → **4b** dispersion → 6 effect. A CI entirely below `max_regression` is rejected even when samples are noisy: noise only **widens** a bootstrap CI, so this cannot turn noise into a false rejection. Sample quality still guards every conclusion that needs precision (`verified`, `no_improvement`). Reason codes and gate numbers are unchanged (regression is still gate 5).
- This follows ADR-0009's asymmetry: evidence of harm can always reject, and evidence of benefit must be clean.

## Consequences
- The eval table's positive cases are `verified` on this machine most of the time. When they are not, the only tolerated outcome is `inconclusive` from gate 4 (`insufficient_evidence`), the documented noisy-hardware case in ROADMAP Phase 3 acceptance #2. Negative cases stay strict (`tests/integration/test_benchmark_eval_table.py`).
- The noisy-environment eval case (injected 0–20 ms latency on every execution) still ends `inconclusive: insufficient_evidence` from gate 4.
- `bench@1` is the first released engine version, so no stored results change. Any later change to these rules bumps `engine_version`.
- Residual risk: a long, smooth drift (for example thermal throttling across the whole run) can widen the IQR without spikes. Block interleaving spreads drift across arms, and the gate still catches the widened distribution.
- **Measured after this ADR (same day):** with the worker in a container on `sandbox_net`, the sf=1 `orders_ecommerce` candidate median fell from 0.88 ms to 0.29 ms (177×, 95% CI 144–211×), but its robust CV was still 0.44 (≈ 0.1 ms absolute jitter on a shared 8-core VM). On hardware like this, gate 4b still blocks very fast winners. The policy question is open decision D11 (CURRENT_PHASE); this ADR does not decide it.
- Reducing the noise itself is out of scope here. Running the worker container on `sandbox_net` would remove the published-port hop (DEPLOYMENT §2) and is a Phase 5 deployment item.

## Amendment note (2026-10-12)
The decision text above remains the `bench@1` rule. [ADR-0019](ADR-0019-noise-warning-verification-and-corroborated-regression.md) adds, for `bench@2`:
- the explicit assumptions behind "noise only widens a bootstrap CI" (it holds for disturbances that are independent of the arm);
- corroboration requirements before gate 5 may reject: n ≥ 20, no baseline censoring, and every block slower;
- the D11 resolution, `verified_with_noise_warning` by independent replication, instead of a waiver.
