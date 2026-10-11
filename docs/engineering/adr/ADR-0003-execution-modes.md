# ADR-0003: Three execution modes; no AI-generated DDL on user databases; Mode B off on public demo

- Status: Accepted (2026-10-11)
- Area: Security / Product

## Context
Connecting to user databases and executing AI-generated SQL are the highest-risk capabilities. The product still needs live inspection and real benchmarks to be credible.

## Alternatives
1. Allow `EXPLAIN ANALYZE` and candidate DDL on user DBs with read-only/limited roles — most realistic data, unacceptable risk (EXPLAIN ANALYZE executes; DDL locks and writes).
2. Offline only — safe, but cannot verify anything.
3. **Split modes**: A offline, B restricted plain-EXPLAIN inspection, C isolated sandbox benchmarking with synthetic or user-provisioned non-production data.

## Decision
Option 3. Mode B is enabled in the local profile and disabled by default on the public demo (SSRF and abuse surface); Mode C runs live only in the local profile, and the public demo shows prerecorded, labeled benchmarks.

## Rationale & trade-offs
- + Clear trust boundaries; AI DDL never touches user systems.
- − Verification happens on sandbox data, which may differ from production distributions; reports must say so.
- − Public demo is less "live" than a hosted DB-tuning SaaS.

## Consequences
Reports always state where verification ran. Sandbox-from-user-data (`pg_dump` subset + anonymization) is a Future feature requiring its own ADR.
