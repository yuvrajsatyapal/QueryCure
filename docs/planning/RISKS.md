# Risk Register

Severity (impact) and probability: H/M/L. Review at each phase exit.

| ID | Risk | Sev | Prob | Mitigation | Fallback |
|---|---|---|---|---|---|
| R1 | **Benchmark noise on a laptop/Docker for Mac** makes most verdicts inconclusive | H | M | Interleaving, warm-up, CV gate, larger sf for clearer effects, pinned settings, one experiment per host | Run sandbox on a Linux host/VM; increase `measured_runs`; report honestly as inconclusive |
| R2 | **LLM agents produce plausible but wrong hypotheses** | H | M | Citation validator, deterministic context summaries, eval suite with ground truth, verification by experiment | Narrow prompts; more deterministic heuristics (e.g., rule-based missing-index detector feeding the agent). Overconfidence on an already-optimal query (Phase 2 baseline) is now capped by the deterministic materiality gate (ADR-0017) |
| R3 | **SQL validator bypass** | H | L | Defense in depth (read-only txn, timeouts, role checks), fail-closed parser, security tests with evasion payloads | Mode B restricted further (catalog-only, no user query EXPLAIN) |
| R4 | **SSRF via connection targets** on public deployment | H | M | SSRF guard with hostaddr pinning; Mode B disabled publicly by default | Keep Mode B local-only permanently |
| R5 | **LangGraph / LangChain API churn** | M | H | Pin versions; isolate graph assembly and LLM layer; integration tests on upgrade | Vendor-neutral fallback: own small orchestrator for the fixed topology |
| R6 | **Scope creep** (too many features, never shipping) | H | H | Phase exit criteria; FEATURES tiers; Post-MVP list; "smallest verifiable change" rule | Cut Phase 5 items to MVP-marked only |
| R7 | **Free-tier changes / cost** for hosting, Neon, LLMs | M | M | BYOK; small footprint; Postgres-only infra | Static demo (report replays only) on Vercel |
| R8 | **Sandbox data unrepresentative** → verified in sandbox, useless in production | M | H | Clear labeling; param sets incl. edge cases; workload descriptions; recommendations framed "within tested scope" | Future: user-data subset sandbox (F-50) with anonymization |
| R9 | **Prompt injection via schema/workload text** steering recommendations | M | M | Fencing, sanitization, capability limits, deterministic verdicts, approval shows exact SQL | Disable Workload Investigator on untrusted `pg_stat_statements` text |
| R10 | **Postgres job queue edge cases** (stuck leases, duplicate resumes) | M | M | Leases + heartbeat, dedupe keys, idempotent nodes, tests | Replace with arq/Dramatiq via new ADR |
| R11 | **Correctness check false positives/negatives** (ties, floats, collations) | M | M | Canonicalization rules, tie detection → inconclusive, tests per type | Mark rewrite candidates as "unverified" only, never verified |
| R12 | **LLM cost per investigation** too high for users | M | M | Budgets, deterministic context compression, cheaper models for analysts | Offer "fast" profile with fewer agents |
| R13 | **Secrets leak** through logs/checkpoints | H | L | Redaction processor, SecretStr, references-only state, tests scanning logs/checkpoints | Rotate master key; incident note |
| R14 | **Documentation drift** as implementation proceeds | M | H | CLAUDE/AGENTS rules require doc updates; phase reports; FILE_MAP status markers | Doc review task at each phase exit |
| R16 | **Free-model capacity and reliability** (owner policy: free OpenRouter models only, ADR-0016): ~50 requests/day, slow calls, upstream 429s, routers that switch models, weaker calibration | H | H | Pinned `:free` model chosen by benchmark; served model recorded per call; free-tier limits, bounded retries, 120 s timeout; graceful stop on quota; recorded evals in CI | Keep eval recording frugal (ledger); deterministic checks where models are weak (materiality gate, ADR-0017, done 2026-10-12); re-benchmark when the catalogue changes |
| R15 | **Learning bottleneck** — code written by agents isn't understood by the author | H | M | LEARNING.md per phase, phase reports with "what to study", interview questions | Slow down: implement critical modules by hand (validator, stats, queue) |
