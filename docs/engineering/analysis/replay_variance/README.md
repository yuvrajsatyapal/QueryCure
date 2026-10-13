# Same-machine experiment-replay variance (Phase 4, T4.7 acceptance, D9)

Measured 2026-10-13 on the owner's laptop (arm64, Docker Desktop), PostgreSQL 17, real sandbox clones. No LLM is involved. Each pair runs the `orders_ecommerce` composite-index experiment, using the committed fixture's config with a new id and the pair's seed. It then replays the experiment exactly as experiment replay does: same config and seed, new experiment id, scored by `bench@2`. The two results go through `replay.comparison.compare_experiments` (margin 1.25, 2,000 resamples). Script: [`measure.py`](measure.py). Raw results, including every integer-nanosecond sample and the full comparison: [`data/`](data/). The file names give the scale factor and seed.

## Results (14 pairs)

| Path | sf | Seeds | Pair results | Point drift D (both param sets) |
|---|---|---|---|---|
| host relay (`docker-relay`) | 0.1 | 1000–1003 | 3 × `inconclusive: insufficient_evidence`, 1 × `inconclusive: verdict_inconclusive` | 0.87–1.05 |
| host relay | 1 | 2000–2002 | 3 × `inconclusive: insufficient_evidence` | 0.83–1.24 |
| container (`docker-network`, ADR-0020 default) | 0.1 | 3000–3003 | **1 × `reproduced`** (seed 3002, D CIs [0.81, 1.02] and [0.81, 1.04]), 1 × `inconclusive: drift_undetermined` (seed 3000, CIs [1.03, 1.26] and [1.07, 1.43]), 2 × `insufficient_evidence` | 0.91–1.19 |
| container | 1 | 4000–4002 | 3 × `inconclusive: insufficient_evidence` | 0.98–1.55 |

**No pair was `not_reproduced`.** No verdict flipped between `verified` and `rejected`. No direction reversed, and result fingerprints always matched.

## Reading

- **T4.7 acceptance** ("same-machine replay of `orders_ecommerce` yields `reproduced` or a documented `inconclusive`") is met. One pair reproduced on the default container path, and the rest are documented `inconclusive`.
- **Why so many `inconclusive`:** gate 4 (robust CV ≤ 0.25 on every arm and parameter set) fails for at least one parameter set in 12 of 14 pairs (11 pairs end `insufficient_evidence` overall; seed 1003 ends `verdict_inconclusive` because one side's verdict was already inconclusive). The candidate arm runs in about 0.1–1 ms, where Docker Desktop scheduling noise dominates (risk R1). This is the same mechanism that makes single experiments `inconclusive` in Phase 3. Replay inherits it by design: "no evidence of a difference" never counts as a reproduction.
- **Margin `m` (D9):** the margin only matters for pairs that pass gate 4 (2 of 14). One reproduced at 1.25. The other's upper CI bound (1.26 and 1.43) narrowly exceeds 1.25. Point drifts for every parameter set stay inside 0.83–1.24 in 12 of 14 pairs. The two outliers (1.27 for seed 4000 and 1.55 for seed 4002, both sf=1 on the container path) fail gate 4, so their intervals would not count either way. Widening `m` would turn at most one more pair into `reproduced`, and it would weaken what "reproduced" means. **Recommendation: keep `m = 1.25`.** This is recorded as the D9 resolution proposal in CURRENT_PHASE and is the owner's call.
- **Limits:** one machine, one workload, 14 pairs. "Reproduced" here means consistent in one pair of runs (REPLAY_ENGINE §9.4).

## Reproduce

```bash
cd backend && uv run python ../docs/engineering/analysis/replay_variance/measure.py --sf 0.1 --pairs 4 --out /tmp/rv
# container path (rebuild the worker image first: docker compose -f infra/docker/compose.yaml build worker)
docker compose -f infra/docker/compose.yaml run --rm --no-deps -e QC_BACKEND=/app -e PYTHONPATH=/app \
  -e QC_TEST_SANDBOX_URL=postgresql://qc_sandbox_admin:qc_local_dev_only@sandbox-db:5432/sandbox_admin \
  -v "$PWD/backend/tests:/app/tests:ro" -v "$PWD/backend/evals:/app/evals:ro" \
  -v "$PWD/docs/engineering/analysis/replay_variance:/work" \
  worker /opt/venv/bin/python /work/measure.py --sf 0.1 --pairs 4 --runtime docker-network --out /work/data
```
