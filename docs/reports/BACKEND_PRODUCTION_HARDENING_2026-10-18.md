# Backend production hardening — 2026-10-18

Scope: reliability, correctness, security and operational readiness of the existing backend. No frontend redesign and no new infrastructure. Everything below was run in this session on a local laptop (macOS, Docker Desktop VM with 8 CPUs and 4 GB, PostgreSQL 17.11), unless marked **not tested**. No secrets appear here.

Each row in the summary tables is marked Passed, Failed, Skipped, Blocked or Not tested.

## A. Initial assessment

**Architecture (unchanged):** a modular monolith (FastAPI `api` plus a `worker` process) with a PostgreSQL job queue and a LangGraph orchestrator. Agents exchange Pydantic models. A deterministic benchmark engine (`bench@2`) runs against a disposable sandbox, and reports are content-addressed and sealed. Three databases are kept apart: metadata (local Docker or Neon), target (Mode B, read-only) and sandbox (Mode C).

**Baseline before any change**

| Check | Result |
|---|---|
| ruff, format, `mypy --strict` | Passed |
| Backend unit | 982 passed, 1 xfailed (documented ADR-0019 limitation) |
| Integration + security (local Docker) | 475 passed |
| Evals smoke (recorded) | 5/5 |
| Evals Mode C (recorded + fixtures) | **0/2**: "recording does not match the current prompts" |
| CI on `main` (GitHub) | **Red.** The integration job failed on `test_win_from_an_arm_specific_disturbance_is_not_noise_verified`, so it stopped before the Mode C step. That test had already failed in 2 of the last ~10 CI runs; the earlier report missed it. |
| OpenRouter | Free tier, 0 requests used today (Neon `agent_executions` checked read-only, plus the eval ledger) |
| Old worker | PID 83767, started 2026-10-17 against Neon. It owned nothing: 11 jobs `done`, no leases, runs or approvals |

**Confirmed issues, in dependency order**
1. Two red CI items: the flaky test above, and the stale Mode C recordings.
2. `claims@1` pooled every figure, so evidence could be borrowed across candidates, param sets and experiments.
3. Benchmark noise had no measurement behind it.
4. No worker liveness signal; no keepalive or connect timeout on metadata connections; unbounded worker teardown.
5. Blank env values became empty secrets or URLs.
6. Eval record mode overwrote recordings even when the new run failed, and an explicit `--admin-url` could point at a hosted database.

## B. Implemented fixes

| Commit | Change | Files | Why |
|---|---|---|---|
| `689610d` | Flaky noise-screen test redesigned with a quantified clean-block count | `tests/integration/test_benchmark_bench2.py` | The "useless" index is a Seq Scan on both clones (speed-up 0.997 over 400 interleaved pairs), so a pass is pure chance. 3 spared blocks gave CI 2/10 failures; 10 spared blocks of 2 bound it below 0.02%. Same design as the sibling regression test. |
| `e8857f4` | `claims@2` evidence-specific grounding ([ADR-0028](../engineering/adr/ADR-0028-evidence-specific-claim-grounding.md)) | `agents/claims_v2.py` (new); `claims.py` frozen; call sites; `benchmark_auditor.py` (`candidate_plans`, `replication_ranges`); `agent_runner.py` (checker version in `claim_check`) | §D |
| `fb87ead` | Transport floor diagnostic, relay startup warning, repeatability harness ([ADR-0029](../engineering/adr/ADR-0029-transport-floor-and-benchmark-repeatability.md)) | `benchmark/engine.py`, `executor.py`, `repeatability.py` (new), `domain/benchmark.py`, `worker/__main__.py`, generated API types | §C |
| `d49f06c` | Eval guards | `evals/preflight.py` (new), `runner.py`, `__main__.py` | A failing recording no longer replaces the working one (`--keep-failing` to force). A quiet-host pre-flight runs before any free request. `--admin-url` must be local. |
| `506e048` | Worker presence and diagnostic metrics | migration `0016_worker_heartbeats`, `worker/heartbeat.py` (new), `api/routers/metrics.py`, `ops/retention.py` | §E. Also fixed a pre-existing test-order coupling: a second `local` user was inserted in `test_baseline_migration`. |
| `faf13aa` | Bounded shutdown, dead-peer detection, blank settings | `db/engine.py`, `api/deps.py`, `agents/checkpointer.py`, `worker/__main__.py`, `core/config.py` | §E |
| `dac7067`, `90bf243` | Mode C recordings re-recorded | `evals/recordings/…`, `evals/fixtures/measurements/…` | §G |
| `8b3e7d2` | Black-box demo probe; worker duplicate-delivery and DB-loss tests | `ops/demo_probe.py` (new), `tests/integration/test_worker.py` | §E, §F |
| `7a77ac0` | Backup/DR runbook with a drill; wrong-master-key test | `DEPLOYMENT.md` §4c, `tests/unit/core/test_crypto.py` | §E |
| `14dd6a8` | Concurrent approval decisions test | `tests/integration/test_optimization_api.py` | §E |

