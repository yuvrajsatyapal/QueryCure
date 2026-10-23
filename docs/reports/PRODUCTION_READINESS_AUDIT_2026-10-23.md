# Production readiness audit (2026-10-23)

Read-only assessment at `e8da80b` + the final UI polish ([FINAL_UI_POLISH](FINAL_UI_POLISH_2026-10-23.md)). It re-checks the code against the previous [FINAL_BACKEND_DEPLOYMENT_READINESS](FINAL_BACKEND_DEPLOYMENT_READINESS_2026-10-18.md) report rather than repeating it. Nothing was deployed, no hosted service was touched, no real OAuth sign-in and no paid model call was made, and no test connected to Neon.

**Not performed (so not claimed):** real Google/GitHub sign-in, a deployed origin, a hosted smoke test or demo probe, a Neon PITR restore, load testing.

## 1. Findings

| # | Severity | Area | Finding and evidence | Recommended fix |
|---|---|---|---|---|
| B1 | **Blocker** (for any deployment) | Deployment | No host, domain or deploy workflow exists (owner decisions D1, D5; DEPLOYMENT §4 says releases are manual). | Owner chooses host and domain; follow §3 below. |
| B2 | **Blocker** (for opening sign-in) | OAuth | Code is reviewed and tested (state compared with `hmac.compare_digest`, PKCE S256 in `auth/oauth.py`, `_safe_return_to` accepts only same-site relative paths, redirect URI built from `PUBLIC_API_URL`), but real Google and GitHub sign-in on a deployed origin has never run. | Register callbacks on the deployed origin, then run [OAUTH_VERIFICATION_CHECKLIST](../engineering/OAUTH_VERIFICATION_CHECKLIST.md) with test accounts. |
| H1 | High | SSE / DB pool | F1 (2026-10-18): an intermittent pool-checkout 500 in an SSE stream, root cause unknown. Re-read `api/sse.py`: each batch opens and closes its connection before yielding, so a stream does not hold a connection while idle; the hypothesis "connection returned with a statement in flight" is still unexplained. Not reproduced in this session: 2 full e2e runs, 0 server 500s in the logs. | Investigate before a trial on Neon's pooled endpoint, or accept in writing; alert on 5xx rate. |
| H2 | High | Observability | Metrics exist (`/metrics` with bearer token; `qc_workers_alive`, `qc_jobs_oldest_pending_seconds`, …) but nothing scrapes or alerts (F2). A dead worker would leave runs queued silently. | With the host: scrape, alert on `qc_workers_alive == 0`, oldest pending job, 5xx rate. |
| M1 | Medium | BYOK secrets | AES-GCM with a 12-byte random nonce and AAD bound to table/row/user (`core/crypto.py`); keys never logged (`core/redaction.py`). `SecretBox` can hold several key versions, but settings load **one** key (`from_base64`), and **no re-encrypt job exists**, although SECURITY §5 says "`key_version` supports rotation (re-encrypt job)". The master key therefore cannot be rotated today without user re-entry. | Correct SECURITY §5 (done in this change), then add a previous-key setting plus a re-encrypt CLI before relying on rotation. Keep the offline key copy (DEPLOYMENT §4c). |
| M2 | Medium | Backup / restore | Local restore drill passed (2026-10-18: 714/714 artifacts, 43/43 reports). No hosted restore: Neon PITR window unconfirmed, no off-provider `pg_dump` scheduled. | Confirm the PITR window; run DEPLOYMENT §4c on a Neon child branch once; schedule `pg_dump -Fc`. |
| M3 | Medium | Web config | `NEXT_PUBLIC_API_BASE_URL` falls back to `http://localhost:8000` in both `lib/api/client.ts` and the CSP in `next.config.ts`. A production build without it ships a broken app (every call blocked by its own CSP) instead of failing. | Fail `next build` when `NODE_ENV=production` and the variable is unset (small, separate change; not made here: config, not polish). |
| M4 | Medium | Web security | CSP allows `script-src 'unsafe-inline'` (documented gap, SECURITY §5c); no HSTS on the web app (the API sets it in the demo profile). | Nonce-based CSP later; set HSTS at the web host. |
| M5 | Medium | Credentials | Previous report: a stale plaintext `env.bak` outside the repo still needed deleting (owner). Not verifiable from here. | Owner deletes it and confirms. |
| L1 | Low | Dependencies | `pnpm audit --prod --audit-level high`: **0**. `pip-audit` on the locked runtime set: **0**. Full `pnpm audit`: 1 high, dev-only `braces` via `eslint-config-next` (no patched release; not in the bundle). | Track; bump when a fix ships. |
| L2 | Low | SSE | Streams per user are not capped. Each stream costs one async task and wakes on NOTIFY; DB connections are per batch. | Cap concurrent streams per user if abuse appears. |
| L3 | Low | Reports | F3 unchanged: `report-builder@2` should surface the transport floor and claim removals (new version ID; frozen builders, ADR-0015). | Plan as its own change. |

