# Phase 3 Report — Optimization & benchmarking

- **Dates:** 2026-10-12 → 2026-10-12 (UTC)
- **Exit criteria met:** **partially.** Acceptance #1, #3, #4 and #5 are met, verified against real PostgreSQL 17. Acceptance #2 ends with the outcome the roadmap allows: a documented `inconclusive` on noisy hardware, with measured evidence of why (§5, §6). The exit artifact, prerecorded demo fixtures, is committed. The Optimization Engineer's real-model eval recordings are pending (free-quota policy, §10). Two Phase 2 smoke recordings are also still pending and are tracked separately.
- **Tasks completed:** T3.1–T3.8, T3.10–T3.13 ([TASKS.md](../TASKS.md)). T3.9 is implemented and tested with scripted and stub models; its eval cases exist but have no recordings yet.
- **Tasks deferred:** `explain_in_sandbox` tool for the Optimization Engineer (it would need a clone before approval; the engineer is a single structured call checked deterministically instead) → Phase 4 if evals show a need. User-provisioned sandbox connections (D4) → later. The Benchmark Auditor is Phase 4 by plan.

## 1. What was implemented

**For the user.** Pick a demo workload in the Workspace ("Demo workload" tab: workload, scale factor, example query and its parameter sets) and start an investigation. The agents diagnose the query against a plain EXPLAIN taken from a throwaway sandbox clone. The Optimization Engineer then proposes candidate changes, and the run stops at **Approve sandbox experiment**: a card showing the exact SQL of every candidate, with approve all, approve selected, or decline. Nothing runs before a decision. After approval, every candidate is benchmarked in one **tournament** against a shared baseline, in disposable clones. The **Tournament** tab then shows the ranked verdicts in words (verified within the tested scope, rejected with a reason, inconclusive with a reason), a per-parameter-set comparison (median, p95 or "n/a (n<20)", n, speedup with a 95% CI on a log-scale bar), and the environment the numbers come from. A rejected or inconclusive round feeds its reasons back to the engineer for a bounded number of extra rounds.

**Technical summary.**
- **Sandbox provisioner** (`sandbox/provisioner.py`): workload templates built once as `qc_bench` (autovacuum off, `VACUUM (FREEZE)`, no ANALYZE) with a data digest that is stable across rebuilds. `FILE_COPY` clones per arm. Session advisory-lock leases that can be cancelled. Orphan cleanup on every lease and at worker start. Clone cap.
- **Benchmark engine** (`benchmark/`, `bench@1`, pure deterministic Python, no `llm`/`agents` imports):
  - seeded interleaved schedule;
  - timing of execute + streamed fetch in a READ ONLY transaction (BEGIN outside the timer);
  - frozen `qc-row-v1` row hashing with golden vectors;
  - multiset and ordered fingerprints, with conservative ORDER BY totality, tie awareness, error parity and arm stability;
  - median ratio with a seeded 2,000-resample bootstrap CI;
  - verdict gates; tournament ranking with a 5% tie band;
  - block-level resume; cancellation between blocks plus in-flight `pg_cancel` from a watcher thread.
- **Safety gates in the engine itself:** every arm is re-validated against the DDL allowlist, and its SQL digest must match the approved one before any clone exists.
- **DDL allowlist** (`sql/ddl_allowlist.py`): a strict, fail-closed parser for `CREATE INDEX` / `CREATE STATISTICS` / `ANALYZE` on tables the query reads.
- **Agents:** sandbox context through the hardened inspection gateway, `optimization_engineer`, `approval_gate` (LangGraph `interrupt`), `run_experiment` (sync engine in a thread, bridged to the DB), `next_round`, and new outcomes plus `interim-report@3` in `write_report`.
- **API:** sandbox investigations, candidates, approvals, decision, experiments.
- **Worker:** approval-expiry sweep, sandbox orphan cleanup, opt-in container on `sandbox_net`.
- **Demo workloads:** `join_fanout`, `stale_stats`, `index_regression`.
- **Prerecorded fixtures:** with provenance enforced on import.

## 2. Important architecture decisions

