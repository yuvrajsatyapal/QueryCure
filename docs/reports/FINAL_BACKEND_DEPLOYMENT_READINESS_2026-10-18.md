# Final backend deployment readiness — 2026-10-18

Scope: close the operational risks left by [BACKEND_PRODUCTION_HARDENING_2026-10-18](BACKEND_PRODUCTION_HARDENING_2026-10-18.md) and prepare a restricted hosted trial. No frontend redesign, no architecture change, no public deployment. No passwords, tokens or connection strings appear in this report or were printed while producing it. Every check that touched Neon used the app's own fixed queries, ran read-only unless it is listed as a migration, and executed no benchmark and no user SQL.

**Legend:**
- **Local**: verified on the laptop against local Docker.
- **Neon**: verified against the hosted Neon database.
- **Origin**: verified on a deployed origin.
- **Not tested**.
- **Awaiting owner**: needs your action or approval.

## 1. Credential exposure and rotation

| Item | Status | Evidence |
|---|---|---|
| Which configurations use `qc_app` | Local | Only the operator's `backend/.env`: `DATABASE_URL` (Neon pooled) and `DATABASE_URL_DIRECT` (Neon direct), with one shared password. There is no hosted deployment, no GitHub Actions secret (`gh secret list` is empty) and no Vercel project. CI uses throwaway local roles |
| Password in Git | Local | 0 hits in tracked files and in all 1,657 objects (history, reflog, unreachable). The scan compared bytes in-process and printed counts only |
| Password elsewhere on disk | Local | Two files outside the repo held it: the 2026-10-17 session transcript (the known exposure), and a scratchpad `env.bak` from an earlier session. That file is a plaintext copy of the whole `.env`, mode 0600 in an owner-only directory. No other secret reached a transcript; the sandbox passwords found there are the committed local-dev defaults |
| Rotation | Neon (by the owner) | You ran `ALTER ROLE qc_app … PASSWORD` and updated both URLs. I changed no password |
| New credential, pooled and direct | Neon | Both connect as `qc_app` in a read-only transaction, and their passwords match each other |
| Old credential rejected | Neon | Both endpoints answer "password authentication failed for user qc_app" (the old value was read in-process from `env.bak`, never printed) |
| App reconnects after rotation | Neon | The API and worker started on the new credential (§3) |
| `QC_MASTER_KEY` | Unchanged | Not touched |

**Remaining owner action:** delete the stale `env.bak`, at `/private/tmp/claude-501/-Users-yuvrajsatyapal-Desktop-Projects-QueryCure/0106880d-46d3-4689-aa4a-d084e508830a/scratchpad/env.bak`. It still holds the current owner, retention and OAuth secrets, the API keys and the master key; only `qc_app` changed. Consider whether the old session transcripts under `~/.claude/projects/` should be kept. A rotation runbook is now in DEPLOYMENT §4d.

## 2. Neon migration 0016

| Check | Status | Result |
|---|---|---|
| Migration reviewed | Local | Additive only: `CREATE TABLE worker_heartbeats`, two partial indexes, a trigger on the shared `set_updated_at()`, and grants. No DROP, ALTER, UPDATE or DELETE. `alembic history -r 0015:head` listed only `0015 → 0016`, and the file was identical to the reviewed commit |
| Pre-state | Neon | Revision `0015`, PostgreSQL 18.6. 11 jobs, all `done`; 9 runs, all `completed`; no live lease, no pending approval, no other sessions |
| Privileges | Neon | `neondb_owner` owns the schema and can create in `public`; `qc_app` and `qc_retention` exist; `uuid-ossp` and `set_updated_at()` are present |
| Applied | Neon | `uv run alembic upgrade head` with `DATABASE_MIGRATION_URL` (`neondb_owner`, direct endpoint). `alembic current` → `0016 (head)` |
| Objects | Neon | 11 columns, 4 CHECK constraints, PK, `idx_worker_heartbeats_worker_id_unique`, `idx_worker_heartbeats_last_seen_at`, trigger `worker_heartbeats_set_updated_at` |
| Grants (as each role, `has_table_privilege`) | Neon | `qc_app`: SELECT, INSERT, UPDATE; no DELETE or TRUNCATE. `qc_retention`: SELECT, DELETE only |
| Existing data | Neon | Fingerprints (count + md5 of ids/statuses/digests) of 10 tables were identical before and after, and again after the API and worker run: users 1, investigations 7, runs 9, events 372, artifacts 94, manifests 9, reports 9, jobs 11, approvals 4, sessions 2 |
| Evidence integrity | Neon | New read-only `python -m querycure.ops verify-integrity`: 94/94 artifacts re-verified by digest, 9/9 sealed reports replay `verified` |