## C. Benchmark reliability

The full method and data are in ADR-0029 and `docs/reports/data/benchmark-repeatability-2026-10-18/`. The harness is `python -m querycure.benchmark.repeatability`. Each configuration ran 20 independent sessions, each with its own experiment ID, seed and clones, on `orders_ecommerce@v1:sf=0.1:seed=42`. Every session had a real-effect arm (composite index) and a null arm (an unused index).

| | Relay (host worker) | In-network (worker container) |
|---|---|---|
| Candidate median, hot customer | 0.666 ms | 0.239 ms |
| Measured speed-up, hot / regular | 5.89× / 7.43× | 13.84× / 21.58× |
| Single experiment: real index `verified` | 8/20 (before), 9/20 (after) | 16/20 (before), 13/20 (after) |
| With replicates: real index verified or noise-warned | 18/20 | 19/20 |
| Null index | 20/20 `inconclusive` (one `rejected: no_improvement` in-network before) | 20/20 `inconclusive` |
| Median relative CI width (effect arm, hot) | 0.22 | 0.12 |
| Within-session robust CV, median / max | 0.22 / 0.84 | 0.12 / 1.33 |
| `SELECT 1` transport floor | 0.35 ms (53–127% of the fastest arm) | 0.072 ms (29–54%) |
| Runtime per session, median | 3.6 s (with replicates) | 1.2 s |

**Findings**
- **The relay distorts sub-ms measurements.** Its round trip is added to every sample, which compresses the speed-up toward 1. The "4.72×" in the 2026-10-17 report was understated for this reason. The relay also roughly halves single-experiment verification.
- **The remaining noise is host contention.** Bursts of consecutive slow blocks appear on both paths. During a failed recording, other projects on the host pushed the load average to 15–24, and the in-network floor rose from 60–70 µs to 138–470 µs.

**Techniques evaluated and rejected**
- Relay CPU cap as the cause: no cgroup throttling observed.
- GC control: no measurable effect.
- ABAB interleaving: drift is already paired by blocks.
- Subtracting the transport floor from samples: it would add variance.
- A paired dispersion gate: deferred, because it needs `bench@3` and a false-verification analysis.

**Adopted**
- **Transport floor.** Recorded beside each `bench@2` result, outside every sample, and flagged `transport_dominated`. It is omitted when absent, so stored results keep their bytes.
- **Relay startup warning.**
- **Quiet-host eval pre-flight.**

**Limitations.** I do **not** claim lower engine noise. The engine change is diagnostic, and the before/after differences are within batch-to-batch variation on a shared laptop. The floor is not yet surfaced in reports (`report-builder@2`).

## D. Claim grounding

**Architecture (`claims@2`, ADR-0028).** Each sentence is split into clauses, and each clause is resolved deterministically to its subjects:
- arms, by ID or by the action named (ANALYZE, rewrite, extended statistics, index by columns or "composite"/"single-column");
- param sets;
- the baseline or a candidate plan.

The frozen `claims@1` rules then run on a context narrowed to those subjects' measurements: their speed-ups, intervals and medians, their own replicated range and their own plan's scan types. Unattributed text falls back to the pooled `claims@1` check.

