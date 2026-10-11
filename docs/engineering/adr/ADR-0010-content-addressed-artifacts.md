# ADR-0010: Content-addressed artifacts (SHA-256 over canonical bytes) stored in the metadata DB

- Status: Accepted (2026-10-11); amended by [ADR-0015](ADR-0015-canonicalization-finalization-integrity.md)
- Area: Replay / Data

## Context
Reports must be replayable without LLM calls and integrity-checkable (ADR-0015 narrows this: digests detect inconsistency relative to stored references; they are not tamper-proof against a compromised metadata store); artifacts (queries, plans, configs, outputs) are mostly small (KB–MB).

## Alternatives
1. Store blobs inline in each owning table — simple; duplicates; no uniform integrity story.
2. Object storage (S3/R2) keyed by hash — scalable; another service and credentials.
3. **`artifacts` table keyed by SHA-256 of canonicalized content, linked to runs via `run_artifacts`**, 5 MB cap per artifact.

## Decision
Option 3, behind an `ArtifactStore` interface so option 2 can replace the backend later.

## Rationale & trade-offs
- + Uniform hashing, dedupe, integrity checks, simple backups.
- − DB size grows with plans/reports; retention sweeps and size caps keep it bounded.
- − Canonicalization rules become a compatibility contract (versioned via `canonicalization`). Concrete profiles and the digest definition are specified in ADR-0015.

## Consequences
Every value shown in a report must come from a persisted record or artifact (enables report replay).
