# ADR-0006: Metadata schema conventions (UUID, TEXT, TIMESTAMPTZ, soft delete, no FK constraints)

- Status: Accepted (2026-10-11)
- Area: Data

## Context
The author's standing database conventions (applied across projects) require: UUID primary keys via `uuid_generate_v4()`, `TEXT` instead of `VARCHAR`, `TIMESTAMPTZ` in UTC, standard `created_at/updated_at/deleted_at`, soft deletes, a shared `updated_at` trigger, partial indexes on active rows, and **no foreign-key constraints or cascades** (integrity enforced in the application).

## Alternatives
1. Follow the conventions as-is.
2. Use FK constraints (PostgreSQL default best practice) — stronger integrity guarantees at the DB level.

## Decision
Follow the conventions (option 1) for all QueryCure-owned tables. Exception: LangGraph's checkpointer tables are managed by the library.

## Rationale & trade-offs
- + Consistency with the author's other projects; simpler migrations and retention purges (no cascade ordering surprises).
- − Orphans are possible if application code is wrong. Mitigations: all multi-table writes in transactions; repository-level existence checks; a periodic integrity check job (Post-MVP) that reports orphans; every relationship column indexed.
- − Append-only tables (events, benchmark runs, artifacts) are purged by retention jobs — the only hard deletes, executed by system jobs, never by user requests.

## Consequences
Repository tests must cover relationship validation. `CHECK` constraints are still used for enums and size limits (they are not foreign keys).