New typed claims (`TypedClaim`):
- fold/factor/"speed-up of" figures;
- percentage reductions (must equal 1 − 1/speed-up, and can never reach 100%);
- absolute savings;
- latency transitions that must come from one measurement.

New rules:
- guarantees;
- the stated status of a named subject, including "cleanly verified" against a noise warning;
- advice against a verified change;
- estimate direction and accuracy;
- "fresh" statistics.

The recommendation rule now applies per clause and only to recommendations. No LLM call was added. Requiring typed claim objects from the model was rejected: it changes every prompt, and every recording would exceed the daily quota.

**Versioning.** `claims@1` is frozen and still tested. New runs record `checker: claims@2` in `narrative_check` and, newly, in every `claim_check`. Historical outputs are untouched. `report-builder@1` does not read claim checks, so sealed reports are unaffected: 43/43 local sealed reports replay `verified`.

**Adversarial coverage** (`test_claims_v2.py`, 63 cases):
- A's speed-up cannot support B (claims@1 accepted all three examples);
- param sets cannot be mixed into one invented interval;
- an interval from another experiment cannot be borrowed;
- baseline and candidate plans are kept apart;
- an inconclusive or rejected subject cannot be called verified;
- numeric paraphrases (fold, factor, %, savings, transitions) are rejected when unsupported;
- correctly supported claims survive.

`test_claims_v2_compat.py` re-runs all 37 `claims@1` regression cases, including the real run-2 audit texts, under `claims@2`. All pass. The compat run found and fixed three `claims@2` defects before release.

**Remaining gaps.** Coverage is still pattern-based, and a mixed sentence is removed whole. `write_report` has no candidate plans, and the Optimization Engineer gets no action context; both are documented in ADR-0028.

## E. Operational readiness

**OAuth (Google, GitHub)**, code review:
- PKCE S256;
- 32-byte state compared in constant time against an HttpOnly cookie scoped to the provider path (10 min);
- same-site `return_to`;
- the provider subject (not the display name) as identity;
- session rotation on sign-in, so a pre-sign-in token is revoked;
- logout revokes server-side and needs CSRF;
- login is rate-limited; failure redirects carry a code only.

Existing `test_github_oauth.py` and `test_google_oauth.py` pass. **Not tested:** a real sign-in against Google or GitHub. It needs registered callback URLs on a deployed origin. Manual steps: register `https://<api>/api/v1/auth/{google,github}/callback`, set `PUBLIC_API_URL`, `WEB_BASE_URL` and the client ID/secret, sign in from an anonymous session that owns one investigation, and confirm that the investigation survives, the `qc_session` value changes, and `/me` shows the account.

**Worker**

| Scenario | Result |
|---|---|
| Old Neon worker | SIGTERM while idle: it stopped polling Neon but **did not exit for >10 min**. Its main thread was idle in `kevent`, with 4 ESTABLISHED Neon sockets. Ownership was re-verified (no jobs, leases, runs or approvals, no API running), then SIGKILL. Neon is left clean. **Not restarted against Neon**, because its schema is at 0015 and the new code expects 0016 (see H). |
| Root cause | Metadata connections had no `connect_timeout` and no keepalive settings (macOS default: 2 h idle before probing), and teardown awaited background work with no deadline. Fixed: libpq keepalives (30 s + 3 × 10 s) and `connect_timeout=10` on the engine, LISTEN hub and checkpointer; a 20 s bounded teardown that cancels hung sweepers; a bounded `dispose()`. |
| SIGTERM while idle (new code, local) | Exits in 0.3 s and marks the presence row stopped. Test: hung sweeper cancelled. |
| SIGTERM during work, abrupt kill, lease expiry, resume, approval interruption, model outage | Existing tests pass: drain/cancel, SIGKILL after fan-out → restart without duplicates, lost lease, expired/partial approvals, provider outage, `MODEL_UNAVAILABLE` |
| Duplicate delivery | New: 2 workers × 2 slots × 20 jobs, each runs exactly once |
| Metadata DB interruption | New: all connections terminated server-side; the loop survives and runs the next job |
| Running the new code | Each worker records `source_digest` (SHA-256 of its installed sources). Local: worker digest = checkout digest. Demo image: the digest differed from the checkout after a later edit, which is the drift it is meant to detect. |