| Decision | ADR / doc updated | Why |
|---|---|---|
| Sample-quality gate uses robust CV = IQR/(1.349·median), and a decisive regression is checked before it | [ADR-0018](../../engineering/adr/ADR-0018-robust-sample-quality-gate.md) (pending owner review), BENCHMARK_ENGINE §6–§7 | Classic CV was driven by single spikes (0.30–0.76 on clear 6× wins). Gate order hid a 5.5× slowdown behind noise on another param set. Noise only widens a CI, so decisive harm is real |
| Stream the result in one round trip (chunked rows) instead of server-side cursor DECLARE/FETCH | BENCHMARK_ENGINE §4 | Same bounded memory. Halved the per-sample harness floor on the Docker relay (≈1.1 → 0.55 ms) |
| Two sandbox roles: admin (provisioner only) and `qc_bench` (owns objects, runs all candidate SQL) | BENCHMARK_ENGINE §3, SECURITY §8 | Candidate SQL never runs as a superuser; security tests prove `qc_bench` cannot reach programs, server files, roles or new databases |
| Loopback socat relay for host access; worker container on `sandbox_net` as an option | compose, DEPLOYMENT §2 | `internal` networks cannot publish ports. The relay keeps the sandbox egress-free. The container removes the host↔VM hop (40 µs vs 355–451 µs round trip) |
| Approval wait excluded from the wall-clock budget (`waiting_seconds`) | migration 0009, AGENT_SYSTEM §11 | Otherwise every approved run would resume already out of budget |
| `benchmark_runs.phase` (`build`/`measure`/`plan`) in the resume key | DATABASE_DESIGN | Build costs and post-timing plan captures share the append-only, idempotent row store |
| Content writers lock the run row `FOR NO KEY UPDATE`, not `FOR SHARE` | AGENT_SYSTEM §3 | Fixed a lock-upgrade deadlock between parallel analysts (§9) |
| Optimization Engineer is one structured call plus deterministic judging, with no tools | AGENT_SYSTEM §2 | Free-quota policy (ADR-0016): candidate validity is computable, so code decides it, with one retry when more than half are invalid |
| `interim-report@3` adds the optimization rounds; runs without them still build byte-identical `@2` | REPLAY_ENGINE §7 / ADR-0015 | Released builders are frozen |

## 3. Files changed

| Area | Files / modules | Notes |
|---|---|---|
| Migrations | `0008_optimization_benchmarking`, `0009_approval_wait_and_preauthorization` | 4 tables, append-only `benchmark_runs` grants, `experiment_result` artifact kind, `waiting_seconds`, `pre_authorize_sandbox` |
| Benchmark | `benchmark/{stats,schedule,correctness,rules,tournament,executor,engine,fixtures}.py`, `domain/benchmark.py`, `replay/canonical/row_v1.py` | Engine `bench@1`, profile `qc-row-v1` (frozen) |
| Sandbox | `sandbox/provisioner.py`, `infra/docker/compose.yaml`, `backend/Dockerfile` | relay, pinned settings, opt-in worker container |
| SQL | `sql/ddl_allowlist.py` | candidate policy |
| Agents | `agents/{candidates,graph,run,runtime,services,state}.py`, `agents/nodes/{optimization_engineer,approval_gate,run_experiment,optimization_loop,collect_context,intake,write_report}.py`, `agents/prompts/optimization_engineer.py` | prompt `optimization_engineer@1` |
| Persistence / jobs | `db/repositories/optimization.py`, `jobs/approvals.py`, `jobs/handlers.py`, `worker/__main__.py`, `evidence/store.py` | decision/expiry, deadlock fix |
| API | `api/routers/{optimization,investigations}.py`, `api/schemas/optimization.py` | 5 new endpoints |
| Reports / evals | `reports/{interim,optimization}.py`, `evals/{cases,scoring,runner}.py`, 2 new cases, `evals/fixtures/experiments/*.json` | Mode C cases unrecorded |
| Frontend | `components/tournament/*`, `InvestigationView`, `StartInvestigation`, `Workspace`, `Timeline`, `useRunEvents`, `lib/api/optimization.ts`, `e2e/sandbox-approval.spec.ts` | |
| CI | `.github/workflows/ci.yml` | sandbox service for integration and e2e |