## 2. Verified in code (no change needed)

| Area | Evidence |
|---|---|
| Sessions | `api/routers/session.py`: session cookie `HttpOnly`, `Secure` outside the local profile, `SameSite=Lax`; CSRF double-submit middleware (`api/middleware.py`, only `POST /session` exempt, ADR-0013). |
| Rate limits | Postgres token buckets (`api/rate_limit.py`, `domain/limits.py`) on session creation (IP), run creation (user + IP), inspect, connections, settings, report and experiment replay; 429 `RATE_LIMITED`; buckets pruned by `ops/retention.py`. |
| Authorization | Ownership checks and negative tests in `tests/security`: **145 passed** this session against local Docker. |
| Worker | `worker/runner.py`: lease + heartbeat, cancel on lost lease, dead-letter on lease exhaustion, abandon to lease expiry on shutdown; presence rows with source digest (migration 0016). |
| SSE | `Last-Event-ID` and `after_seq` resume (`api/routers/runs.py`), `retry: 3000`, heartbeats, terminal-event close; LISTEN on a dedicated direct connection with keepalives (`api/deps.py`). |
| DB access | Mode B through `connectors/inspection_gateway.py`; Mode C in disposable clones; SSRF guard; covered by the 145 security tests run this session (integration suite not re-run; backend unchanged since 2026-10-18). |
| Health / rollback | `/healthz`, `/readyz` (`ok/current` checks migration head); migrations are expand-only, so rollback = redeploy the previous image (DEPLOYMENT §4). |
| CI | `ci.yml` (backend, evals, frontend, e2e) and `audit.yml` (pip-audit, `pnpm audit --prod`). |

## 3. Recommended deployment sequence (restricted trial)

1. Owner: choose host and domain; delete `env.bak`; confirm the Neon PITR window.
2. CI green on the release commit (all `ci.yml` jobs and `audit.yml`).
3. Host secret store: `DATABASE_URL` / `DATABASE_URL_DIRECT` (`qc_app`), `QC_MASTER_KEY` + version (existing key, never regenerated; second offline copy), `METRICS_TOKEN`, OAuth secrets. No model keys in the demo profile.
4. Environment per DEPLOYMENT §3 (`QC_PROFILE=demo`, `WORKER_MODE=embedded`, `FEATURE_SANDBOX=false`, CORS / cookie domain / public URLs / `TRUSTED_PROXY_HOPS`).
5. Release: `alembic upgrade head` (currently a no-op at 0016) → deploy API image → `/readyz` `ok/current` → `qc_workers_alive 1` with the release `source_digest`.
6. Web: build with `NEXT_PUBLIC_API_BASE_URL=https://api.<domain>` (check the CSP header names it; see M3), deploy, set HSTS.
7. `demo_probe` against the deployed origins (expect 17/17); OAuth checklist for both providers.
8. Scrape metrics and enable alerts (H2); decide on F1 (H1).
9. Open to the restricted audience.

## 4. Rollback plan

- **Web:** redeploy the previous build; no state.
- **API / worker:** redeploy the previous image tag. Migrations are expand-only, so the older image runs on the newer schema. Never `alembic downgrade` a database with user data (0015 and 0013 downgrades drop data).
- **Bad migration:** stop the release before traffic; restore from Neon PITR to a child branch, verify with `python -m querycure.ops verify-integrity`, then repoint (DEPLOYMENT §4c).
- **Leaked credential:** DEPLOYMENT §4d (database passwords). The master key is never rotated as part of that (M1).
- **Kill switch:** scale the API to zero or set `FEATURE_*` flags off; sealed reports and artifacts are immutable and survive.

## 5. Verdict

Ready for a **restricted hosted trial** once B1 and B2 are done and H1/H2 are handled or explicitly accepted. Not production-grade until alerting, a hosted restore check and master-key rotation exist.