**Rollback plan (not needed):** code on 0015 runs unchanged against 0016. If the table had to go, the owner would run `DROP TABLE worker_heartbeats`; it holds only presence rows.

## 3. Worker readiness and heartbeat

The checkout's API (`127.0.0.1:8011`) and a separate worker ran on the Neon configuration (`local` profile, rotated credential) for about 45 s. No job was pending, so nothing ran.

| Check | Status | Result |
|---|---|---|
| No older Neon worker | Local + Neon | No local `querycure` process; no `qc_app` session on Neon besides our own PgBouncer connection |
| `/healthz`, `/readyz` | Neon | 200; `{"database":"ok","migrations":"current"}` |
| Heartbeat row | Neon | `worker-c723508049d1`, bench path `docker-relay`; `last_seen_at` refreshed (0.6 s old at 21 s uptime) |
| Source digest | Local + Neon | Worker row `d50873af…786d9` = digest of this checkout |
| Metrics (bearer token) | Neon | `qc_workers_alive 1`, `qc_worker_last_seen_seconds{…source_digest="d50873af074a"…}`, `qc_runs_terminal_unsealed 0`, `qc_jobs_oldest_pending_seconds 0`, `qc_db_connections 5` / `901`. A wrong token → 404 |
| Graceful shutdown | Neon | SIGTERM: the worker exited in 1.5 s, logged `worker_stopped` and set `stopped_at`; the API exited in 0.3 s more. No processes left |
| Logs | Local | The API and worker logs contain no secret, URL password or Neon host |
| Exactly-once claim, duplicate delivery, interrupted-job resume, checkpoint survival, provider failure | Local | Integration suite (§7): `test_worker.py` (2 workers × 2 slots × 20 jobs run once each; SIGKILL after fan-out → restart without duplicates; lost lease; DB loss), resume and approval tests, `MODEL_UNAVAILABLE` |
| The same fault injection on Neon | Not tested, by design | Destructive tests stay on local Docker |

**Hosted worker:** none is running, and none was restarted. A long-running Neon worker belongs to the deployment decision (§8).

## 4. Google and GitHub OAuth

| Item | Status |
|---|---|
| Code review: PKCE S256, 32-byte state compared in constant time (HttpOnly, path-scoped cookie, 10 min), same-site `return_to`, subject-based identity, session rotation that revokes the pre-sign-in session, CSRF-protected logout with server-side revocation, rate-limited login, code-only failure redirects, `Secure`/`HttpOnly`/`SameSite=Lax` cookies outside local | Local (review) |
| Automated tests (`test_github_oauth.py`, `test_google_oauth.py`) | Local: pass in §7 |
| Real sign-in, logout and investigation preservation | **Not tested.** There is no deployed origin, no registered production callbacks and no test accounts. Checklist: [OAUTH_VERIFICATION_CHECKLIST](../engineering/OAUTH_VERIFICATION_CHECKLIST.md) |

## 5. Restricted demo security

`infra/docker/compose.demo.yaml` was rebuilt from this checkout and run locally (Local). It used its own Postgres, never reads `backend/.env`, and got a throwaway master key and metrics token generated in-shell. Configuration: `QC_PROFILE=demo`, `FEATURE_SANDBOX=false`, `FEATURE_LIVE_INSPECTION_PUBLIC=false`, `ALLOW_PRIVATE_TARGETS=false`, no server model key (BYOK only), strict CORS, embedded worker.

**`python -m querycure.ops.demo_probe`: 17/17 passed.** It checked:
- readiness;
- `Secure`/`HttpOnly`/`SameSite=Lax` session cookie;
- profile demo, with sandbox and live inspection off;
- live connection refused, and sandbox investigation refused;
- no shared model key: an LLM run needs the visitor's own key, with no fallback;
- metrics hidden without the token, and no `/docs`;
- cross-visitor isolation, and foreign or unknown investigation → 404;
- CORS refuses other origins and allows the web origin;
- security headers, and CSRF required;
- error envelopes without internals.

**Also checked:**
- `/readyz` returns `ok/current`;
- `qc_workers_alive 1` with digest `e6a64674d3e2`, equal to the checkout, and `bench_path="none"`;
- `qc_llm_free_requests_today 0`;
- a graceful `stop` logs `worker_stopped`.

The automated suites additionally cover:
- the cross-user sweep of every path-parameter route;
- rate limits;
- the SSRF guard, including private-target blocking in every non-local profile;
- an OpenAPI secret-field scan;
- the `LLM_FREE_ONLY` refusal of paid models before any request;
- approval restrictions, and SQL execution restrictions (SQLGlot + read-only DB controls).

**Not tested:** the same probe on a deployed origin. `openapi.json` stays public in demo (route list, no secrets).

## 6. Monitoring and disaster recovery