## 4. Tests executed

All real output, 2026-10-12, Apple M2 / Docker Desktop, PostgreSQL 17.11, Python 3.12, Node 22.

| Suite | Command | Result | Notes |
|---|---|---|---|
| Lint / types | `uv run ruff check . && uv run ruff format --check . && uv run mypy` | clean, 162 files | `--strict` |
| Unit | `uv run pytest tests/unit -q` | **595 passed** | stats (incl. CI coverage property), schedule, `qc-row-v1` golden vectors, correctness, gates, tournament, allowlist, candidate judge, fixtures, eval scoring |
| Integration | `QC_REQUIRE_DB=1 uv run pytest tests/integration -q` | **325 passed** | grants, provisioner, engine, eval table, Mode C graph, approvals API, deadlock regression |
| Security | `QC_REQUIRE_DB=1 uv run pytest tests/security -q` | **123 passed** | +14 sandbox isolation (`qc_bench` escape attempts) |
| Full backend | `QC_REQUIRE_DB=1 uv run pytest -q` | **1043 passed** | was 804 at the end of Phase 2 |
| Evals (replay) | `uv run python -m querycure.evals run --suite smoke` | 3 PASS, 2 not recorded (exit 1) | unchanged from Phase 2; Mode C cases are in `full` and unrecorded |
| Frontend | `pnpm lint && pnpm typecheck && pnpm test && pnpm build` | clean; **65 passed**; build OK | +6 tests |
| E2E | `pnpm exec playwright test` | **2 passed** (4 consecutive green paired runs after one failure, see §9) | new: sandbox approval flow through API, worker, metadata DB and sandbox with the stub LLM |
| CI | GitHub Actions on `fc72846`, `53fa425`, `510f766` | green | includes integration and e2e with the sandbox service |

**Benchmark evidence** (assertions are on verdicts, never latencies):
- **Eval table (TESTING_STRATEGY §6), sf=0.1, spec thresholds:** 9/9 tests pass, stable across 4 consecutive runs. Negative cases are strict:
  - `index_regression` → `rejected: regression` (open 4.6× faster, escalated 5.5× slower);
  - `rewrite_trap` NOT EXISTS → `rejected: result_mismatch`;
  - `no_benefit` → never verified;
  - injected-noise case → `inconclusive: insufficient_evidence` from gate 4.
- **Positive-case verdict frequency on this host** (3 seeds each, sf=0.1): `orders_ecommerce` 1/3 verified (5.9–6.1×, CIs 4.7–7.5×); `join_fanout` 1/3 (1.5–1.6×); `stale_stats` 2/3 (3.2–3.5×). The other 5/9 were `inconclusive` from gate 4, and **0 were rejected**.
- **Acceptance #2 full run** (API → worker → sandbox, `orders_ecommerce@v1:sf=1:seed=42`, stub LLM proposed the composite index, 12 s): `hot_customer` **50.8 → 0.29 ms, 177× (95% CI 144–211×)**; `regular_customer` **49.7 → 0.18 ms, 270× (236–320×)**; results identical. Verdict `inconclusive: insufficient_evidence` (candidate robust CV 0.44). Committed as fixture `orders_ecommerce_sf1_composite_index.json`.

## 5. Acceptance criteria