**Configuration**
- **Blank values.** A blank `SANDBOX_ADMIN_URL=` dialled the default Unix socket. Blank optional secrets and URLs now mean unset; a blank `QC_MASTER_KEY` is still refused in demo.
- **Fail-closed validation (re-checked).** The demo profile requires a master key and refuses server model keys and private targets. Pooled and direct URLs are validated. The metrics token is HMAC-compared, and a blank token never opens the endpoint.
- **Credential exposure in this session.** While reading `backend/.env`, my redaction filter missed `DATABASE_URL_DIRECT`, and the Neon `qc_app` connection string appeared in this session's transcript. It was not written to any file or sent elsewhere. **Rotate the Neon `qc_app` password** to be safe.

**Monitoring.** `/internal/metrics` (open locally, bearer token elsewhere, 404 otherwise) now covers:

| Diagnoses | Metric |
|---|---|
| Worker unavailable | `qc_workers_alive`, `qc_worker_last_seen_seconds{worker_id,source_digest,bench_path}` |
| Model failures | `qc_llm_calls_24h{status,error_code}` |
| Quota | `qc_llm_free_requests_today`, `qc_llm_daily_request_limit` |
| Connection exhaustion | `qc_db_connections`, `qc_db_max_connections` |
| Sandbox / benchmark failures | `qc_experiments{status,error_code}` |

The existing queue, lease, unsealed-run and replay metrics remain. The OBSERVABILITY playbook was extended. Nothing new was introduced: no Prometheus, Grafana or Redis.

**Backup and DR.** See DEPLOYMENT §4c. Drill on local Docker only:
- `pg_dump -Fc` took 0.34 s and `pg_restore` into an isolated database 0.39 s (20 MB, schema 0016);
- row counts were identical and grants intact;
- 714/714 artifacts re-verified by digest, and 43/43 sealed reports replayed `verified`.

A wrong master key fails closed (new test). **Not tested:** a Neon PITR restore, and a restore at production size.

## F. Restricted demo security

**Live validation.** `docker compose -f infra/docker/compose.demo.yaml` was run locally with a throwaway master key: profile demo, sandbox and live inspection off, no private targets, no server model key, embedded worker. It was then probed black-box with `python -m querycure.ops.demo_probe`: **17/17**.

The probe covers:
- readiness;
- cookies `Secure`, `HttpOnly` and `SameSite=Lax`;
- `/me` showing profile demo with sandbox and live inspection off;
- live connection creation refused;
- sandbox investigation refused;
- an LLM run needs the visitor's own key, with no fallback;
- metrics 404 without the token;
- no `/docs`;
- another visitor sees nothing, and a foreign or unknown investigation is 404;
- CORS refuses other origins and allows the web origin with credentials;
- security headers;
- CSRF required;
- error envelopes leak no internals.

The existing automated suite also covers:
- a cross-user sweep of every route with a path parameter (approvals, experiment replay, report replay, connections and credentials: 404/403 with nothing changed);
- rate limits;
- the SSRF guard;
- an OpenAPI secret-field scan.

This is **local** validation of the demo configuration, not a hosted deployment. `openapi.json` stays public in demo (the route list, no secrets).

## G. Regression results (final state, this session)