| Area | Status | Notes |
|---|---|---|
| Pooling | Neon | Pooled endpoint for requests with per-transaction timeouts; direct endpoint for LISTEN and the checkpointer (ADR-0025). The pool is 5 + 5 overflow, against a server `max_connections` of 901 |
| Worker liveness | Neon | `qc_workers_alive`, per-worker age and digest |
| Queue backlog, leases, unsealed runs | Neon | Metrics present and at 0 |
| Model failures, quota | Neon | `qc_llm_calls_24h{status,error_code}`; `qc_llm_free_requests_today 0` |
| Investigation timeouts, budgets | Local | Unchanged; covered by the suites |
| Structured logs | Local | JSON with redaction; checked on the Neon run's logs |
| Rate limiting | Local | Integration and demo probe |
| Alerting backend | **Not implemented** | Metrics are scrapeable, but nothing scrapes or alerts yet; that is a deployment decision |
| Secret management | Local | Only the operator's `.env` today; a host secret store is required at deploy (§9) |
| Backup retention | **Awaiting owner** | Neon's PITR window depends on the plan; check it in the console. No off-provider `pg_dump` has been scheduled |
| Local restore drill | Local | 2026-10-18: 714/714 artifacts and 43/43 reports (earlier session). Today `verify-integrity` on the local DB: 756/756 artifacts and 47/47 reports `verified` |
| Neon PITR restore | **Not tested** | Procedure in DEPLOYMENT §4c, on a child branch only; never against the live branch |
| Migration recovery | Local | Expand-only migrations, a transaction per migration, and a pre/post fingerprint procedure (DEPLOYMENT §4b) |

## 7. Test results (this session, local Docker; no Neon, no model calls)

| Suite | Command | Result |
|---|---|---|
| Lint / format / types | `uv run ruff check . && uv run ruff format --check . && uv run mypy` | Passed (381 files formatted; mypy `--strict` clean on 217 source files) |
| Backend unit (Python 3.12) | `uv run pytest -q -m "not integration"` | **1116 passed**, 2 skipped (fixtures that are not experiments), 1 xfailed (documented ADR-0019 limitation) |
| Integration + security | `QC_REQUIRE_DB=1 uv run pytest -q -m integration` | **490 passed, 0 failed** on the final code. Includes worker reliability (exactly-once claim, duplicate delivery, SIGKILL/resume, lost lease, DB loss), report replay, OAuth, BYOK, approvals, and 4 new tests (3 integrity, 1 SSE disconnect) |
| Security directory alone | `pytest tests/security` | 145 passed (a subset of the two rows above) |
| Evals smoke (recorded) | `python -m querycure.evals run --suite smoke --admin-url <local>` | **5/5** |
| Evals Mode C (recorded + fixtures, no sandbox) | as in CI | **2/2** |
| Real model requests | eval ledger `evals/.quota/2026-10-18.json` | **0 this session** (36, unchanged since 20:05) |
| Frontend | `pnpm lint`, `typecheck`, `test`, `build` (Node 22) | lint 0, typecheck 0, **89/89** tests, production build passed |
| Playwright e2e | `pnpm exec playwright test` (stub LLM, local Docker) | **14/14 in 3 of 3 runs**. Run 1 logged one server-side 500 (§8, F1); runs 2 and 3 logged none |
| Restricted demo probe | `python -m querycure.ops.demo_probe` | **17/17** |
| Integrity, local DB | `python -m querycure.ops verify-integrity` | 756/756 artifacts, 47/47 reports `verified` |
| Integrity, Neon (read-only) | same | 94/94 artifacts, 9/9 reports `verified` |
| CI on GitHub | `ci.yml` on the pushed commit | See §11 |

Python 3.13 (the second CI matrix leg) was not run locally; CI runs it.

**Reworked during the session:** the first full integration run failed 1 of 489 (`test_ops_integrity`). The new test assumed the whole shared session database was intact, but other tests tamper with their own runs on purpose. Assertions are now scoped to the run each test creates; the code was not changed.

## 8. Remaining blockers and owner actions

**Owner actions (blocking a hosted trial)**
1. **Choose the host and domain** (D1, D5) and provision the API + embedded-worker container, with the secrets in the host's store (§9).
2. **Register the OAuth callbacks** on the deployed origin, then run [OAUTH_VERIFICATION_CHECKLIST](../engineering/OAUTH_VERIFICATION_CHECKLIST.md) with test accounts.
3. **Delete the stale `env.bak`** (§1).
4. **Check the Neon PITR window** for your plan; optionally run the branch-based restore check (DEPLOYMENT §4c) once.

**Engineering findings**