| Criterion (ROADMAP Phase 3) | Status | Evidence |
|---|---|---|
| 1. Benchmark-engine eval table passes with hand-written candidates on sf=0.1–1 | **Met** (sf=0.1) | `test_benchmark_eval_table.py` 9/9; positive cases accept only gate-4 `inconclusive` (documented noisy hardware), never rejection |
| 2. Full run on `orders_ecommerce` reaches `verified` or a documented inconclusive reason | **Met as documented inconclusive** | §4: 177×/270× with matching results, stopped by the sample-quality gate on a 0.2–0.3 ms arm; root cause measured (§6); policy decision D11 open |
| 3. `rewrite_trap` rewrite is `rejected: result_mismatch` | **Met** | eval table; `test_semantics_changing_rewrite_is_rejected_and_the_loop_is_bounded` (graph); fixture `rewrite_trap_sf01.json` |
| 4. Cancelling during measurement stops within one block and leaves no `qc_clone_*` | **Met** | `test_cancel_stops_within_one_block_and_drops_clones`, `test_cancel_interrupts_an_in_flight_query` (< 15 s for a 60 s statement), graph-level cancel test; every engine test asserts no clones remain |
| 5. No sandbox DDL without an approved `approval_requests` row | **Met** | `test_no_sandbox_ddl_before_approval_then_approved_run_is_benchmarked` (no experiment, block or clone while pending); engine refuses unapproved arms or a changed SQL digest before provisioning (`test_unapproved_arm_executes_nothing`, `test_sql_changed_after_approval_executes_nothing`) |
| Exit: sample experiment artifacts committed as labeled prerecorded fixtures | **Met** | `backend/evals/fixtures/experiments/` (4), `load_prerecorded` refuses `measured` |

## 6. Known limitations

- **Sub-millisecond winners rarely verify on Docker Desktop.** The per-arm dispersion gate compares jitter (~0.1 ms absolute, even in-network) with a 0.2–0.9 ms median. Speedups of 6–270× with CIs far above 1.10× still end `inconclusive`. Open decision D11 (CURRENT_PHASE) proposes the fix. Until it is decided, demo outcomes for index candidates are mostly `inconclusive`, reported honestly.
- Hardware fields in the environment fingerprint describe the machine running the worker, and Docker Desktop's VM may differ. `sandbox_image_digest` is a tag (`postgres:17`) unless `SANDBOX_IMAGE_DIGEST` is set.
- Warm cache, single session, synthetic data (BENCHMARK_ENGINE §10). Write overhead is not measured (D6, Post-MVP).
- ORDER BY totality is only proved for single-table queries. Elsewhere the comparison stays conservative: equal multisets are accepted, and differing rows under LIMIT are `inconclusive`.
- `extended_statistics` candidates need an `ANALYZE`, which also refreshes ordinary statistics, so their effect is confounded. Only `stale_stats`-style ANALYZE candidates were exercised.
- Cancelling a run while it awaits approval ends it `cancelled` without a report (same as Phase 2 queued cancels); Phase 4 finalization covers it.
- The Optimization Engineer has not been run against a real model (§10).

## 7. Security considerations

- **New controls, all tested:**
  - DDL allowlist (39 unit cases incl. comments, dollar and escape strings, stacking, subqueries in predicates, denylisted functions in expressions);
  - candidate re-validation and approval-digest check inside the engine;
  - `qc_bench` least privilege (14 security tests: `COPY … PROGRAM`, server files, `CREATE DATABASE`/`ROLE`, `ALTER SYSTEM`, extensions, terminating admin sessions, `SET ROLE`);
  - READ ONLY transactions for benchmark queries;
  - per-statement and DDL timeouts;
  - approvals scoped per user (404 across users, including decisions);
  - partial approvals only for offered candidates.
- Sandbox egress was re-verified after adding the relay: TCP, DNS and metadata-db are all unreachable from `sandbox-db`. The relay container has egress but runs only `socat` to a fixed target.
- Approval payloads and events carry SQL and a human-readable sandbox label, never a DSN. Fixtures were scanned for DSNs and passwords (none).
- **Residual risks:**
  - the admin role builds templates from trusted generator code as a superuser;
  - Docker is not a VM boundary (ADR-0007);
  - the `qc_bench` password is a dev default in compose and `.env.example` (local profile only);
  - `pre_authorize_demo_sandbox` lets a run skip the human click, but only for demo workloads, and the approval row is still written.

## 8. What I should study

