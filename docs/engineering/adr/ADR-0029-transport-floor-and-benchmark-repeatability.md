# ADR-0029: Transport floor diagnostic and measured benchmark repeatability

- Status: Accepted (2026-10-18); amends BENCHMARK_ENGINE §4, §10, adds §12; complements ADR-0018, ADR-0019, ADR-0020
- Area: Benchmark engine

## Context

The 2026-10-17 real-model investigation recorded a robust CV of up to 0.47 and only 2 replicates. Before changing anything, the engine was measured. A repeatability harness (`benchmark/repeatability.py`) ran the same deterministic experiment as 20 independent sessions per configuration, each with its own experiment ID, seed and clones:
- workload `orders_ecommerce@v1:sf=0.1:seed=42`;
- one real-effect arm (composite index) and one null arm (an unused index).

Host: macOS, Docker Desktop VM with 8 CPUs and 4 GB, PostgreSQL 17.11. Raw data is in `docs/reports/data/benchmark-repeatability-2026-10-18/`.

Measurement-path findings (`bench@2`, unchanged; a single approved experiment):

| Path | Real index `verified` | Candidate median (hot) | Speed-up (hot / regular) | `SELECT 1` round trip |
|---|---|---|---|---|
| host relay (`docker-relay`) | 8 / 20 | 0.666 ms | 5.89× / 7.43× | 307–457 µs |
| in-network (`docker-network`) | 16 / 20 | 0.239 ms | 13.84× / 21.58× | 60–70 µs |

- **The relay dominates sub-millisecond arms.** Its fixed round trip is added to both arms of every sample, which compresses the measured speed-up toward 1 (5.9× vs 13.8× for the same index). Sub-ms dispersion then comes mostly from the network: the within-session robust CV is up to 1.3.
- **Host contention bursts.** Runs of consecutive blocks at 2–3× the usual median affect every arm on both paths.

Techniques evaluated:

| Technique | Evaluation | Decision |
|---|---|---|
| Relay CPU cap (`cpus: 0.5`) as the burst cause | cgroup `nr_throttled` unchanged across a run | Rejected: not the cause |
| GC disabled in the timed region | In-network A/B: no consistent change in median or robust CV | Rejected: no measurable gain |
| Per-sample (ABAB) interleaving instead of runs of `block_size` | Drift is already paired per block, and per-arm dispersion (gate 4b) does not depend on order | Not implemented |
| Randomized arm order, warm-up, bounded replicates | Already in `bench@2` (§4, ADR-0019) | Kept |
| Subtracting a transport estimate from samples | The floor's own jitter is independent of each sample's, so subtracting it adds variance and a bias model | Rejected |
| Paired (block-ratio) dispersion gate instead of per-arm robust CV | Would change verdict rules (a new engine version) and needs its own false-verification analysis | Deferred |
| Recording the transport floor | Separates "how much of a sample is transport" from the query time without touching samples | **Adopted** |
| Startup warning on the relay path | The measured path difference is large | **Adopted** |

## Decision

1. **Transport floor (diagnostic).** Each experiment times 25 bare `SELECT 1` round trips on the baseline connection before warm-up, and 25 more after measurement. This is outside every timed sample. The result gets an optional `transport_floor`:
   - `median_ns`, `iqr_ns`, and the medians of both windows;
   - `share_of_fastest_arm`, the floor median divided by the smallest arm median;
   - `transport_dominated` when that share is ≥ 0.5.

   Samples, statistics, gates, verdicts and replication never read it.
2. **No engine version bump.** Measured samples and every rule are unchanged, so results remain `bench@2`. The field is omitted when `None`, so every stored result, including the prerecorded eval fixtures, re-serializes to its original bytes and digest. Re-scoring persisted rows yields identical statistics and verdicts (integration test).
3. **Worker warning.** A worker with a sandbox configured and `QC_BENCH_PATH=docker-relay` logs `benchmark_path_relay` at startup.
4. **Repeatability harness** for future engine changes: `python -m querycure.benchmark.repeatability --sessions N [--replicated]`. It refuses non-local sandbox hosts, writes nothing to the metadata DB and calls no LLM.

## Consequences

- **Product-level stability**, measured after the change with replicates, 20 sessions per path:
  - the real index ends `verified` or `verified_with_noise_warning` in 18/20 sessions on the relay and 19/20 in-network;
  - the null index ends `inconclusive` in 20/20 on both paths (no false verification);
  - every relay session is flagged `transport_dominated` (share 0.53–1.27). In-network shares are 0.29–0.54.

  This change does **not** reduce noise. The in-network path does, and that was already the default.
- **Variation between batches.** Two independent 20-session batches on the same path differed: in-network single-experiment `verified` was 16/20 before and 13/20 after. That is the spread to expect on a shared laptop, and it is why no lower-noise claim is made for the engine itself.
- **Not yet surfaced in reports.** The floor reaches the experiment API (`ExperimentDetail.result.transport_floor`) but not the report or the auditor prompt. Surfacing it is a `report-builder@2` item, together with ADR-0026's `narrative_check`.