| # | Severity | Finding | Status |
|---|---|---|---|
| F1 | P2 | **Intermittent SSE 500.** In 1 of 3 local e2e runs, an SSE stream (`api/sse.py`) failed at pool checkout: the pre-ping found a pooled connection still `ACTIVE` ("can't change 'autocommit' now"), meaning a connection went back to the pool with a statement in flight. The browser's EventSource reconnects (`retry: 3000`), and the spec passed. Hypothesis tested and **ruled out**: a client disconnect mid-query in the SSE loop (`test_sse_disconnect.py` passes). Root cause unknown. It is not caused by this session's changes (none touch the API runtime), but before this session no e2e log had been checked for server exceptions | **Open.** Needs a focused investigation before a hosted trial with real traffic, especially on the Neon pooled endpoint |
| F2 | P2 | **No alerting.** Metrics are complete, but nothing scrapes or alerts | Open: pick a scraper with the host |
| F3 | P2 | **`report-builder@2`** should surface the transport floor and claim removals (from the hardening report) | Open, unchanged |
| F4 | P3 | **No deploy workflow.** DEPLOYMENT §4 now says so; releases are manual (§4b) | Accepted until a host is chosen |

**Untested (by design or blocked):** real OAuth; the demo probe on a deployed origin; a Neon PITR restore; restore at production size; fault injection on Neon (local only by policy).

## 9. Production deployment checklist

Run in order. Each line is either done or a check to perform at deploy time.

- [x] Neon at `0016`; grants verified; data and evidence integrity verified.
- [x] `qc_app` rotated, with the old password rejected on both endpoints.
- [ ] CI green on the release commit: all four `ci.yml` jobs plus `audit.yml`.
- [ ] Host chosen (always-on container; DEPLOYMENT §3). Domain with `app.` and `api.` subdomains.
- [ ] Host secret store holds:
  - `DATABASE_URL` (Neon pooled, `qc_app`) and `DATABASE_URL_DIRECT` (Neon direct, `qc_app`);
  - `QC_MASTER_KEY` + `QC_MASTER_KEY_VERSION` (the existing key, never regenerated) and `METRICS_TOKEN`;
  - the OAuth client IDs and secrets.

  `DATABASE_MIGRATION_URL` is used only by the release step, never by the running API.
- [ ] Environment set:
  - `QC_PROFILE=demo`, `WORKER_MODE=embedded`, `FEATURE_SANDBOX=false`, `FEATURE_LIVE_INSPECTION_PUBLIC=false`, `ALLOW_PRIVATE_TARGETS=false`;
  - **no** `OPENROUTER_API_KEY`, `GROQ_API_KEY` or `GEMINI_API_KEY` (demo refuses the first two at startup);
  - `CORS_ORIGINS=["https://app.<domain>"]`, `COOKIE_DOMAIN=.<domain>`, `PUBLIC_API_URL`, `WEB_BASE_URL` (https), `TRUSTED_PROXY_HOPS` matching the host's proxy.
- [ ] Release:
  - `alembic upgrade head` (already current; a no-op);
  - deploy the API image;
  - `/readyz` → `ok/current`;
  - `qc_workers_alive 1`, with a `source_digest` equal to the release commit's.
- [ ] Web deployed with `NEXT_PUBLIC_API_BASE_URL=https://api.<domain>`.
- [ ] `demo_probe --base-url https://api.<domain> --web-origin https://app.<domain>` → 17/17.
- [ ] OAuth checklist passed for GitHub and Google.
- [ ] Metrics scraped with the token; an alert on `qc_workers_alive == 0` and on `qc_jobs_oldest_pending_seconds`.
- [ ] F1 investigated, or accepted in writing for the trial.
- [ ] Off-provider `pg_dump` scheduled, or the Neon PITR window accepted; the master key stored in a second, offline place.

## 10. Assessment

| Area | Assessment |
|---|---|
| Credentials | **Resolved** for the exposed `qc_app` password: rotated by the owner, old value refused, no copy in Git. One stale plaintext backup remains on disk (owner action) |
| Hosted database | **Ready.** Neon is at `0016`, data is unchanged, evidence verifies, and the grants are least-privilege |
| Worker | **Ready.** The checkout's worker runs against Neon, heartbeats, reports its digest and stops in 1.5 s. Reliability properties are verified locally |
| Restricted demo | **Ready locally** (17/17). Not yet verified on a deployed origin |
| OAuth | **Unverified in production.** Code review and automated tests pass; real sign-in is pending a deployed origin |
| Operations | **Adequate for a restricted trial, not production-grade.** Metrics and runbooks are complete; alerting and a hosted restore drill are missing |
| Code health | All local suites green. One intermittent server-side error (F1) is unresolved |

**Verdict:** the backend is ready to be deployed for a **restricted hosted trial** once the owner chooses a host and domain. The trial itself should start only after these three things: the OAuth checklist passes on that origin, the demo probe passes on that origin, and F1 is investigated or explicitly accepted. Nothing has been deployed publicly.

## 11. Commits and CI

PENDING_CI
