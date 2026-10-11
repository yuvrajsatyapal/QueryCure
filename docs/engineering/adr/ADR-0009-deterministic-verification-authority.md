# ADR-0009: Deterministic rules own verdicts; the Benchmark Auditor LLM can only downgrade

- Status: Accepted (2026-10-11)
- Area: Agents / Verification

## Context
The core promise is "verified means verified". An LLM auditor is valuable for spotting contextual problems (e.g., speedup relies on a synthetic data quirk) but can hallucinate or be prompt-injected.

## Alternatives
1. LLM decides verdicts from benchmark data — flexible, unreliable.
2. Deterministic rules only — reliable, misses contextual concerns.
3. **Deterministic gates produce the verdict; the LLM auditor may downgrade `verified → inconclusive` with a recorded reason, never upgrade.**

## Decision
Option 3. `benchmark` module has no dependency on `llm`/`agents` (import-linter contract).

## Rationale & trade-offs
- + Asymmetric authority: the worst a misbehaving LLM can do is be over-cautious.
- − Some legitimate improvements may be marked inconclusive; the report shows the auditor's reasoning so users can judge.

## Consequences
`verification_results.auditor_downgraded` is tracked; eval suite measures downgrade rate on fixtures where the right answer is `verified`.
