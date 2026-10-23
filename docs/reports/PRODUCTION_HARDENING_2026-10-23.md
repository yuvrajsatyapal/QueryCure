# Production hardening for a restricted hosted trial (2026-10-23)

Code-only hardening at `252d630`, plus the deployment plan in [DEPLOYMENT §3a](../architecture/DEPLOYMENT.md#3a-restricted-hosted-trial-recommended-architecture-2026-10-23-not-deployed). **Nothing was deployed**, no hosted resource was created or changed, no credential was rotated or printed, no paid model call was made, and no test connected to Neon. One read-only command did reach Neon by mistake (§7).

No backend contract change, no migration, no change to benchmarking, verdicts, `claims@1`/`claims@2`, report builders or replay.

## 1. Plan (written before the changes)

1. Re-verify each finding in [PRODUCTION_READINESS_AUDIT](PRODUCTION_READINESS_AUDIT_2026-10-23.md) against the code at `252d630`.
2. **H1/F1 (SSE 500):** find the root cause by reading the code and reproducing it locally, then add a regression test that fails first, then fix it. Also check how the browser recovers.
3. **M3 (web config):** fail the production build without a valid API origin, and keep development unchanged. Backend: validate hosted-profile settings at startup (CORS, public URLs, cookie domain, metrics token, required URLs).
4. **H2 (observability):** add the signals that no table records (API errors, SSE outcomes), make sure logs cannot carry parameters or keys, and document alert rules for a low-cost host.
5. Security review: re-run the security suite and the dependency audits, and correct the docs where they are wrong.
6. Deployment architecture, costs, environment variables, deployment order, rollback and restricted access, all in DEPLOYMENT §3a.
7. Full verification: lint, types, unit, integration + security against local Docker, recorded evals, e2e (3 runs), production builds, audits, and the local demo-profile stack with `demo_probe`.

## 2. Previous findings, re-verified

| # | Previous finding | Status at `252d630` | Outcome |
|---|---|---|---|
| B1 | No host, domain or deploy workflow | Still true | Architecture and steps in DEPLOYMENT §3a; still an owner decision |
| B2 | Real OAuth never run on a deployed origin | Still true | Unchanged: needs a deployed origin |
| H1 / F1 | Intermittent SSE pool-checkout 500, root cause unknown | **Root cause found and reproduced** (§3) | **Fixed**, with regression tests |
| H2 | Metrics exist, no scraping or alerting | Still true; API errors and SSE failures were not measured at all | Per-process counters added; alert rules documented (OBSERVABILITY §8). Still needs a scraper at deploy time |
| M1 | Master key cannot be rotated (no re-encrypt job) | Still true; SECURITY §7 already says so | Unchanged by design (needs approval). Note added: never change `QC_MASTER_KEY_VERSION` alone |
| M2 | No hosted restore check | Still true | Unchanged (owner, Neon console) |
| M3 | `localhost` fallback for `NEXT_PUBLIC_API_BASE_URL` | Still true in `client.ts` and `next.config.ts` | **Fixed:** the production build fails |
| M4 | CSP `'unsafe-inline'`, no web HSTS | Both still true | **HSTS added** to the web app. `'unsafe-inline'` remains (nonce CSP is a separate change) |
| M5 | Stale `env.bak` outside the repo | Not verifiable from here | Owner action |
| L1 | Dev-only `braces` advisory | Unchanged: runtime 0 in both ecosystems | Track |
| L2 | No per-user SSE cap | Unchanged; `qc_sse_streams_active` now shows the count | Track |
| L3 | `report-builder@2` | Unchanged | Separate change |

**New findings in this session**

| # | Severity | Finding | Status |
|---|---|---|---|
| N1 | Medium | SQLAlchemy put bound parameter values into `str(exc)`, and `unhandled_error` logs the traceback, so user SQL, ciphertext or token hashes could reach logs | **Fixed:** `hide_parameters=True`. Residual: PostgreSQL's own message can quote an input value |
| N2 | Low | Groq keys (`gsk_…`) were not masked inside log values | **Fixed** |
| N3 | Medium | After an HTTP error on a reconnect, `EventSource` closes for good, so a single 5xx/503 left the page silently not live | **Fixed:** bounded manual reconnect |
| N4 | Medium | Hosted settings accepted `CORS_ORIGINS=["*"]` or plain-http origins with credentials, and the API started without `DATABASE_URL` or CORS | **Fixed:** refused at startup |
| N5 | High (cost) | The always-on worker keeps the Neon compute awake (heartbeat every 20 s), so the free plan's compute allowance is likely exceeded. Inferred, not measured | Documented in DEPLOYMENT §3a; owner must check the plan |
| N6 | High (access) | The demo profile allows anonymous sessions, so a "restricted" trial is open to anyone with the URL | Documented; the sign-in allowlist needs approval (§6) |
| N7 | Low | Docs were wrong: SECURITY §9 claimed a nonce CSP and Dependabot; neither exists | Corrected |

## 3. F1 root cause (SSE 500), with evidence

**Symptom (2026-10-18):** in 1 of 3 e2e runs an SSE request logged a server exception at pool checkout: `can't change 'autocommit' now: connection in transaction status ACTIVE`.

**Mechanism, traced through the installed sources:**
1. Starlette cancels a streaming response with an anyio cancel scope when the client disconnects. That cancellation is level-triggered: every later `await` in the cleanup is cancelled too.
2. If the disconnect lands while SQLAlchemy runs its **pool pre-ping** on a reused connection (`_psycopg_common.do_ping`: set `autocommit=True`, run `SELECT 1`), psycopg's `AsyncConnection.wait` catches the `CancelledError` and tries to cancel the query on the server (`await self._try_cancel()`). That `await` is cancelled immediately as well, so the connection stays `ACTIVE`.
3. The `finally` block in `do_ping` then restores `autocommit`. On an `ACTIVE` connection that raises `ProgrammingError`, which **replaces** the `CancelledError`.
4. The pool invalidates the connection, so it is not reused and the pool stays healthy. The `ProgrammingError`, though, escapes the stream generator and is logged as an unhandled error.

The 2026-10-18 hypothesis, a connection returned to the pool with a statement in flight, was wrong: the statement in flight was the pre-ping's own `SELECT 1`. That is also why the earlier disconnect test (cancel during a normal query) passed.

**Reproduction:** `test_a_disconnect_during_the_pre_ping_closes_the_stream_cleanly` stretches the pre-ping to `pg_sleep(0.5)` and disconnects after 0.1 s. Before the fix it fails with exactly the production message; after the fix it passes. Without `api/sse.py`'s change it fails again (checked with the change stashed), and it passed 8 of 8 repeated runs.

**Fix:** each database round trip of a stream runs under `anyio.CancelScope(shield=True)` (`api/sse.py::_read`). The read is bounded by the pool timeout and the server-side statement timeout, and the cancellation is delivered at the next `await`, after the connection is back in the pool. `anyio` is declared as a direct dependency; it was already locked as Starlette's.

**Also changed:**
- A server-side error after the stream has started is logged as `sse_stream_failed` and counted, and the stream ends, so the browser resumes with `Last-Event-ID`. Before, it surfaced as an uncaught ASGI exception.
- On the client, `useRunEvents` reconnects itself after an HTTP error with `after_seq` (backoff 1, 2, 4, 8, 16, 30 s; at most 6 attempts, reset on every successful open). It stops after a terminal event and on unmount.

**Not proven:** that the 2026-10-18 occurrence went through exactly this path. No log of it was kept, so this is the mechanism that reproduces the identical message, not a replay of that run. Three e2e runs after the fix logged zero server errors.

## 4. Changes

| Area | Change | Files |
|---|---|---|
| SSE (server) | Shielded DB reads; stream outcomes counted; failures logged and ended cleanly | `backend/src/querycure/api/sse.py`, `api/routers/runs.py` |
| SSE (client) | Bounded reconnect after HTTP errors, resuming with `after_seq` | `frontend/src/lib/events/useRunEvents.ts`, `lib/events/runEvents.ts` |
| Web config | `resolveApiOrigin`: the production build fails without a valid origin (https, or http on loopback); `next typegen` exempt; dev keeps `http://localhost:8000`; HSTS header | `frontend/src/lib/api/origin.ts`, `next.config.ts`, `lib/api/client.ts` |
| Backend config | Hosted-profile validation (CORS, public URLs, cookie domain, metrics token ≥ 32, web origin in CORS); the API refuses to start without `DATABASE_URL` / `CORS_ORIGINS` | `backend/src/querycure/core/config.py`, `api/main.py` |
| Observability | `qc_http_responses_total{status_class}`, `qc_http_unhandled_errors_total`, `qc_sse_streams_active`, `qc_sse_streams_closed_total{outcome}`, `qc_process_uptime_seconds` | `api/process_metrics.py`, `api/middleware.py`, `api/routers/metrics.py` |
| Log safety | `hide_parameters=True` on metadata engines; Groq key pattern | `db/engine.py`, `core/redaction.py` |
| CI | Build step sets the placeholder API origin (`https://api.example.invalid`) | `.github/workflows/ci.yml` |
| Docs | DEPLOYMENT §3a and §6, OBSERVABILITY §0 and §8, SECURITY §5c, §7 and §9, CODING_STANDARDS, CLAUDE.md §7 build command | — |

**Tests added:** `test_sse_disconnect.py` (+3), `test_engine_hides_parameters.py` (1), `test_deployment_config.py` (18), `test_process_metrics.py` (3), `test_logging.py` (+1 case), `origin.test.ts` (4), `useRunEvents.test.tsx` (3), `runEvents.test.ts` (+2). **Tests changed:** `test_operations.py` (32-character metrics token), `test_workloads_api.py` (demo app now gets the settings it needs to start).

## 5. Verification (this session, local Docker only)

| Check | Command | Result |
|---|---|---|
| Lint / format / types | `ruff check .`, `ruff format --check .`, `mypy src` | clean, 216 source files |
| Backend unit | `pytest tests/unit -q` | **1005 passed**, 2 skipped, 1 xfailed (known, ADR-0021) |
| Integration + security | `QC_REQUIRE_DB=1 pytest tests/integration tests/security` | first run 625 passed, 1 failed (the new startup guard refused a demo app built without a database URL; the test now passes the settings a deployment must have). Re-run: **626 passed** |
| Recorded evals | `python -m querycure.evals run --suite smoke …` (local admin URL) | **5/5**; no quota ledger written, so 0 real model requests |
| Frontend | `pnpm lint`, `typecheck`, `test`, `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 pnpm build` | clean; **239 passed**; build OK (Next 16.4.2) |
| Build guard | `pnpm build` without the variable / with `http://api.example.dev` | exit 1 with the named error / exit 1 "must use https" |
| Runtime headers | `next start` without the variable after an https build | CSP names the build-time origin; HSTS present |
| E2E | `playwright test` (stub LLM; compose worker stopped) | **18/18 on 3 consecutive runs**; API stdout piped for these runs only: 0 `unhandled_error`, 0 `sse_stream_failed`, 0 tracebacks, 0 5xx |
| Audits | `pip-audit` on the locked runtime set; `pnpm audit --prod --audit-level high`; full `pnpm audit` | 0; 0; 1 high (dev-only `braces`, L1) |
| Demo stack | `compose.demo.yaml` + `demo_probe` | See §5a |
| Python 3.13 | — | Not run locally; CI runs it |
| GitHub CI | `ci.yml`, `audit.yml` on the pushed commit | See §9 |

### 5a. Demo-profile stack

`infra/docker/compose.demo.yaml` rebuilt from this checkout (random local `QC_MASTER_KEY`, local Postgres only), then:
- `/readyz` → `{"status":"ok","database":"ok","migrations":"current"}`, so the new startup validation accepts the stack's loopback CORS origin;
- `python -m querycure.ops.demo_probe --base-url http://127.0.0.1:8300 --web-origin http://localhost:3300` → **17/17**;
- the web container sends the CSP and `Strict-Transport-Security: max-age=63072000; includeSubDomains`;
- `docker build` of `frontend/` **without** the build argument stops at `pnpm build` with exit 1 (run with `-q`, so the message itself was not captured; the same guard's message is shown by the local build above).

The stack was stopped afterwards.

## 6. Remaining blockers, ranked

| Rank | Severity | Blocker | Owner of the next step |
|---|---|---|---|
| 1 | Blocker | No host, domain or accounts (B1) | Owner |
| 2 | Blocker | Real OAuth not verified on a deployed origin (B2) | Owner, after deploy |
| 3 | High | **Access is not restricted** (N6): anonymous sessions are on. Option B (sign-in allowlist) is a backend contract change and needs approval | Owner decision |
| 4 | High | **Neon compute allowance** with an always-on worker (N5) | Owner: check the plan; budget |
| 5 | High | No alerting wired (H2): rules documented, nothing scrapes yet | At deploy time |
| 6 | High | `TRUSTED_PROXY_HOPS` must match the host. A wrong value makes rate limits global or spoofable | At deploy time |
| 7 | Medium | No hosted restore check; PITR window unconfirmed (M2) | Owner |
| 8 | Medium | Master key rotation impossible without user re-entry (M1); needs a re-encrypt CLI | Separate approved change |
| 9 | Medium | CSP `'unsafe-inline'` for scripts (M4) | Separate change |
| 10 | Medium | Stale `env.bak` (M5) | Owner |
| 11 | Medium | `backend/.env` sets `DATABASE_MIGRATION_URL` twice, and the Neon owner URL wins (§7) | Owner: keep one value, preferably local |
| 12 | Low | Dev-only `braces`; no per-user SSE cap; `report-builder@2` (L1–L3) | Track |

**Remaining high-severity security risks:** N6 (open access) and the proxy-hop setting (rank 6). No high-severity code vulnerability is known: the runtime dependency audits are clean and the security suite passes.

## 7. Disclosure: one read-only command reached Neon

While checking the local migration state I ran `uv run alembic current` in `backend/`. `backend/.env` defines `DATABASE_MIGRATION_URL` twice, and the second definition (Neon, `neondb_owner`) is the one in effect. The command therefore connected to **Neon as the owner role** and read `alembic_version` (result `0016 (head)`). It writes nothing. No test ran against Neon, and the local state was then re-checked with an explicit local URL (`0016 (head)`). The duplicate in `.env` is a trap for any Alembic command and should be resolved (rank 11).

## 8. Updated production-readiness checklist

- [x] F1 root cause found, reproduced and fixed, with regression tests.
- [x] Production web build fails without a valid API origin; no localhost fallback in production.
- [x] Hosted backend settings validated at startup.
- [x] Logs: no bound parameters, Groq keys masked.
- [x] API error and SSE outcome metrics; alert rules written.
- [x] Local suites, e2e ×3, evals, audits green (§5).
- [ ] CI green on the release commit (§9).
- [ ] Owner: domain and accounts; `env.bak` deleted; `.env` duplicate resolved; PITR window and Neon compute allowance checked.
- [ ] Owner: access strategy chosen (allowlist approval, or accept "open to anyone with the link").
- [ ] Deploy in the order of DEPLOYMENT §3a: API → verify → DNS → web → OAuth → probe → monitoring.
- [ ] `TRUSTED_PROXY_HOPS` confirmed for the host.
- [ ] Uptime monitor, metrics scrape with rules, log alerts; one test alert received.
- [ ] OAuth checklist passed for both providers; `demo_probe` passes on the deployed origins.

**Verdict:** the code is ready for a restricted hosted trial. The trial is not "restricted" until access control exists (N6), and it should open only after the steps above, in order. Nothing has been deployed.

## 9. Commits and CI

PENDING_CI

## 10. What to study

- Level-triggered (anyio) vs edge-triggered (asyncio) cancellation, and why cleanup code in a cancelled scope must shield the awaits it needs.
- How SQLAlchemy's pool pre-ping and reset-on-return interact with cancellation (`pool/base.py::_finalize_fairy`, `_ConnectionFairy._checkout`).
- `EventSource` semantics: automatic reconnects happen only on network errors, not on HTTP error responses.
- Why `NEXT_PUBLIC_*` variables are build-time and why validation belongs in the build phase, not in `next start`.
