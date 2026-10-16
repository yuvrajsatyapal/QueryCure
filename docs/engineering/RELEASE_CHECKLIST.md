# Release checklist

Use for every public deployment. Tick each item in the release notes; an unticked item blocks the release. Status as of Phase 5 (2026-10-16): **artifacts ready, verified locally; no public deployment made.**

## 1. Code and CI
- [ ] `main` is clean and pushed; CI green on that commit: backend (3.12, 3.13), integration + security, eval smoke, Mode C fixture evals, frontend, e2e (incl. axe), image builds.
- [ ] `Audit` workflow green (pip-audit, pnpm audit) within the last week.
- [ ] No secrets in the diff (`git diff | grep -iE "sk-or|password|secret"` reviewed); `.env` files untracked.

## 2. Configuration and secrets (host secret store, never env files in images)
- [ ] `QC_PROFILE=demo`.
- [ ] `QC_MASTER_KEY` set (32 random bytes, base64) and **persisted** across deploys; recorded in the secret store's history.
- [ ] `DATABASE_URL` / `DATABASE_URL_DIRECT` use the restricted `qc_app` role (direct endpoint for LISTEN); `DATABASE_MIGRATION_URL` (owner) only on the migration step; `DATABASE_RETENTION_URL` only on the retention job.
- [ ] No `OPENROUTER_API_KEY` / `GEMINI_API_KEY` (startup refuses a server key in the demo profile; BYOK only).
- [ ] `FEATURE_SANDBOX=false`, `FEATURE_LIVE_INSPECTION_PUBLIC=false`, `ALLOW_PRIVATE_TARGETS=false`.
- [ ] `CORS_ORIGINS` = exactly the web origin; `COOKIE_DOMAIN` = the registrable domain shared by `app.` and `api.`.
- [ ] `TRUSTED_PROXY_HOPS` matches the host's proxy chain (otherwise rate limits key on the proxy address).
- [ ] `METRICS_TOKEN` set (or accept that metrics are unreachable).
- [ ] GitHub OAuth (optional): app callback `https://api.<domain>/api/v1/auth/github/callback`; `GITHUB_CLIENT_ID/SECRET`, `PUBLIC_API_URL`, `WEB_BASE_URL` (HTTPS).

## 3. Database
- [ ] Metadata Postgres 15+ with `uuid-ossp`; roles created (`infra/docker/metadata-init/01-roles.sh` equivalent).
- [ ] `alembic upgrade head` run as the owner role **before** the new app version starts; expand-only migrations confirmed.
- [ ] Point-in-time restore available and its window noted; demo data declared disposable.

## 4. Deploy
- [ ] API/worker image deployed on an **always-on** instance (no idle spin-down); stop timeout > `WORKER_SHUTDOWN_GRACE_SECONDS` (default 20 s).
- [ ] `/api/v1/healthz` 200 and `/api/v1/readyz` 200 (`database: ok`, `migrations: current`); uptime check on `/readyz`.
- [ ] Web deployed with `NEXT_PUBLIC_API_BASE_URL=https://api.<domain>`; CSP header present.
- [ ] HTTPS on both origins; HSTS header on API responses.
- [ ] Retention job scheduled daily.

## 5. Smoke test (production)
- [ ] `/me` → `profile: demo`, `live_inspection: false`, `sandbox: false`.
- [ ] `/demo` lists the gallery; one "Check stored digests" → consistent.
- [ ] Creating a run without a key → 503 with the "add your own key" message; `sandbox_benchmark` → 403.
- [ ] `/api/v1/docs` → 404; `/api/v1/internal/metrics` → 404 without token, 200 with it.
- [ ] Cookies `Secure; HttpOnly; SameSite=Lax`.

## 6. Rollback
- [ ] Previous image tags recorded. Roll back by redeploying them; **never** `alembic downgrade` a database with user data.

## 7. Known limitations to state publicly
- Benchmarks on the demo are prerecorded and labelled; no live sandbox, no live database inspection.
- Single instance, no HA; a restart interrupts SSE (clients reconnect) and resumes runs after lease expiry.
- Report verification proves consistency with stored digests, not authenticity.
- Free model quality and free-tier quotas limit analysis depth and volume.
