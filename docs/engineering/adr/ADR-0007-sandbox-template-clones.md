# ADR-0007: Sandbox benchmarks use template-database clones on a dedicated Docker PostgreSQL

- Status: Accepted (2026-10-11)
- Area: Benchmarking / Security

## Context
Each candidate needs an identical starting database; experiments must not interfere; AI DDL must be contained.

## Alternatives
1. One database, apply/rollback DDL between arms — cheap; leftover effects (bloat, stats, cache) bias results; DDL rollback can't undo everything.
2. One container per arm — strong isolation; slow, and arms then run on different "machines".
3. **One sandbox server, template DB per workload version, `CREATE DATABASE … TEMPLATE` clone per arm.**
4. `pg_dump/pg_restore` per arm — slow for millions of rows.

## Decision
Option 3, one experiment measuring at a time per sandbox server (advisory lock), network-internal Docker container with resource limits.

## Rationale & trade-offs
- + Arms share hardware/config → fair comparison; clones are fast file copies; clean teardown.
- − Template DBs cannot have active connections during cloning (provisioner manages this).
- − Shared buffers are shared across clone DBs on the same server; warm-up per arm and interleaving mitigate.
- − Docker isolation is not a VM boundary (documented residual risk).

## Consequences
Disk usage = template + N clones; provisioner enforces max concurrent clones and cleans orphans on startup.