1. `benchmark/rules.py` + ADR-0018: gate order, and why noise can justify a rejection but not a verification.
2. `benchmark/stats.py`: percentile bootstrap of a ratio of medians, and why every random draw uses `Random.random()` (replay stability).
3. `benchmark/engine.py` + `agents/nodes/run_experiment.py`: a sync engine in a thread, `run_coroutine_threadsafe` persistence, resumable append-only blocks, the cancel watcher thread.
4. `replay/canonical/row_v1.py` + `benchmark/correctness.py`: type-tagged, length-prefixed row hashing; multiset vs ordered fingerprints; ties under LIMIT.
5. `sql/ddl_allowlist.py`: writing a fail-closed grammar instead of trusting a permissive parser (SQLGlot turned `CREATE STATISTICS` into an opaque Command).
6. `agents/nodes/approval_gate.py` + `jobs/approvals.py` + `agents/run.py`: LangGraph `interrupt`/`Command(resume=…)`, re-executed nodes, and keeping DB state as the source of truth.
7. `evidence/store.py`: lock-upgrade deadlocks (§9).
8. `sandbox/provisioner.py`: template databases, `FILE_COPY`, session advisory locks as crash-safe leases.

See [LEARNING.md](../../engineering/LEARNING.md) Phase 3.

## 9. Interview-relevant implementation details

1. **"Verified" was failing on obvious wins.** The first real run showed a 6× index win stopped by `CV > 0.25`. I measured instead of tuning: a bare `SELECT 1` through Docker Desktop's port forward already has robust CV 0.26–0.28, and one spike set classic CV to 0.76. Changes: robust CV (consistent with the median-based verdict), BEGIN outside the timer, one-round-trip streaming (floor ≈1.1 → 0.55 ms), and a worker container on the sandbox network (round trip 40 µs vs ≈400 µs). The remaining question is policy (D11), so it is escalated rather than decided by me.
2. **Gate order hid harm.** `index_regression` was 5.5× slower on one param set, but noise on the other set made it `inconclusive`. Insight: noise only widens a bootstrap CI, so a CI entirely below 0.95 is decisive evidence. Regression is now checked before dispersion, but after the n ≥ 10 floor. Asymmetric like ADR-0009.
3. **Bug: deadlock between parallel analysts.** A containerized worker failed runs with `DeadlockDetected`. Earlier, Playwright had shown one unexplained `OperationalError` that never reproduced. Root cause: `ensure_writable` took `FOR SHARE`, and the same transaction's event emit `UPDATE`d the run row, so two writers each held the share lock and both waited to upgrade. A regression test forces the interleaving with an `asyncio.Event`. The fix is to take `FOR NO KEY UPDATE` up front: the lock the UPDATE needs anyway, which still waits for `finalize_run`.
4. **Approval as a crash-safe pause.** `interrupt()` re-executes the node on resume, so the node must be idempotent. The approval row is the source of truth, and the resume value is only a signal. Approval wait time is excluded from the wall-clock budget. Expiry is a sweep that resumes the run so it ends `inconclusive`, not stuck.
5. **Defense in depth for AI-written DDL.** Allowlist at proposal time, the human sees the exact SQL plus its digest, the engine re-validates and checks the digest before any clone exists, execution happens as a non-superuser in a disposable clone with no egress, and queries run in READ ONLY transactions. Each layer has its own test.
6. **Deterministic replay of measurements.** Integer-ns samples, a SHA-256-derived per-block shuffle seed (golden test), a seeded bootstrap, and frozen `qc-row-v1` golden vectors. A resumed experiment re-derives the same schedule for its missing blocks.

## 10. Remaining work

- **Pending evaluations, tracked separately** (free OpenRouter quota, ADR-0016; no request was sent this phase):
  - Phase 2: `orders_injection_in_schema`, `orders_plain_explain` (smoke);
  - Phase 3: `orders_sandbox_composite_index`, `rewrite_trap_sandbox` (full; need `SANDBOX_ADMIN_URL`).
  - Record after 00:00 UTC on a day with free capacity, Phase 2 first.
- **Owner decisions:** review ADR-0018. **D11:** for the dispersion gate on fast arms, my recommendation is to waive gate 4b when the primary CI lower bound ≥ 2 × `min_effect` (decisive evidence, symmetric to the regression rule), or to report "verified (noisy environment)" as a distinct label. **D12:** whether the container worker becomes the default local benchmarking path.
- **New risks (RISKS.md):** R1 updated with measurements; R17 lock-ordering regressions in content writers.
- Phase 4 is not started.
