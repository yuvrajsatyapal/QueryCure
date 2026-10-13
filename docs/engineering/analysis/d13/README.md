# D13 analysis: does the clean `verified` gate need block agreement?

Evidence for [ADR-0021 (accepted 2026-10-13: no change)](../../adr/ADR-0021-d13-clean-verification-block-agreement.md). Collected 2026-10-13. None of this changes the engine. Every safeguard is evaluated **on top of** the real `bench@2` code (`querycure.benchmark.rules.assess`), and can only turn a clean `verified` into `inconclusive`.

## Contents

| File | What |
|---|---|
| `collect.py`, `load.py`, `campaign.sh`, `campaign2.sh` | Real-PostgreSQL collection. Runs `run_experiment` (engine `bench@2`, default config except `seed` / `block_size`) and stores the raw per-block samples |
| `rescore_real.py` | Rebuilds `CandidateEvidence` from the raw blocks, re-runs `bench@2` (asserting the stored verdict is reproduced), and applies each safeguard |
| `sim.py`, `analyze_sim.py` | Deterministic simulation of the engine's schedule and noise processes (seeded through `derive_seed`) |
| `rulesets.py` | The candidate safeguards |
| `results/real_report.txt`, `results/real2_report.txt` | Real re-scoring output |
| `results/sim_tables.md` | Full simulation tables (270 cells × 500 experiments) |
| `data/real.jsonl.gz`, `data/real2.jsonl.gz` | Raw measured samples, 3,050 experiments (`provenance`: measured; host worker through `sandbox-relay`) |

## Reproduce

From `backend/`, with `docker compose up -d sandbox-db sandbox-relay`, and the analysis directory as `D`:

```bash
zsh $D/campaign.sh                        # ~70 min, writes $D/real.jsonl
PYTHONPATH=.:$D uv run python $D/rescore_real.py $D/real.jsonl
PYTHONPATH=.:$D uv run python $D/sim.py $D/sim.json 500 --procs=7   # ~25 min on 8 cores
python3 $D/analyze_sim.py $D/sim.json
```

The simulation is bit-for-bit deterministic. The real campaign is not: it measures a shared host.

## Real setup

- Docker Desktop on an Apple-silicon Mac (8 cores, 8 GB), PostgreSQL 17 sandbox, host worker through the relay (`docker-relay`). This is **not** the ADR-0020 default container path, which has less noise. The figures are therefore an upper bound on that path's noise, but that path was not measured here.
- Workloads at sf=0.1: `orders_ecommerce` (about 3.4 ms sequential scan, 2 param sets) and `no_benefit` (sub-ms PK lookup, 1 param set).
- Arms:
  - **neutral:** an index the plan does not use. True speedup 1.0, but on a separate clone.
  - **genuine:** the composite index (about 5.5×).
  - **injected:** a neutral arm with a fixed busy-wait added to every *baseline* sample inside the timed region. This is a known, real difference: 0.2 / 0.3 / 0.7 / 1.7 ms gives measured medians of 1.05 / 1.07 / 1.18 / 1.42×.
- `--load`: a competing CPU-heavy query loop on the same server, 1–2 s on and 1.5–3.5 s off.

## Simulation model

The model is log-normal iid noise (σ = 0.07) with 3% spikes, plus one of:
- linear drift (+35% over the run);
- a step (+28% at a random time);
- AR(1) correlated jitter (φ = 0.95, sd 0.10);
- Poisson bursts (one per 60 samples, mean length 8, ×1.35–2.5);
- a first-segment-of-block penalty (+10%);
- a baseline segment delayed in a block with probability p (×1.3 at p=0.5, ×2 at p=5/6: the xfail family);
- a persistent baseline delay (×1.15).

True effects: 1.0, 1.05, 1.10, 1.20, 1.50, 3.0. Schedules: block size 5 (current), 5 counterbalanced, 2, 1, 1 counterbalanced. The arm-specific per-block models are defined per 5-sample segment, so they are only comparable across schedules at block size 5.
