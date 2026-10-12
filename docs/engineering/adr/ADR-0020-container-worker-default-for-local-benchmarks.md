# ADR-0020: The containerized worker is the default for local Mode C benchmarking

- Status: Accepted (2026-10-12), owner decision D12
- Area: Deployment / Benchmarking
- Related: [ADR-0007](ADR-0007-sandbox-template-clones.md) (sandbox clones), [ADR-0018](ADR-0018-robust-sample-quality-gate.md) (measured round-trip noise), DEPLOYMENT §2, SECURITY §8

## Context

In the local profile, a worker on the host reaches `sandbox-db` through `sandbox-relay`, a loopback-only socat that crosses Docker Desktop's host↔VM port forward. A bare `SELECT 1` round trip costs 355–451 µs median that way, against ≈ 40 µs from a container on `sandbox_net` (ADR-0018, measured 2026-10-12). For sub-millisecond arms the hop is a large share of each sample and most of its jitter. Phase 3 shipped the container worker as an opt-in (`--profile bench`).

## Decision

- `docker compose up -d` now starts the worker container. It joins `default` and `sandbox_net` and benchmarks in-network. That is the default and documented path for local Mode C benchmarking.
- **Host-run development stays supported.** Start only the databases and the relay (`docker compose up -d metadata-db sandbox-db sandbox-relay`), then run the worker and API on the host. The relay stays in compose, because integration tests and host processes need it.
- Each worker records which path it measures through. `EngineOptions.container_runtime` is `docker-network` for the container (set by compose through `QC_BENCH_PATH`) and `docker-relay` on the host. It lands in the environment fingerprint that already exists (`container_runtime`), so reports and replays can tell the two apart. The fingerprint's shape is unchanged.
- **Sandbox isolation is unchanged:**
  - `sandbox_net` stays `internal: true`, and `sandbox-db` publishes no port and has no egress;
  - the relay publishes only `127.0.0.1:55432`;
  - the worker container runs as the non-root `qc` user;
  - the worker is the only application process on `sandbox_net`.
  It has egress through `default`, which it needs for the LLM provider; the sandbox does not.

## Options considered

1. Keep the host worker as the default: lowest friction, highest noise. Rejected by the owner.
2. **Container worker by default, host worker still supported** (chosen).
3. Remove the relay and the host path: breaks host-run tests and debugging. Rejected.

## Consequences

- One `docker compose up -d` gives low-noise local benchmarks. A developer who also runs a host worker gets two workers claiming jobs: still correct with `SKIP LOCKED`, but the measurement path then varies per run. The docs say to run one or the other, and the fingerprint records which one ran.
- The worker image must be rebuilt after backend changes (`docker compose up -d --build worker`).
- Phase 5 deployment is unaffected: the public demo runs no live sandbox.
