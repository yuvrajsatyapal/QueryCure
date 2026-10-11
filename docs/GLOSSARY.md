# Glossary

Canonical terms. Use these exact names in code, docs, UI, and API fields.

| Term | Definition | Code name |
|---|---|---|
| Investigation | A user-owned unit of work: one objective + inputs (query, plan, connection). Persists across runs. | `Investigation` |
| Run | One execution of the agent graph for an investigation (initial, resume-after-approval is the *same* run; re-investigation is a *new* run). | `InvestigationRun` |
| Execution mode | A = offline analysis, B = restricted live inspection, C = isolated benchmarking. A run may combine B+C. | `ExecutionMode.OFFLINE / LIVE_INSPECTION / SANDBOX_BENCHMARK` |
| Metadata DB | QueryCure's own PostgreSQL database. | `metadata_db` |
| Target DB | A user's database reached in Mode B. Never written to. | `target_db` |
| Sandbox DB | Disposable PostgreSQL database used in Mode C. | `sandbox_db` |
| Workload | A dataset + schema + query set used for benchmarks. Demo workloads are generated deterministically from a seed. | `Workload` |
| Artifact | Immutable, SHA-256-addressed content (query text, schema snapshot, plan JSON, config, report). | `Artifact` |
| Evidence | A typed, citable fact derived from an artifact or measurement (e.g. "plan node 3 is a Seq Scan on orders, 4.9M rows est."). | `Evidence` |
| Finding | An agent's structured observation that cites evidence. | `Finding` |
| Hypothesis | A suspected root cause with supporting/contradicting evidence, confidence, and a verification method. | `Hypothesis` |
| Candidate | A proposed optimization (index, rewrite, statistics change). | `OptimizationCandidate` |
| Experiment | A benchmark definition comparing baseline vs one or more candidates. | `Experiment` |
| Benchmark run | Measurements for one *arm* (baseline or candidate) × one parameter set. | `BenchmarkRun` |
| Tournament | An experiment with ≥2 candidates competing under identical conditions. | `Tournament` (an `Experiment` with `kind=tournament`) |
| Verdict | `verified`, `rejected`, or `inconclusive`, produced by deterministic audit rules and annotated by the Benchmark Auditor. | `VerificationResult.verdict` |
| Claim status | UI label: Observed, Hypothesis, Recommendation, Verified, Rejected, Inconclusive. | `ClaimStatus` |
| Outcome | Final run result: `verified_recommendation`, `unverified_recommendations`, `no_action_needed`, `inconclusive`. | `RunOutcome` |
| Approval request | A human gate before risky operations (sandbox DDL, live `EXPLAIN` on a production-flagged connection, budget extension). | `ApprovalRequest` |
| Provenance | Where a number came from: `measured`, `prerecorded`, `imported`. | `provenance` |
| Canonicalization profile | Frozen rule set producing canonical bytes for hashing (`qc-json-v1`, `qc-text-v1`, `qc-raw-v1`, `qc-events-v1`, `qc-row-v1`). | `artifacts.canonicalization` |
| Digest | `SHA-256(profile ‖ LF ‖ canonical bytes)`, written `sha256:<hex>`. Proves consistency with a stored reference, not authenticity. | `sha256` |
| Finalization | The single transaction that seals a run: event cutoff, events digest, report, manifest, terminal status. | `finalize_run` |
| Events cutoff | Last event `seq` covered by the events digest; later events are lifecycle-only. | `events_cutoff_seq` |
| Report replay | Verify a finalized run's stored evidence against its manifest and redisplay it; zero LLM calls. | `replay_attempts.kind=report` |
| Experiment replay | Re-execute a stored experiment config (same seed) in a fresh sandbox; produces *new* measurements, compared statistically. | `replay_attempts.kind=experiment` |
| Replay attempt | One replay request with its own status and failure code. | `ReplayAttempt` |
| Speedup drift | `S_replay / S_original`; its bootstrap CI vs the equivalence margin decides `reproduced`. | `D` |
| AI re-investigation | New LLM-driven run on the same inputs, diffed against the original (Post-MVP). | `investigation_runs.kind=reinvestigation` |
| Budget | Hard limits on LLM calls, tokens, tool calls, wall-clock, benchmark time, retries. | `RunBudget` |