| Suite | Command | Result |
|---|---|---|
| Lint/format/types | `uv run ruff check . && uv run ruff format --check . && uv run mypy` | Passed (216 files) |
| Backend unit (3.12) | `uv run pytest -q -m "not integration"` | Passed: 1115, skipped 2 (fixtures that are not experiments), xfailed 1 (documented) |
| Backend unit (3.13, CI matrix) | same, fresh 3.13 env | Passed: 1115 |
| Integration + security | `QC_REQUIRE_DB=1 uv run pytest -q -m integration` | Passed: 486, 0 failed |
| Evals smoke (recorded) | `python -m querycure.evals run --suite smoke` | Passed: 5/5 |
| Evals Mode C (CI step, no sandbox) | `--suite full --measurements fixture --case …` | Passed: 2/2 |
| Frontend | `pnpm lint && pnpm typecheck && pnpm test && pnpm build` | Passed: 89 tests. The build first failed on a stale `.next` cache (Turbopack font resolution); it passed after the cache was moved aside. |
| Playwright e2e | `pnpm exec playwright test` (stub LLM, local Docker) | Passed: 14/14 |
| Repeatability study | §C | 80 sessions, raw data committed |
| Demo probe | `python -m querycure.ops.demo_probe` | Passed: 17/17 |

**Real model requests today: 36 of 45.**
- Record attempt 1 of `orders_sandbox_composite_index`: 13 requests, FAIL. The host was contended (§C). The recording was restored from backup, which led to the save-policy fix.
- Record attempt 2 of `orders_sandbox_composite_index`: 11 requests, PASS.
- An interrupted attempt when the earlier session ended: 1 request.
- `rewrite_trap_sandbox`: 11 requests, PASS.

Every recording used `nvidia/nemotron-3-super-120b-a12b:free`, with explicit local admin URLs and a 15-request cap.

## H. Remaining risks

**P0:** none known that blocks a restricted local demo.

**P1**
- **Neon still runs schema 0015.** Migration 0016 (additive `worker_heartbeats`) was not applied to the hosted database without your approval. Until it is, a worker on Neon logs heartbeat warnings, and an API on Neon reports `/readyz` "behind". Apply: `uv run alembic upgrade head` with the Neon owner URL, then restart the worker.
- **Rotate the Neon `qc_app` password** (§E).
- **Real OAuth sign-in** on a deployed origin is untested (§E, manual steps).
- **Host-worker (relay) results understate speed-ups** and are flagged in results, but not in the report UI (`report-builder@2`).
- **`claims@2` is pattern-based.** Paraphrases outside its rules can pass. Verdicts stay deterministic (ADR-0009).

**P2**
- The worker exits at boot if the sandbox is unreachable (fail-fast; it relies on its restart policy).
- A noise-screen block check with few blocks is probabilistic (documented, ADR-0019).
- A Neon PITR restore and a production-size restore are untested.
- `openapi.json` is public in demo.
- The demo's no-BYOK response is a 503 `CONFIGURATION_ERROR`, where a 4xx would be clearer.
- Eval recording quality depends on host quiet. The pre-flight guards it, but a busy shared laptop can block recording for hours.

## I. Readiness assessment (evidence-based, not a score)

| Area | Assessment |
|---|---|
| Backend architecture | **Sound.** No structural change was needed; every fix fitted the existing layers. |
| AI orchestration | **Good.** Bounded retries, circuit breaker and pinned model are unchanged and tested. Two real recordings completed within 11 requests each. Free-tier quota stays the binding constraint. |
| Benchmark correctness | **Correct verdict logic, environment-sensitive magnitudes.** No false verification of the null arm in 80 sessions. Speed-up magnitudes depend heavily on the measurement path, which is now recorded and warned about but not yet shown in reports. |
| Evidence integrity | **Strengthened.** Figures are now bound to their candidate, param set, experiment and plan. Sealed replay is unchanged (43/43). Pattern coverage remains the limit. |
| Security | **Strong for the demo scope.** Fail-closed config, CSRF, rate limits, cross-user isolation and SSRF are verified black-box. Open items: OAuth on a real origin, and the credential rotation above. |
| Reliability | **Improved materially.** A real shutdown hang was found and fixed. Duplicate delivery and DB loss are now tested. Restore is proven locally. |
| Operational readiness | **Adequate for a portfolio demo.** Failures can be diagnosed from metrics without logs. Not production-grade: no alerting backend, and Neon restore is unexercised. |
| Restricted demo readiness | **Ready for a hosted trial once migration 0016 and the OAuth checks are done.** It has not been deployed. |
