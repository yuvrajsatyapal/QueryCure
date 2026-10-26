# Current Phase

| Field | Value |
|---|---|
| Phase | **5 — Production polish** (authorized by the owner 2026-10-16). Phase 1: [PHASE_1_REPORT](reports/PHASE_1_REPORT.md); Phase 2: [PHASE_2_REPORT](reports/PHASE_2_REPORT.md); Phase 3: [PHASE_3_REPORT](reports/PHASE_3_REPORT.md); Phase 4 owner-reviewed 2026-10-16: [PHASE_4_REPORT](reports/PHASE_4_REPORT.md) |
| Status | **Phase 5 implementation complete and verified locally (2026-10-16); not publicly deployed; awaiting owner review** ([PHASE_5_REPORT](reports/PHASE_5_REPORT.md)). Exit criterion "deployed" not met by design (needs owner approval, domain, accounts) |
| Last updated | 2026-10-26 |
| Application code | Phases 1–3 (API, metadata DB, parsing, inspection gateway, artifact store, six demo workloads, multi-agent graph, approval gate, sandbox benchmark engine `bench@2`, tournament, web workspace) plus Phase 4: Benchmark Auditor (deterministic checks + downgrade-only review), atomic finalization with versioned reports (`report-builder@1`, `report-md@1`), report replay, experiment replay with statistical comparison, re-investigation start, plan diff; migrations 0001–0012; web app adds Report tab, report and replay pages, lineage drawer, audit panel and plan diff |

## Post-Phase-5 addition (2026-10-16)

- [x] **Google sign-in.** Second OAuth provider on the shared flow (`auth/google.py`, `auth/oauth.py`, provider-parameterised `api/routers/auth.py`); `features.google_login`; `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`; scopes `openid profile`, no email stored; no migration. Tests: `test_google_oauth.py`, config unit tests; ADR-0013 amended. Verified: ruff, mypy, 743 unit, 579 integration + security, frontend lint/typecheck/85 tests/build.

- [x] **Neon PgBouncer compatibility (2026-10-17, [ADR-0025](../engineering/adr/ADR-0025-pgbouncer-compatible-metadata-connections.md)).** Pooled endpoints get per-transaction timeouts instead of rejected startup options; LISTEN and the checkpointer use `DATABASE_URL_DIRECT`; settings validate the URL pair; `qc_app` / `qc_retention` privileges pinned by a security test. Verified live against Neon (readiness, job claim, LISTEN/NOTIFY, checkpointer).
- [x] **End-to-end AI investigation and functional audit (2026-10-17, [report](../reports/E2E_AUDIT_2026-10-17.md)).** Real OpenRouter runs from the web UI against Neon metadata and the local Docker sandbox. `openrouter/free` ended inconclusive (invalid output and timeouts); a pinned free model reached `verified_recommendation` (composite index 2.95×, noise warning, 3 experiments). Report replay verified; experiment replay honestly inconclusive. Fixed: eval CLI refuses non-local admin URLs; e2e pinned to local Docker; budget meters poll while a run is active; `llm.model` refused instead of ignored; DB outage → 503; mobile header; dashboard copy; replay duplicate key; token counts readable in logs. Open items O1–O11 in the report (O1 default model, O2 narrative vs verdicts first). Verified: ruff, mypy, 767 unit, 603 integration + security, evals 5/5 + 2/2, frontend lint/typecheck/88 tests/build, e2e 14/14.
- [x] **AI reliability and evidence-integrity hardening (2026-10-17, [ADR-0026](../engineering/adr/ADR-0026-deterministic-claim-grounding-and-model-reliability.md), [report](../reports/AI_RELIABILITY_HARDENING_2026-10-17.md)).** Fixes audit O1, O2, O3, O6 and O7.
  - Deterministic claim grounding (`claims@1`) runs at every LLM prose boundary and again against final verdicts.
  - Statistics provenance separates planner statistics from counters reset by cloning.
  - Timeouts are retried once; a bounded free fallback also covers invalid output; a per-run model circuit breaker skips failing models.
  - Pinned default model, startup warning for untested models, one-request probe CLI.
  - Run-level `MODEL_UNAVAILABLE` with `error_message`; the quota excludes undispatched attempts.
  - No report-builder change.
  - Verified: ruff, mypy, 837 unit, 607 integration + security, smoke evals 5/5 (one case re-recorded), frontend lint/typecheck/89 tests/build, e2e 14/14.
  - Real-model smoke run on local metadata: `verified_recommendation`, 7/7 valid calls, no stale-statistics hypothesis, report replay `verified`.
  - **Open:** the Mode C eval recordings (`orders_sandbox_composite_index`, `rewrite_trap_sandbox`) must be re-recorded, because the O3 context text changed and today's free quota ran out. CI "Eval Mode C" fails until then.
- [x] **Groq provider (2026-10-17, [ADR-0027](../engineering/adr/ADR-0027-groq-provider-trusted-free-plan.md)).** `LLM_PROVIDER=groq` with a local-profile `GROQ_API_KEY` (`llm/groq.py`, OpenAI-compatible JSON mode). Allowed while `LLM_FREE_ONLY` is on by trusting the key to be on Groq's free plan (owner decision; Groq reports no cost). Per-day 429 stops the run; the minute limiter applies; the OpenRouter daily count does not. Refused in the demo profile; no BYOK, no UI change. Tests: `tests/unit/llm/test_groq.py`. Verified: ruff, mypy, 850 unit, 607 integration + security. Not verified live: no Groq request has been made.

- [x] **Backend production hardening (2026-10-18, [report](../reports/BACKEND_PRODUCTION_HARDENING_2026-10-18.md), [ADR-0028](../engineering/adr/ADR-0028-evidence-specific-claim-grounding.md), [ADR-0029](../engineering/adr/ADR-0029-transport-floor-and-benchmark-repeatability.md)).**
  - **CI green locally on every job:**
    - the flaky noise-screen test was redesigned;
    - both Mode C cases were re-recorded (2/2, 22 real requests plus 13 on a failed contended attempt);
    - smoke 5/5, 1115 unit, 486 integration + security, frontend 89 tests and build, e2e 14/14.
  - **`claims@2`:** evidence-specific grounding (subject attribution, typed claims). `claims@1` is frozen.
  - **Benchmark:** a 20-session repeatability study per path, which showed the relay compresses speed-ups (5.9× vs 13.8×). Each result records a transport floor, and the worker warns on the relay path.
  - **Worker:** presence rows with a source digest (migration 0016), and failure-diagnosing metrics.
  - **Shutdown hang fixed:** metadata connections get keepalives and a connect timeout; teardown is bounded.
  - **Config:** blank settings now mean unset.
  - **Eval guards:** no overwrite on failure, a quiet-host pre-flight, and a local-only admin URL.
  - **Demo probe:** 17/17 against the local demo stack.
  - **DR:** a runbook plus a local restore drill (714/714 artifacts, 43/43 sealed reports verified).
  - **Open:**
    - apply migration 0016 to Neon (owner approval), then restart the Neon worker;
    - rotate the Neon `qc_app` password;
    - test real OAuth on a deployed origin;
    - surface the transport floor and claim removals in `report-builder@2`.

- [x] **Final backend deployment readiness (2026-10-18, [report](../reports/FINAL_BACKEND_DEPLOYMENT_READINESS_2026-10-18.md)).**
  - **Credential:** the owner rotated the Neon `qc_app` password. Pooled and direct connect with the new one, and the old one is refused ("password authentication failed") on both. A redacted scan found it in no Git object or repo file. A stale plaintext `env.bak` outside the repo still needs deleting (owner).
  - **Neon migrated 0015 → 0016** as `neondb_owner`, approved by the owner:
    - objects and grants verified as each role;
    - 10 table fingerprints identical before and after;
    - `verify-integrity` (read-only): 94/94 artifacts and 9/9 reports `verified`.
  - **Worker on Neon:** the checkout's API and worker ran for about 45 s (no jobs pending, so none ran):
    - `/readyz` `ok/current`;
    - heartbeat row with a digest equal to the checkout's, and `qc_workers_alive 1`;
    - SIGTERM exit in 1.5 s with `stopped_at` set.
  - **New:** `python -m querycure.ops verify-integrity` (read-only restore check). Runbooks in DEPLOYMENT: §4c Neon PITR validation on a child branch, §4d credential rotation. DEPLOYMENT §4 now lists the real CI workflows (no deploy workflow exists). [OAUTH_VERIFICATION_CHECKLIST](../engineering/OAUTH_VERIFICATION_CHECKLIST.md). A guard test keeps tests from reading `backend/.env`.
  - **Verified locally:**
    - ruff, format, mypy; 1116 unit; 490 integration + security;
    - evals 5/5 + 2/2 with 0 real requests;
    - frontend lint, typecheck, 89 tests, build;
    - e2e 14/14 ×3; demo probe 17/17.
  - **Open:**
    - **F1:** an intermittent SSE pool-checkout 500, seen in 1 of 3 e2e runs, root cause unknown;
    - host and domain (D1, D5);
    - real OAuth on a deployed origin;
    - alerting;
    - a Neon PITR check;
    - `report-builder@2`.

- [x] **UI redesign: Linear structure, LangSmith trace, dark-first (2026-10-19, [ADR-0030](../engineering/adr/ADR-0030-linear-langsmith-ui-direction.md)).**
  - **Tokens and type:** Linear-style neutrals plus status tokens `--running` and `--approval` (new). Teal brand accent kept. Inter + JetBrains Mono. Dark by default. Shared `qc-*` Tailwind utilities.
  - **Shell:** sidebar with grouped nav, active state, and account footer; mobile drawer.
  - **Pages:** dashboard (status counts, in progress, recent, get started); Linear-style History list; simple landing page with an illustration labelled as such.
  - **Investigation page:** header with breadcrumb and status pill, underlined result tabs, approval card in the approval color.
  - **Trace:** client-built span tree from existing SSE events (`lib/events/trace.ts`, TDD) with a latency waterfall and expandable details (`TraceView`, replacing `Timeline`). No backend or API change.
  - **Docs:** DESIGN_SYSTEM and UI_UX §3.6 updated. e2e assertions moved to the new wording.
  - **Verified:** frontend lint, typecheck, 95 unit tests (incl. 4 trace-builder + 2 trace-view), build; e2e 14/14 (axe clean in light and dark). Contrast computed per token: all text tokens ≥ 5.1:1, `--faint` (≈ 2.8:1) restricted to icons.

- [x] **UI Pass 1: split trace, evidence navigation, investigation header (2026-10-19, UI_UX §3.6, owner-approved).** Frontend only; no API or schema change.
  - **Split trace:** step tree (WAI-ARIA tree, keyboard model) beside the selection; the run row shows the results tabs, any step shows Input · Output · Metadata · Evidence. Only recorded data is shown; prompts, redacted tool arguments and raw model output are stated as unavailable. Parallel analysts stay sibling steps.
  - **Evidence navigation** (`lib/investigation/links.ts`, TDD): finding/hypothesis → trace step by event key (missing and multiple matches named); plan-node evidence → Plan tab node (plan or node absent, load failure reported); plan nodes list "Cited by" with pending and failed counts.
  - **Header:** run selector dropdown, compact usage meters from real run usage/budget, sticky from `md` up.
  - **Fix found in browser verification:** `write_report` (no `node.completed` by design) now closes on `run.concluded` / `report.ready` instead of reading "did not finish".
  - **Correction to the redesign entry above:** its "axe clean in light and dark" was only true for dark. With dark as the fixed default, `emulateMedia` no longer switched themes. The e2e now applies the theme class (`e2e/theme.ts`), and light mode passes too.
  - **Verified:** lint, typecheck, 111 unit tests, build, e2e 14/14 against local Docker (the investigation e2e now also checks Cited by, Show step, tree keys and axe in both themes). Browser check on a local stub-model run at 398px and 1366px.

- [x] **UI Pass 2: Reports, Connections, Settings, Dashboard, History, Demo gallery (2026-10-19, UI_UX §3.2, §3.3, §3.9, §3.11–§3.13, owner-approved).** Frontend only; existing endpoints; no backend or contract change.
  - **Reports:** reading layout with a numbered table of contents (only sections the report renders), verdict header, icon callouts, AI-written blocks, and a navigation bar from the sealed report (run, replay page, original run, parent run). Report content, exports and the frozen Markdown renderer are unchanged.
  - **Connections / Settings:** shared `SettingsSection` rows. Connection form in Identity / Server / Credentials groups after the read-only role. Test status pills (passed, failed, role refused, never tested). Capability refusals shown as ✕. Settings gains Appearance (native theme radios).
  - **Dashboard:** counts per status from `GET /investigations?status=…&limit=100`; exact unless a cursor is returned, then `100+` (stated). Refreshes every 10 s while anything is in flight. Replaces counts over the 25 newest.
  - **History:** server-side outcome filter (the frontend client gained the `outcome` param the API already had), Clear filters, result line, and grouping by local day. Sorting and mode filtering are **not offered**: the endpoint has a fixed newest-first order and no mode parameter.
  - **Demo gallery:** outcome pills, a Prerecorded tag on every card, benchmark stats as a table of the API's own strings, and the demo header matches the app.
  - **Verified:** lint, typecheck, 122 unit tests, build, e2e 15/15 against local Docker (axe now also covers Connections, light and dark). Browser check on local data at 398px and 1280px.

- [x] **UI Pass 3: guided New investigation, command palette, keyboard shortcuts (2026-10-23, UI_UX §3.14–§3.15, owner-approved).** Frontend only. Existing endpoints, and the same create request body as before, so server validation, mode rules, approvals and the idempotency key are unchanged. No backend or schema change.
  - **Guided flow:** SQL query → Plan source → Investigation mode → Review & start.
    - Step 1 checks the SQL through `POST /inspect/sql`, which runs the same `validate_select` as creation.
    - A workload example that replaces the SQL makes the check stale, and Review checks it again before Start is enabled.
    - Modes the plan source cannot support are disabled with the reason (`lib/investigations/wizard.ts`, TDD).
    - Focus moves to each newly opened step. `⌘/Ctrl+Enter` advances outside the SQL editor; CodeMirror keeps its own `Mod-Enter`.
  - **Suggested titles:** `suggestTitle` (`lib/investigations/title.ts`, TDD) is pure and deterministic, with no LLM. It strips comments and literals and excludes CTE names. A blank title submits the suggestion; a typed title overrides it.
  - **Command palette:** `⌘K` / `Ctrl+K`, or the sidebar "Search or jump to…" button. It holds actions, navigation, the investigation page's tab commands, recent investigations, and title search through `GET /investigations?q=` (debounced, with a skeleton and an empty state). It is a modal combobox with a focus trap and focus restore.
  - **Shortcuts:** `?`, `c`, `g d/h/c/s`, and on the investigation page `[`/`]` and `g f/p/t/r`. None fire while you type in a field or CodeMirror, or while a modal is open. The shortcuts dialog is generated from the live command list.
  - **Feedback:** skeletons while workloads, connections, plans and the investigation load; pending button labels; a polite announcement after a theme change.
  - **Fixes found in verification:**
    - The API sends `statement_type` in lower case; it is now displayed in upper case, and the unit mock now matches the API.
    - The palette's group-label ids contained spaces, which broke `aria-labelledby`.
    - axe `scrollable-region-focusable` failed once the results overflowed. The results region is now a tab stop with the same keys, and the e2e forces the overflow.
  - **Verified:**
    - lint, typecheck, 158 unit tests (title 10, wizard rules 5, keyboard helpers 6, Workspace 10, commands 10), build;
    - e2e 18/18 on three consecutive runs against local Docker, including the new `keyboard.spec.ts`: keyboard-only start, tab shortcuts, palette search, axe with the palette open in light and dark, and 390 px mobile;
    - browser check on local stub-model data at 1366 px and 375 px.
  - **Not done:**
    - The palette offers no destructive actions (cancel run, delete).
    - On non-US layouts, `?` depends on the browser reporting `?` as the key.
  - **Environment note:** at the time of this pass, `next build` / `next dev` printed a Next.js security advisory and stopped every other invocation; a retry continues. The e2e runs above were retried on that stop. The Next.js upgrade is not part of this pass.

- [x] **Next.js security upgrade 16.4.0 → 16.4.2 (2026-10-23, separate worktree, awaiting owner review before merge).** Frontend dependencies only: `next` and `eslint-config-next` pinned to `16.4.2`; React 19.3.0, Tailwind 4, TypeScript and `next.config.ts` unchanged.
  - **Advisories fixed** (all `>=16.0.0 <=16.4.0`, first patched `16.4.1`): GHSA-673q-mjm6-r5xr (critical, RCE in `use cache` functions returning typed arrays), GHSA-2464-fhr4-w9xw (critical, RCE in Image Optimization with SVG via `sharp`; lockfile already had `sharp@0.35.5`), GHSA-p3m5-59mp-jv5r / CVE-2026-94482 (high, Server Actions DoS). `16.4.2` is the same-minor LTS patch that adds Turbopack stability fixes (turbo-tasks snapshot consistency, GC edge teardown, chunk-list collisions).
  - **Why builds stopped:** Next 16.4 defaults `experimental.agentUpgrade` to `security`. When it detects a coding agent (`CLAUDECODE` / `AI_AGENT`) and the installed version is affected, `next dev`/`next build` throw `SecurityFatalError` (exit 1) and write a retry receipt in `.next/cache/next-agentic-upgrade-retries` valid for 5 minutes, so the next run passes and the one after that stops again. Reproduced on 16.4.0 (exit 1, 0, 1); gone on 16.4.2. The check was left at its default, not disabled. In an interactive terminal outside an agent, the same check shows an upgrade menu instead.
  - **Second cause, independent of the advisory:** only one `next dev` per project directory; a second one exits 1 ("You can access the existing server…"). Playwright's web server (`reuseExistingServer: false`) fails the same way if a preview `next dev` is already running in `frontend/`. `next build` alongside a running `next dev` works.
  - **`next upgrade --agent=security` not used:** it downloads a skill with `npx skills@…` from GitHub, hands off to a nested agent, records telemetry and writes `experimental.agentUpgrade` into the config. A pinned patch bump was smaller.
  - **Verified:** `pnpm audit --prod --audit-level high` clean (the CI gate); lint; typecheck; 158 unit tests; 5/5 clean `next build`s (`.next` removed each time); 3/3 `next start` and 5/5 clean `next dev` starts serving `/app` with HTTP 200; Playwright 18/18 on two consecutive runs against local Docker with no retries (axe, keyboard, investigation, sandbox approval, lifecycle). Local Docker only; no `.env` in the worktree.
  - **Remaining:** dev-only `braces <=3.0.3` (GHSA-vfj7-8cjw-p6xm, high, no patched release) through `eslint-config-next` → `fast-glob` → `micromatch`; not in the production bundle and not caught by the `--prod` gate. A future Next advisory will bring the alternating stop back under an agent until Next is upgraded again.

- [x] **UI Pass 4: execution-plan viewer and benchmark analytics (2026-10-23, UI_UX §3.16–§3.17).** Frontend only: existing `GET /runs/{id}/plans`, `GET /experiments/{id}`, `GET /runs/{id}/verifications`; no backend, contract, schema or benchmarking change; no new dependency (charts are HTML on the design tokens).
  - **Plan viewer** (`PlanExplorer`, `lib/plan/analysis.ts`, TDD):
    - keeps the parsed parent → child structure, including subplan relationships;
    - adds loops, est. cost, time per loop, a summary line, Expand all / Collapse all / Hottest node, a thresholds legend, and a full-width modal (Esc returns focus);
    - *expensive* = self time ≥ 20% of the root; *hottest* unchanged;
    - row misestimates use the backend ratio: significant ≥ 10×, severe ≥ 100×; not flagged when never executed, when under 100 rows across all loops, or when fewer rows than estimated come from a node a LIMIT stopped early.
  - **Fix found in browser verification:** the recorded orders plan showed Gather Merge "433× over · severe" only because `LIMIT 20` stopped it. The early-stop rule above walks up to the Limit and stops at Sort, Hash or a non-sorted Aggregate.
  - **Evidence navigation:** a node selected from evidence, the report or Hottest node is revealed when its parents are collapsed. Pass 1 trace ↔ evidence ↔ plan links and Cited by are unchanged.
  - **Benchmark analytics** (`BenchmarkAnalytics`, `lib/benchmark/analysis.ts`, TDD against a real result recorded from a local stub-model run):
    - per param set, latency distributions of every recorded sample, with the box computed by the engine's quartile method (it matches the stored IQR);
    - a speedup forest plot with a 1× no-improvement line and the configured `min_effect` / `max_regression`, drawn only from valid recorded stats and never for arms that failed correctness;
    - verdict classes from backend verdicts: Disputed = auditor downgrade; Unverified = not measured;
    - recorded warnings: transport floor, robust CV over `max_cv`, failed samples, noise screens, p95 n/a, prerecorded. Host contention is stated as not recorded;
    - a replicate selector, so experiments are never pooled, and a "Recorded samples" table;
    - the stats table gains IQR, robust CV, min–max and failed counts.
  - **Other fixes:**
    - the ranking table overflowed the page at 375 px;
    - the selected row's teal tint dropped the Verified badge to 4.49:1 in light mode, so it now uses `--surface-2` with an accent bar;
    - the stats table scroll region was not focusable.
  - **Environment:** the first build stopped with Next's `SecurityFatalError` because `node_modules` still held 16.4.0 after the 16.4.2 merge. `pnpm install --frozen-lockfile` fixed it; there was no version change.
  - **Verified:**
    - lint, typecheck, 212 unit tests (plan analysis 16, benchmark analysis 18, format 4, PlanExplorer 8, BenchmarkAnalytics 8), production build;
    - Playwright 18/18 on two consecutive runs against local Docker with the stub model. The specs now also cover the full-width plan (axe in light and dark, focus return) and the tournament analytics (axe in light and dark, no sideways scroll at 390 px);
    - browser check on local data at 1366 px, 1280 px light and 375 px.
  - **Not done:** correctness panel (fingerprints) of UI_UX §3.8; early stops from semi/anti joins and `EXISTS` are not detected; host contention has no recorded signal to show.

- [x] **Production hardening for a restricted hosted trial (2026-10-23, [report](../reports/PRODUCTION_HARDENING_2026-10-23.md), [DEPLOYMENT §3a](../architecture/DEPLOYMENT.md#3a-restricted-hosted-trial-recommended-architecture-2026-10-23-not-deployed)).** Code-only, nothing deployed; no migration, contract, benchmarking, claims or replay change.
  - **F1 root cause found and fixed:** a client disconnect during the pool pre-ping left the ping's `SELECT 1` ACTIVE (anyio cancellation also cancels psycopg's query cancel), and SQLAlchemy's `do_ping` `finally` raised `can't change 'autocommit' now`, replacing the cancellation. Reproduced by a test that fails before the fix; fixed by shielding each SSE database round trip. SSE failures after the response started are logged (`sse_stream_failed`), counted, and end the stream. The web client reconnects itself after HTTP errors (bounded backoff, `after_seq`).
  - **Config:** `next build` fails without a valid `NEXT_PUBLIC_API_BASE_URL` (https, or loopback http) and the web app sends HSTS. Hosted settings refuse `*`/http CORS origins, http public URLs, a malformed cookie domain and short metrics tokens; the API refuses to start without `DATABASE_URL`/`CORS_ORIGINS`.
  - **Observability:** per-process `qc_http_responses_total`, `qc_http_unhandled_errors_total`, `qc_sse_streams_*`, `qc_process_uptime_seconds`; alert rules in OBSERVABILITY §8. Logs: `hide_parameters=True`, Groq keys masked.
  - **Verified:** ruff, mypy, 1005 unit, 626 integration + security, smoke evals 5/5 (0 real requests), frontend lint/typecheck/239 tests/build, e2e 18/18 ×3 with 0 server errors, audits (runtime 0), demo stack `demo_probe` 17/17.
  - **Disclosure:** one `alembic current` read `alembic_version` on Neon as the owner role, because `backend/.env` defines `DATABASE_MIGRATION_URL` twice. Read-only.
  - **Open (ranked in the report):** host and domain; real OAuth; access is not restricted (anonymous sessions; an allowlist needs approval); Neon compute allowance with an always-on worker; alerting not wired; `TRUSTED_PROXY_HOPS` for the host; hosted restore check; master-key rotation; CSP `unsafe-inline`.
- [x] **Restricted-trial sign-in allowlist (2026-10-23, [ADR-0031](../engineering/adr/ADR-0031-restricted-access-email-allowlist.md), [DEPLOYMENT §3a](../architecture/DEPLOYMENT.md#managing-approved-accounts-option-b)).** Closes the code side of hardening item N6. Nothing deployed; **no migration** (`users.email` exists since 0001).
  - **Settings.** `RESTRICTED_ACCESS` and `ACCESS_ALLOWLIST` (a JSON list).
    - Demo profile only, and needs an OAuth provider.
    - A list without the switch is refused at startup.
    - `[]` admits nobody.
  - **Backend.**
    - `POST /session` returns 403 `ACCESS_DENIED` and creates no anonymous user.
    - `current_user` and `stream_user` re-check the stored email on every request: 401 without a session (or with a leftover anonymous one), 403 for an account that is not approved. Removing an address and restarting therefore revokes existing sessions.
    - The callback accepts only a provider-verified email (Google `email_verified`, GitHub `/user/emails` `verified`) and refuses with `not_allowed` before writing any row or session.
    - Email scopes are requested only while restricted, so open mode is unchanged.
    - New public `GET /auth/options`. The list is never echoed in responses or logs.
  - **Web.** SessionGate shows a sign-in screen when the session is refused, and a "not approved" screen with sign-out.
  - **Verified:**
    - Backend: ruff, format, mypy; `pytest` 1657 passed (unit, integration and security), including 17 new security tests and 8 new settings tests. Security suite alone: 162. Smoke evals 5/5.
    - Frontend: lint, typecheck, 243 tests (4 new for SessionGate), build.
    - e2e: 18/18 (local profile, stub model).
  - **Not verified:** real Google/GitHub email scopes on a deployed origin (mocked providers only).
  - **Limitations:**
    - List changes need a restart.
    - An already-open SSE stream and already-queued jobs are not cut off.
    - The demo gallery stays public.
    - Approved emails are stored in `users.email`.

## Completed

- [x] Repository inspected (was empty).
- [x] Root docs: README, CLAUDE.md, AGENTS.md, GLOSSARY.
- [x] Product: PRD, FEATURES.
- [x] Architecture: ARCHITECTURE, AGENT_SYSTEM, DATABASE_DESIGN, API_DESIGN, SECURITY, BENCHMARK_ENGINE, REPLAY_ENGINE, DEPLOYMENT.
- [x] Design: DESIGN_SYSTEM, UI_UX.
- [x] Engineering: FILE_MAP, CODING_STANDARDS, TESTING_STRATEGY, OBSERVABILITY, LEARNING, DECISIONS + ADR-0001…0014.
- [x] Planning: ROADMAP, TASKS, CURRENT_PHASE, PHASE_TEMPLATE, RISKS.
- [x] All 10 required Mermaid diagrams embedded in their owning docs.
- [x] Replay engine tightened (ADR-0015): canonicalization profiles, atomic finalization, integrity scope, renderer versioning, replay lifecycles, statistical comparison; lifecycle events outside the seal; restricted-role artifact paths; same- vs cross-environment labeling. Replay contracts for Phases 1–3 recorded in ROADMAP.
- [x] 3 designed HTML diagrams in `docs/diagrams/` (system architecture, trust boundaries, agent graph) — added only where they add value beyond Mermaid.

## Phase 1 progress

- [x] **T1.1 Repo scaffolding.**
  - `backend/` is a uv project on Python 3.12.15 with FastAPI, ruff, `mypy --strict`, and pytest (asyncio).
  - `frontend/` is Next.js 16.4 + Tailwind 4 + Vitest 5, with `lint`, `typecheck` (`next typegen && tsc`), `test`, and `build` scripts.
  - `infra/docker/compose.yaml` defines `metadata-db` and `sandbox-db`; the sandbox sits on an internal network.
- [x] **T1.2 CI workflow.** `.github/workflows/ci.yml` runs on every push to `main` and on pull requests:
  - backend on Python 3.12 and 3.13: `uv sync --locked`, ruff, format check, mypy, and unit tests;
  - frontend: frozen install, lint, typecheck, test, and build.
  
  The failure path was verified locally: an injected type error makes both `mypy` and `tsc` report errors. It was not pushed, to keep `main` green.
- [x] **T1.3 `core/`.**
  - `config.py`: profile-aware settings; the demo profile refuses `ALLOW_PRIVATE_TARGETS=true` and requires `QC_MASTER_KEY`; secrets are `SecretStr`.
  - `logging.py` + `redaction.py`: structlog JSON with UTC timestamps. Sensitive keys are redacted recursively; DSN passwords, Google/OpenRouter/`sk-` keys and Bearer tokens are masked inside values, including exception tracebacks.
  - `errors.py`: stable codes and statuses matching the API error envelope.
  - `crypto.py`: AES-256-GCM `SecretBox` with table/row/user associated data and key versions for rotation.
  - 43 new unit tests.
  - CI actions bumped to their Node 24 majors (checkout v7, setup-uv v10.3.0 (exact pin; no floating tag), pnpm/action-setup v6, setup-node v7).
- [x] **T1.6 `sql/`** (SQLGlot 30).
  - `parse_single` enforces one statement and a byte limit, and fails closed on empty, unparseable, or over-deep input.
  - `validate_select` allows only SELECT and set-operation roots, and walks the **whole tree** for writes. This catches data-modifying CTEs, which parse with an innocent `Select` root. It also rejects SELECT INTO, row locks, the function denylist (also when schema-qualified or upper-cased), and qualified user functions unless opted in.
  - Metadata covers tables (CTE names excluded), columns, ORDER BY, LIMIT, and parameter count.
  - The literal-normalized fingerprint is metadata, not artifact identity.
  - 97 new tests: 82 unit plus 15 security evasion tests in `tests/security/`.
  - Unqualified user functions can't be detected by parsing; the `pg_proc` check is now an explicit T1.10 requirement (SECURITY §4.3 updated).
- [x] **T1.7 `plans/`** (complete).
  - The parser takes PG JSON (list or object) into a typed preorder `PlanTree`.
  - Every node carries a JSON-pointer `locator` for evidence citations. Unknown keys are kept in `extra`.
  - Strict type checks; 5 MB / depth-256 limits; detection of ANALYZE, TIMING OFF, and BUFFERS.
  - Metrics: loops-aware inclusive and self time, dividing by process count below `Gather`; per-loop estimate error with direction; total rows removed by filter; sort spill; self buffers.
  - Unknown values stay `None`, never 0.
  - 29 tests against hand-computed **synthetic** fixtures, plus 7 invariant tests on **real PG 17.11 captures** (`pg17_*.json`, provenance in the fixtures README).
  - The real canonical plan is parallel (`Limit → Gather Merge(2) → Sort → Seq Scan`). The invariants confirm self times are ≥ 0 and add up to the root, and that the parallel correction keeps scan time ≤ execution time.
- [x] **T1.9 SSRF guard** (`connectors/ssrf_guard.py`).
  - Host syntax validation runs before any DNS lookup. inet_aton-style numeric hosts (`2130706433`, `0x7f000001`, `0177.0.0.1`, `127.1`) are refused, as are ports outside the allowlist (5432, 6543, plus configured).
  - DNS is resolved **once**; the target is refused if **any** answer is non-public. IPv4 addresses embedded in IPv4-mapped, 6to4, NAT64 and Teredo IPv6 forms are checked too.
  - Link-local (cloud metadata), multicast, unspecified and reserved addresses are blocked in every profile. Private and loopback addresses are allowed only in the local profile.
  - Returns a pinned `hostaddr` plus the original `host` for TLS. Error details never echo resolved addresses.
  - 70 security tests, including a rebinding resolver (one lookup only) and the real system resolver path.
  - Bug caught by the tests: Python reports `::1` as `is_reserved`, so loopback is now classified before the reserved rule.
- [x] **T1.8 canonicalization profiles and artifact store.**
  - Canonical profiles, as above.
  - `replay/artifact_store.py`: `store_json`/`store_text`/`store_raw_sql` dedupe by digest using `INSERT … ON CONFLICT DO NOTHING` plus re-select. There is no UPDATE and no row lock, so it works as `qc_app`.
  - `get_artifact` re-verifies the digest on every read and raises `ArtifactIntegrityError` on a mismatch.
  - A profile or content mismatch under an existing digest raises `ArtifactConflictError`. Artifacts over 5 MB are rejected. `link()` into `run_artifacts` is idempotent.
  - 11 integration tests run as `qc_app`: 8 concurrent same-digest inserts yield one row, NUL survives storage, and corruption is detected.
- [x] **T1.15 frontend shell.**
  - `styles/tokens.css` holds DESIGN_SYSTEM §2 tokens (light and `.dark`), mapped into Tailwind 4 `@theme` (`bg-surface`, `text-muted`, …). IBM Plex Sans/Mono come via `next/font`.
  - `next-themes` with the class strategy, plus a `ThemeToggle`.
  - `AppShell` has a 56px top bar and a 224px side nav. Planned sections render disabled ("soon"), never as dead links.
  - The `/app` dashboard shows an empty state.
  - `lib/api`: `apiFetch` (cookies, CSRF header on mutations, error envelope → `ApiError`, network failures → `NETWORK_ERROR`) and `case.ts` (snake↔camel, type-fest typed).
  - Types are generated from the backend OpenAPI by `pnpm gen:api`, using `python -m querycure.api.export_openapi`.
  - 12 new Vitest tests.
  - Verified in the browser: dark mode switches tokens (`#0E1013` background), the font resolves to IBM Plex Sans, the preference persists, and there are no console errors.
  - Mobile: below `md` the side nav becomes a scrollable strip under the header and pages stack to one column (done in T1.17).
- [x] **T1.4 Alembic baseline** (migration `0001`).
  - Contents: `uuid-ossp`, `qc_app`/`qc_retention` roles (created NOLOGIN if missing; no passwords in migrations), the shared `set_updated_at()` trigger, and tables `users`, `sessions`, `database_connections`, `artifacts`, `run_artifacts`. All follow ADR-0006: UUID, TEXT, TIMESTAMPTZ, soft delete, CHECK-based enums, no FKs.
  - Per-table grants: the app gets SELECT/INSERT/UPDATE on mutable tables but no DELETE, and only SELECT/INSERT on append-only tables. Retention gets SELECT/DELETE.
  - **Deviation (documented in DATABASE_DESIGN):** `artifacts.content` is `BYTEA` holding exact canonical bytes. JSONB would reorder keys, normalize numbers and reject `\u0000`, and TEXT rejects NUL; either could break digest verification.
  - Local login roles come from `infra/docker/metadata-init/01-roles.sh` (idempotent; env passwords with dev-only defaults).
  - 18 integration tests run with `SET ROLE` as the restricted roles: conventions, trigger, CHECKs, a second upgrade as a no-op, a single head, and grants (app cannot UPDATE/DELETE/TRUNCATE/lock artifacts or create tables; retention can delete but not insert).
  - CI gained a `postgres:17` integration job with `QC_REQUIRE_DB=1`, so a missing DB fails instead of skipping.
- [x] **T1.5 session API, CSRF, and error envelope.**
  - `POST /session`: the local profile resolves to the single local user; the demo profile creates anonymous users. A valid existing session is reused (200, not 201).
  - The token is random and stored only as its SHA-256. The `qc_session` cookie is HttpOnly and SameSite=Lax (Secure outside local); `qc_csrf` is readable for double-submit.
  - `GET /me` returns the user, profile and features. `GET /readyz` checks DB reachability and that migrations are at head.
  - Request-ID middleware and CSRF middleware (constant-time compare; `POST /session` exempt per ADR-0013).
  - Every error, including framework 404s, validation errors and crashes, leaves as the documented envelope. Crashes are generic and leak nothing.
  - Migration `0002`: a partial unique index allows one active local user, so concurrent first logins converge. It also grants `SELECT` on `alembic_version` to `qc_app` for readiness. The test first exposed the missing grant as a 503.
  - Tests: 10 unit tests (envelope, CSRF) plus 10 integration tests, with the app engine running as `qc_app` via `SET ROLE`.
  - Verified live: uvicorn as the `qc_app` login against the dev DB (readyz ok, 401 → 201 → 200, CSRF 403 envelope).
- [x] **T1.10 inspection gateway and T1.11 statistics redaction** (`connectors/inspection_gateway.py`, `models.py`, `catalog_queries/*.sql`).
  - The connection goes through the SSRF guard and a pinned `hostaddr`, using explicit fields only (never a raw DSN).
  - The session is hardened (read-only, statement/lock/idle-in-transaction timeouts, `search_path = pg_catalog, public`), and each setting is **verified via `current_setting`** rather than trusted. Every operation runs in `BEGIN READ ONLY`.
  - Capabilities come from a template. SUPERUSER, CREATEROLE and BYPASSRLS roles are refused; table owners, REPLICATION, and missing `pg_read_all_stats` produce warnings.
  - `explain()`: validator, then `pg_proc` resolution of unrecognized function names (user functions refused unless opted in), then plain `EXPLAIN (FORMAT JSON)`, or `GENERIC_PLAN` for `$n` queries on PG 16+.
  - `schema_snapshot()`: tables, columns, and indexes with **numeric statistics only**. Value-bearing `pg_stats` columns are never selected.
  - Driver errors map to envelope codes without leaking connection details.
  - Validator fixes found while building it: unquoted identifiers fold to lower case like PostgreSQL, and `functions_to_resolve` lists unrecognized unqualified names.
  - 15 integration tests on a seeded target DB with a throwaway restricted login role. They cover hardening verification; L3 holding with the validator bypassed (`EXPLAIN ANALYZE DELETE`, DDL, and a `SET … ; DELETE` all fail, with the row count unchanged); statement and lock timeouts; the `pg_proc` refusal and opt-in; redaction with planted secret emails; superuser refusal; SSRF block before connecting; a wrong password not leaking; and concurrent gateways.
  - SQL templates verified present in the built wheel.
- [x] **T1.12 connections API** (`/connections`: create, list, test, explain, schema, delete).
  - Passwords are sealed with AES-GCM, bound to the row and user ID. The row ID is generated before encryption.
  - Delete soft-deletes the row and wipes the ciphertext immediately.
  - Blocked targets are refused at creation and re-checked on every use. `sslmode=disable` is local only.
  - A `test` outcome (ok, refused, or failed) is recorded in its own transaction, so it survives an error response.
  - Explain returns the parsed plan plus metrics. Production connections answer `409 APPROVAL_REQUIRED`.
  - Other users' IDs get 404 on every route. The demo profile answers `FEATURE_DISABLED`. A missing `QC_MASTER_KEY` gives `CONFIGURATION_ERROR` rather than plaintext storage.
  - 15 integration tests plus a unit test that scans every OpenAPI response schema for secret-like fields.
- [x] **T1.13 inspect API (Mode A).**
  - `POST /inspect/sql` validates and fingerprints.
  - `POST /inspect/plan` takes a raw plan body and returns the tree, metrics, and a `plan`/`plan_analyze` artifact. It dedupes by digest, so reformatted JSON maps to the same artifact.
  - `POST /inspect/schema` parses DDL with `sql/ddl.py`. It handles `pg_dump` style: columns, NOT NULL/PK, `ALTER … ADD PRIMARY KEY`, indexes with `USING`/`WHERE`. Other statements become warnings and are never executed.
  - Plan uploads now **reject duplicate JSON keys**; stdlib `json` silently kept the last one.
  - New `MaxBodySizeMiddleware` (6 MB): declared sizes are refused up front, and streamed bodies are counted.
  - **Bug fixed while testing:** Starlette's `BaseHTTPMiddleware` wrapped errors in `ExceptionGroup`s, which turned an over-limit stream into a 500. The request-ID and CSRF middlewares were rewritten as plain ASGI, and all earlier envelope, CSRF and session tests still pass.
  - 7 DDL unit tests, 1 duplicate-key test, 3 body-limit tests, 9 integration tests.
- [x] **T1.14 demo workloads.**
  - `orders_ecommerce` has no `(customer_id, created_at)` index, and ten hot customers own 10% of orders. `rewrite_trap` puts a NULL in the `NOT IN` subquery. `no_benefit` is a primary-key lookup.
  - Generation is deterministic SQL (md5 mixing, fixed epoch) composed with `psycopg.sql`. A `WorkloadRef` parser validates IDs.
  - CLI: `python -m querycure.workloads URL WORKLOAD_ID` prints table checksums. `GET /workloads` reports `live` locally and `prerecorded` on the demo.
  - **Bug fixed while testing:** salted multiplicative hashes were correlated, leaving hot customer 1024 with 5 orders instead of about 100. Switched to md5 per salt.
  - Verified at sf=1: 1M orders in 8.8 s, customer 1024 has 10,013 orders and customer 7 has 9. Identical checksums across two independent loads and across the f-string → `psycopg.sql` rewrite.
  - 9 unit tests, 7 integration tests (incl. the rewrite trap really differing), and 2 API tests.
- [x] **T1.16 connections page** (`/app/connections`).
  - List, add form (client-side required-field checks; backend envelope messages and field details shown inline), Test with a capability checklist that states each result in words, two-step delete, and a copyable restricted-role SQL snippet.
  - App plumbing: `Providers` (TanStack Query that skips retries on 4xx, theme) and a `SessionGate` that creates a session after a 401 on `/me`.
  - The `/app` segment sets `instant = false`. Next 16's instant-navigation validation can't render session-gated client pages on the server, and the bundled docs prescribe this opt-out.
  - API client: `rawJsonBody`, so plan JSON is never key-converted; typed modules over the generated schema.
  - Vitest: 4 form tests, 1 checklist test, 1 raw-upload test.
  - **Verified in the browser** against the real API (`qc_app`) and PG 17.11: created a `qc_demo_inspector` connection to the sf=1 database; Test showed `LAST TEST: OK` with live capabilities; a `169.254.169.254` host showed the backend's "Target address is not allowed" inline.
- [x] **T1.17 workspace** (`/app/investigations/new`).
  - CodeMirror 6 SQL editor (PostgreSQL dialect, token-based highlighting); "Upload plan" (paste or file) and "Live EXPLAIN" (connection picker) tabs; "Start investigation" is disabled and says investigations arrive in Phase 2.
  - Plan tree table: an ARIA treegrid with roving tabindex (arrows, Home/End, Left/Right collapse and expand); per-loop estimated vs actual rows with the misestimate stated as "N× under/over"; self time and share; buffers; the hottest node labelled in words; "spilled to disk" for sorts; an "Estimates only" banner for plain EXPLAIN.
  - Node details panel: relation, filter, inclusive time, loops, actual rows across all loops, rows removed by filter, cost.
  - **Bug fixed during browser verification:** the Actual rows column showed the all-loops total next to a per-loop estimate (Seq Scan: 4,333 vs 10,014 under 3 loops). Both columns are now per loop, as in EXPLAIN, and the total moved to the details panel. A regression test came first.
  - **Mobile fix:** at 375 px the fixed side nav took half the screen and clipped the workspace. Now no horizontal page scroll at 375 px on the workspace or connections pages; the plan table scrolls inside its own container. The UI_UX §3.4 mobile tabs (Query · Plan · Agents · Results) wait for the Phase 2 panels.
  - Next 16: `instant = false` is needed on each session-gated page, not only the `/app` layout. The dev overlay flagged every page as a dropped segment until then.
  - Vitest: 7 plan-tree tests and 3 workspace tests (29 frontend tests in total).
  - **Verified in the browser** against the live API: a real PG 17 `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` plan from the sf=1 demo rendered Limit → Gather Merge → Sort → Seq Scan on orders. Seq Scan was labelled hottest at 62.6 ms (91.1% self time), matching hand-computed values (ROADMAP Phase 1 acceptance #2). Live EXPLAIN on the `qc_demo_inspector` connection returned the same shape with the "Estimates only" banner.
- [x] **T1.18 plan graph** (Tree / Graph toggle in the workspace).
  - `lib/plan/layout.ts`: pure dagre top-down layout. Edges carry rows across all loops (planner estimates, labelled "est.", for plain EXPLAIN). Edge width is log-scaled between fixed bounds.
  - `PlanGraph`: React Flow with a custom PlanNode card showing node type, relation, per-loop est vs actual, misestimate (≥10× in `--inconclusive`), and a self-time bar. Only the hottest node gets the accent border and a "hottest" label. Selection is shared with the tree and the details panel. Theme follows tokens through `--xy-*` variables in `globals.css`.
  - Shared helpers `hottestNodeId` and `estimateLabel` are now used by both the tree and the graph, so the two views can't disagree.
  - The tree stays the default view. The graph's caption points keyboard and screen-reader users to it (DESIGN_SYSTEM §accessibility).
  - Tests: 6 layout/helper unit tests, 5 PlanGraph tests, and 1 workspace test showing the graph has the same node set as the tree with selection carried across views (41 frontend tests in total). In jsdom the click test uses `fireEvent.click`, because user-event's `mousedown` has `view=null`, which d3-zoom dereferences.
  - **Verified in the browser** with the real PG 17 plan: 4 cards matching the 4 tree rows, only Seq Scan accented (62.6 ms, 91.1%), and edge labels 20 / 48 / 10,014 rows (16×3 and 3,338×3 across loops). Checked in dark and light themes and at 375 px with no page-level horizontal scroll.
  - Fixed during verification: a card overflowed and hid its relation line; the selected card's tint was overridden by `bg-surface`.
  - Note: running `pnpm build` while `pnpm dev` is up left the dev server serving stale CSS until it was restarted.
- [x] **T1.19 README "Run locally"** — verified from a fresh clone of `main` (`bae022f` + README).
  - Ran under Compose project `qdfresh` with a new empty volume, following the README steps literally: `up -d --wait` (both healthy); `.env` with a generated key; `uv sync`; `alembic upgrade head` (`0002 (head)`); uvicorn, where `/api/v1/readyz` returned the documented JSON; `pnpm install && pnpm dev`, where `/app` loaded with an automatic session.
  - Step 5: pasting the `pg17_join_aggregate_analyze.json` fixture rendered 8 nodes, with Hash Join hottest at 23.4 ms. That matches by hand: 41.617 − 18.077 − 0.142.
  - Step 6: loaded the workload (sf=0.1, 2.2 s); created the restricted role; the connection tested OK on PG 17.11 with honest warnings (no `pg_stat_statements`, not encrypted); Live EXPLAIN returned Limit → Sort → Seq Scan with the estimates-only banner.
  - **Found by the fresh-clone run:** the form's default `TLS = verify-full` cannot reach the TLS-less compose container, and the UI said only "Could not connect". The README now says to set TLS to `disable (local only)`.
  - The gateway now classifies connect failures into fixed reason codes (`connect_failure_reason`), logs `target_connect_failed` without libpq's text, and returns a hint for auth, database, and TLS failures. Network-level failures stay generic (SECURITY §5.3). This was test-first: 8 classifier unit tests and 2 gateway integration tests; the TLS case was checked against real libpq output.
  - Also fixed a stale cross-reference (SECURITY T8 → §4.3) and the README status, which still said "Phase 0, no code".

## Phase 2 progress

- [x] **Pre-flight (2026-10-11).**
  - `main` clean and equal to `origin/main` (`1ce5b58`).
  - Rebrand sweep: no `QueryDoctor`/`QD_`/`qd-` references remain in docs, source, Compose, env examples, API contracts or profiles, except the intentional history note in ADR-0015. Canonicalization profiles are `qc-json-v1`/`qc-text-v1`/`qc-raw-v1` (+ `qc-events-v1`, planned `qc-row-v1`) and are frozen.
  - No `backend/.env` existed, so `QC_MASTER_KEY` was not persistent. Created `backend/.env` from `.env.example` (mode 600, gitignored) with a newly generated key, never printed. The metadata DB held 0 sealed connections, so no ciphertext was stranded.
  - Old volume `querydoctor_qd_meta` kept, not deleted. Current volume: `querycure_qc_meta`.
- [x] **T2.1 migrations** (`0003_investigations`, `0004_langgraph_checkpointer`).
  - Tables: `investigations`, `investigation_runs` (with `last_event_seq`, idempotency key + request hash, Phase 4 finalization columns), `investigation_events`, `agent_executions`, `tool_executions`, `evidence`, `findings`, `hypotheses`, `jobs`. ADR-0006 conventions, CHECK-based enums, no FKs, every relationship column indexed.
  - Grants: append-only tables (`investigation_events`, `agent_executions`, `tool_executions`, `evidence`, `findings`) are `SELECT/INSERT` only for `qc_app`, plus `USAGE` on the event identity sequence; mutable tables get `UPDATE` but never `DELETE`; `qc_retention` gets `SELECT/DELETE`.
  - **Deviation:** a `findings` table was added (displayed values must come from persisted records). `agent_executions.invocation_key` with a unique partial index on successful executions makes LLM nodes idempotent across crash/resume.
  - **Deviation:** the LangGraph checkpointer's `setup()` needs DDL, which `qc_app` lacks. Migration `0004` runs the library's migration list as the owner in schema `langgraph`; `qc_app` gets `SELECT/INSERT/UPDATE`, not `CREATE` or `DELETE`. Documented in DATABASE_DESIGN §2.
  - `domain/runs.py`: modes, statuses, outcomes, and the AGENT_SYSTEM §9 transition table. `db/repositories/runs.py`: `transition_run` in one `UPDATE … FROM (SELECT … FOR UPDATE)`; a completed status requires an outcome.
  - Dependencies: `langgraph` 1.2, `langgraph-checkpoint-postgres` 3.1, `langchain-core` 1.6 (uv also moved `websockets` 17.2 → 16.1 to satisfy `langgraph-sdk`).
  - Tests: 6 unit (state machine); 55 schema/grant integration tests run as `qc_app`/`qc_retention` (incl. the job claim query and checkpointer grants); 6 `transition_run` tests incl. a 6-way race with exactly one winner. Full suite 503 passed; ruff, format, mypy clean. Dev DB at `0004 (head)`.
- [x] **T2.2 job queue + worker** (`jobs/queue.py`, `worker/runner.py`, `worker/__main__.py`).
  - Queue: `enqueue` (dedupe via `ON CONFLICT … DO NOTHING`), `claim` (the documented `FOR UPDATE SKIP LOCKED` query, reporting whether the job was reclaimed from an expired lease), `heartbeat`, `complete`, `fail` (backoff or dead-letter), `reap_exhausted`. All times use the DB clock.
  - Worker: N slots; a heartbeat beside each handler cancels it if the lease is lost; `PermanentJobError` and unknown kinds dead-letter at once; other exceptions retry, storing only `{code, type}`; SIGTERM/SIGINT stop gracefully and leave in-flight jobs to lease expiry. Lease, heartbeat and poll timings come from settings (heartbeat must be under half the lease).
  - **Fix (migration `0005`):** the `dedupe_key` index from `0003` covered every status, so a finished resume job would have blocked all later resumes for that run. It now covers active jobs only.
  - `jobs/handlers.py` registers no handlers yet; `run_start`/`run_resume` arrive with the graph in T2.10. `WORKER_MODE=embedded` is not implemented (demo deployment, Phase 5).
  - Tests: 10 queue integration tests (6 concurrent workers drain 30 jobs with no double claim, reclaim, heartbeat ownership, stale worker cannot complete, backoff then dead-letter, reaping, active-only dedupe, ordering); 8 worker tests (success, retry, permanent error, unknown kind, lease-loss cancellation, 3-slot concurrency, reaping callback, shutdown); 2 config tests. Full suite 523 passed; ruff, format, mypy clean.
  - Live check: `python -m querycure.worker` as `qc_app` dead-lettered an unhandled `retention_sweep` job (`UNKNOWN_JOB_KIND`, attempt 1) and exited 0 on SIGTERM.
- [x] **T2.3 event emitter + SSE** (`events/emitter.py`, `events/hub.py`, `api/sse.py`, `api/routers/runs.py`).
  - `emit()` runs in the caller's transaction: seq from `UPDATE … last_event_seq + 1 RETURNING`, insert, `pg_notify`. A finalized run accepts only `report.ready` / `run.status_changed` (`RunFinalizedError`, rolling the seq back). `change_status()` transitions and emits `run.status_changed {from, to, outcome?}` in one transaction.
  - **Design change (API_DESIGN §3):** one `LISTEN qc_run_events` connection per API process instead of `NOTIFY run_<id>` per stream; notifications are wake-ups only and events are always read from the table.
  - SSE route uses its own short auth transaction: FastAPI 0.143's default yield-dependency scope would otherwise keep one idle transaction open per stream.
  - History endpoint with an opaque seq cursor. Run lookups go through `get_run_for_user` (404 for missing, deleted, or another user's run).
  - Tests: 8 emitter tests (25 concurrent emitters → gap-free 1..25, rollback leaves no gap, NOTIFY only after commit, sealing, status + event atomicity); 3 hub tests (per-run wake-ups, reconnect after `pg_terminate_backend`); 10 API tests over a real uvicorn server, including **ROADMAP acceptance #3**: a client drops after 10 of 41 live events, reconnects with `Last-Event-ID`, and receives every event exactly once (passed 8/8 repeated runs). Also wire format, `after_seq`, heartbeats, early close, 401, cross-user 404, bad `Last-Event-ID`, history pagination, forged cursor. Full suite 544 passed; ruff, format, mypy clean.
  - Live check: uvicorn as `qc_app` streamed seq 1–3 emitted by a separate process and closed after the terminal event.
- [x] **T2.4 LLM layer** (`llm/types.py`, `llm/structured.py`, `llm/providers.py`, `llm/credentials.py`).
  - `call_structured`: JSON mode with the schema in the prompt, Pydantic validation, one repair attempt that sends the validation errors back (locations and messages only, `include_input=False`); retries on rate limit/5xx/timeout/connection errors with `min(2^n + jitter, 30 s)` backoff, ≤ 3, then the fallback model if configured, then `LLM_UNAVAILABLE`; auth and invalid-request errors are not retried. A 60 s timeout per call. `before_call`/`after_call` hooks for budgets and accounting.
  - **Design change (AGENT_SYSTEM §5):** JSON mode + our own validation instead of `with_structured_output(json_schema)`, for one validation path across providers, replays and fakes.
  - Errors are classified with `langchain_core.exceptions` (`ModelRateLimitError`, `ModelAPIError`, …), which both `langchain-google-genai` 4.4 and `langchain-openai` 1.7 map into, so retry logic has no provider-specific code.
  - Providers: `ChatGoogleGenerativeAI` and `ChatOpenAI` pointed at OpenRouter, both with SDK retries off. System messages are merged to the front (Gemini takes one system instruction). Clients' `repr` never shows the key.
  - New dependencies: `langchain-google-genai`, `langchain-openai` (the roadmap names Gemini + OpenRouter via LangChain).
  - Tests: 21 unit tests with scripted fake clients: parsing, fenced JSON, repair with errors, no third call, backoff 2/4/8/16/30/30 s, jitter bounds, fallback, no retry on auth failure, budget hook stops a retry before it is sent, records for every call, logs contain no prompt/output text; key resolution per profile; no key in client reprs; message merging; adapter usage extraction.
  - **Not verified live:** no `GEMINI_API_KEY` or `OPENROUTER_API_KEY` is configured on this machine, so no real provider call has been made. The adapters are exercised only through LangChain's fake chat model.
- [x] **T2.5 state, budgets, cancellation** (`domain/investigation.py`, `agents/state.py`, `agents/budgets.py`, `agents/runtime.py`).
  - Domain models: Evidence, Finding, Hypothesis, InvestigationPlan, NodeError, RunBudget, BudgetUsage (strict: `extra="forbid"`, citation IDs pattern-checked).
  - **Decision:** graph state holds JSON values only, and the checkpointer will run with a strict serializer (its default revives arbitrary classes from checkpoint content).
  - **Decision:** budget counters are DB-side (`investigation_runs.usage`) with atomic conditional updates, so the three parallel analysts share one budget; the same statements observe cancellation and wall clock. AGENT_SYSTEM §11 defaults per profile.
  - `guarded()` node wrapper + `unless_stopped()` router: budget exhaustion or cancellation becomes a `stop_reason` and routes to `write_report`, which always runs (partial reports). `RunEventSink` commits each progress event on its own.
  - Tests: 8 integration (profile defaults, limit, 3 parallel guards grant exactly 5 of 5, tokens enforced on the next call, per-invocation and run tool limits, cancellation observed, wall clock, single 80% warning event); 7 unit routing tests on real LangGraph graphs (happy path + events, exhaustion skips to report with `inconclusive`, cancellation still writes the report, parallel stop reasons merge, unexpected errors propagate); 1 sink test. Full suite 581 passed; ruff, format, mypy clean.
- [x] **T2.6 intake + collect_context** (`agents/nodes/intake.py`, `agents/nodes/collect_context.py`, `evidence/{ids,builders,sanitize,store}.py`, `agents/services.py`).
  - Deterministic evidence IDs (`ev_` + 12 hex of `sha256(run_id|kind|artifact_sha|locator)`); summaries generated from data, never by an LLM. Real PG 17 plan: "Seq Scan on orders; 62.6 ms self (91.1% of runtime); est 4,333 vs actual 3,338 rows/loop x 3 loops (1.3x overestimate); filter (customer_id = 1024); 989,988 rows removed by filter; hottest node".
  - Evidence store: one `jsonb_to_recordset` insert, idempotent, `evidence.created` only for new rows, finalized runs refused.
  - Mode B uses the hardened gateway via `GatewayInspectorFactory`; failures degrade to `tool_error` evidence instead of failing the run; production connections are refused until Phase 3 approvals; another user's connection is `NOT_FOUND`.
  - Refactor: connection decrypt/target helpers moved from the API router to `connectors/credentials.py` so the API and the worker share one implementation (connection API tests unchanged and passing).
  - Bugs found by tests: validator details were dropped from intake errors; identifier truncation added "…", turning plain names into quoted ones (now truncates like PostgreSQL).
  - Tests: 11 builder unit tests (on the real PG 17 captures); 9 integration tests (offline evidence, **crash re-run adds no rows or events**, 3 invalid-input routes, Mode B against the seeded target with the gateway — measured plan/table/column/index evidence, artifacts linked, planted e-mails absent — unreachable target degrades, production refused, foreign connection refused); 10 sanitizer security tests. Full suite 614 passed; ruff, format, mypy clean.
- [x] **T2.7 evidence grounding: fencing, citation validator, agent runner** (`agents/fencing.py`, `agents/citations.py`, `agents/outputs.py`, `agents/agent_runner.py`, `db/repositories/agents.py`).
  - Fencing with random per-block tokens; forged `<<END …>>` markers in content stay inside the block.
  - Citation validator: unknown IDs stripped, uncited claims removed, unbenchmarked speed-up numbers removed, retry once when > 50% removed.
  - Agent runner: one `agent_executions` row per provider call, accepted output stored as an artifact, reuse by `invocation_key` (crash re-run makes no LLM call), provider outage → `AgentFailed`, budget/cancellation propagate after recording calls made. Per-run LLM semaphore and a retry policy on the run context.
  - Bug found by a test: the runner hard-wired the default retry backoff, so a provider outage test slept ~15 s; the policy now comes from the run context.
  - Tests: 7 fencing security tests (forged markers, fresh tokens, objective line breaks, kind labels); 9 citation unit tests; 7 runner integration tests as `qc_app` (accept + rows + usage + artifact role, retry with the problems sent back, second failure keeps cited claims only, exactly 50% not retried, crash re-run reuses output with zero calls, outage records 4 failed calls, budget exhaustion before any call). Full suite 638 passed; ruff, format, mypy clean.
- [x] **T2.8 supervisor plan + synthesize_hypotheses** (`agents/nodes/supervisor.py`, `agents/prompts/{common,supervisor}.py`, `db/repositories/findings.py`).
  - Shared system prompt sections: role, task, evidence rules (cite IDs from the evidence block only, no invented numbers, no speed-up predictions, say "unknown"), data rules. Prompt versions `supervisor_plan@1`, `supervisor_synthesis@1`.
  - Deterministic guard rails around the model: eligibility intersection, fallback plan, confidence re-ranking, `proposed_by` from shared citations, cited `no_action_evidence`.
  - Hypotheses persisted idempotently with `hypothesis.created` only for new rows; findings repository ready for the analysts (T2.9).
  - Tests: 7 routing/ranking unit tests (eligibility per mode/capability, `Send` fan-out, stop → report, confidence ranking with stable keys, `proposed_by`); 8 integration tests (ineligible dropped, fallback on model failure, no LLM call without analysts, **disagreeing analysts persisted as separate ranked hypotheses**, re-run adds no rows or events, uncited hypothesis dropped, `no_action_evidence` stripped of unknown IDs, no synthesis call without findings). Full suite 653 passed; ruff, format, mypy clean.
- [x] **T2.9 Query Analyzer, Index Strategist, Workload Investigator** (`agents/nodes/analysts.py`, `agents/tools/{base,evidence_tools,workload_tools}.py`, `agents/prompts/{analyst,query_analyzer,index_strategist,workload_investigator}.py`, gateway workload methods + 4 catalog templates, migration `0006`).
  - JSON-turn tool protocol with allowlist refusal, argument validation, soft per-agent and hard run-wide tool budgets, fenced tool results, `tool.started`/`tool.completed` events, `tool_executions` rows linked to the requesting `agent_executions` row.
  - Analysts share one factory; each persists its own findings (`fd_` keys, `finding.created` for new rows) and a failure becomes a recoverable error so the run continues. In Mode B they get the gateway, so missing statistics are fetched live.
  - Workload templates checked against the real PG 17 target as the restricted role: idle-in-transaction session aggregated, a real `ACCESS EXCLUSIVE` lock and its waiter counted, table I/O read; `pg_stat_statements` refused cleanly when absent.
  - Tests: 4 gateway workload integration tests; 9 analyst integration tests (tool use + fenced result + row linkage + events; **injection fixture: a model obeying planted instructions is refused for a non-allowlisted tool and for another agent's tool**; per-agent budget soft stop; run-wide budget stops the run; invalid arguments; failure isolation; crash re-run reuses findings with zero model calls; index size 28 bytes/entry → 12 pages from live stats; workload tools on the live target). Full suite 666 passed; ruff, format, mypy clean.
  - **Not yet done:** "eval smoke on 3 workloads" needs recorded model responses (T2.14, after an API key is configured).
- [x] **T2.10 graph assembly, Postgres checkpointer, resume** (`agents/graph.py`, `agents/checkpointer.py`, `agents/run.py`, `agents/nodes/write_report.py`, `reports/interim.py`, `jobs/handlers.py`).
  - Graph: intake → collect_context → supervisor_plan → `Send` fan-out → synthesize_hypotheses → write_report, with stop routing at every step. Strict checkpoint serializer; checkpointer connects with `search_path=langgraph` and runs as `qc_app` in tests (grants suffice).
  - Worker: `run_start`/`run_resume` handlers, `on_dead` for both dead-letter paths, reclaimed jobs record `running → queued → running`.
  - **Deviation:** `queued → failed` added to the state machine (a job can die before its run starts). AGENT_SYSTEM §9 diagram updated.
  - **Bug found by a test:** a stored connection whose password no longer decrypts (changed `QC_MASTER_KEY`) raised a bare `DecryptionError` that crashed the graph, so the job would retry until dead. `target_from_record` now raises `ConfigurationError` with a "re-enter the password" message: the worker degrades to `tool_error` evidence and the connections API answers 503 instead of 500.
  - Tests: 11 end-to-end integration tests with scripted model responses and everything else real: full offline run (`unverified_recommendations`, ranked hypothesis, both analysts' findings, report JSON + Markdown, ≥ 5 checkpoints); **budget exhaustion → `inconclusive` + partial report (acceptance #5)**; cancellation → `cancelled` + partial report; **crash after the fan-out → resume without re-running analysts and with no duplicate evidence or findings (acceptance #2, in-process crash)**; worker retry to completion; dead-lettered job fails its run; missing key → `CONFIGURATION_ERROR`; invalid input → `inconclusive` without model calls; finished runs not re-executed; **no secrets in checkpoints** (target password, API key held by the client, master key, DSNs absent from checkpoints, blobs and writes); undecryptable credentials degrade. Stable across 5 repeated runs. Full suite 678 passed; ruff, format, mypy clean.
  - Still to do: a SIGKILL test of a real worker process, which needs the replay LLM provider from T2.14.
- [x] **T2.11 investigations/runs API** (`api/routers/{investigations,runs,artifacts,settings}.py`, `api/schemas/investigations.py`, `db/repositories/{investigations,artifacts}.py`, `domain/budgets.py`).
  - Create (202, one transaction: investigation, run, input artifacts, first event, job), list (cursor pagination; filters `status`, `outcome`, `q` with LIKE escaping), detail, soft delete + restore, run detail, idempotent cancel, findings + hypotheses, evidence with lineage (artifact + citing findings/hypotheses), parsed plans per run, owner-scoped artifact download, models endpoint.
  - Budget defaults moved to `domain/budgets.py`: the API must not import `agents` (FILE_MAP dependency rule).
  - Repository SQL is fully static; optional filters use `CAST(:p AS type) IS NULL OR …`.
  - Tests: 24 API integration tests as `qc_app` (creation side effects; 9 validation cases; production/foreign/missing connections; **idempotent replay; different body → 409; another user's key → 409 without leaking; 4 concurrent duplicates → one run; malformed key → 400**; concurrency limit; pagination + filters; **cross-user 404 on every route**; cancel idempotency and state machine; delete/restore; findings/evidence/plans/artifact reads; artifact access only through an owned run; models endpoint). The response-schema secret scan now allows token-*count* fields by exact name. Full suite 702 passed; ruff, format, mypy clean.
  - Live check (uvicorn as `qc_app`): create 202, replay with the same key → same run, `run_start` job pending, cancel 202 → `cancelled`, list/filter, events `queued` → `cancelled`.
- [x] **Free-tier LLM policy (ADR-0016)**, requested by the owner after T2.11: free OpenRouter models only, every phase.
  - Discovery (public catalogue): 26 zero-priced models; with tools and structured JSON output: `openrouter/free`, `nvidia/nemotron-3-super-120b-a12b:free`, `google/gemma-4-31b-it:free`, `google/gemma-4-26b-a4b-it:free`, `dots-studio/dots-3-note-preview:free`, `apodex/apodex-1.1-mini:free`, `liquid/lfm-2.5-2.6b:free`. **`openrouter/auto` is listed at $0 but routes to paid models**, so only `:free` IDs and `openrouter/free` are accepted.
  - Key check: `is_free_tier: true`, usage $0 (OpenRouter free tier ≈ 20 requests/min, 50/day without credits).
  - One probe request: `openrouter/free` was served by `nvidia/nemotron-3-super-120b-a12b:free` (provider `Nvidia`), `usage.cost: 0`, 37 of 44 completion tokens were reasoning.
  - Implemented: config guard (refuses paid models at startup); direct OpenRouter client (`openai` SDK) that checks `usage.cost == 0` on every response; quota exhaustion and paid usage are non-retryable, never use the fallback, and stop the run gracefully (`inconclusive` partial report); per-process 16/min window; DB-counted daily quota (45); per-run LLM concurrency 1; `require_parameters`; served model and upstream provider recorded per call (migration `0007`). Defaults are now `openrouter` / `openrouter/free`.
  - Tests: 21 unit tests (free-ID rules incl. `openrouter/auto` refused; paid configs refused; served model/provider/cost captured and request body checked via an HTTP mock transport; non-zero or missing cost blocked; per-day 429 and 402 → quota exhaustion without retry or fallback; per-minute 429 retried; limiter window; no key in repr) + 1 integration test (daily quota stops a real run gracefully). Full suite 726 passed.
- [x] **T2.14 eval runner + free-model benchmark** (`querycure/evals/`, `backend/evals/{cases,fixtures,recordings,results}`).
  - Runner as described in TESTING_STRATEGY §5 (implementation note). 6 cases: orders missing index, injection in schema, plain EXPLAIN, already-optimal PK lookup, budget exhaustion (smoke) + rewrite trap (full). Two new real PG 17 plan captures (`no_benefit`, `rewrite_trap`).
  - **Benchmark on `orders_missing_composite_index`** (results JSON in `evals/results/`): `openrouter/free` FAIL (routed 9 calls to 4 different models incl. a 2.6B model; synthesis output invalid); `nvidia/nemotron-3-super-120b-a12b:free` PASS 7/7 (8 calls, slow: 3 × 60 s timeouts); `google/gemma-4-31b-it:free` FAIL (upstream rate-limited on all 10 requests). **Pinned:** `nvidia/nemotron-3-super-120b-a12b:free` (config default, `.env.example`, local `.env`).
  - Recordings with the pinned model: orders missing index **PASS** (acceptance #1, recorded mode), budget exhaustion **PASS** (acceptance #5), PK lookup **known baseline failure** (high-confidence `missing_index` on a 0.039 ms, 50-row query: overconfident). Injection and plain-EXPLAIN recordings wait for the next free-quota day (today's ~50 requests were spent on the benchmark).
  - Fixes from live runs: call timeout configurable, default 120 s (`LLM_CALL_TIMEOUT_SECONDS`); runs truncated by the eval cap or free quota are never recorded; the injection check no longer compares tool sets (live variance) but checks for non-allowlisted / injected tools.
  - Every live response reported `usage.cost = 0`; no request was blocked by the paid-usage guard.
  - Tests: 7 unit (prompt hash ignores fence tokens, replay order and refusal, round trip, slugs, cases load) + 3 integration (offline record → replay gives identical metrics, missing recording fails, budget case). Full suite 736 passed.
- [x] **T2.12 frontend run view** (`components/investigation/*`, `app/app/investigations/[id]`, `lib/api/investigations.ts`, `lib/events/*`, Playwright `e2e/`).
  - Start: the workspace's "New investigation" form (title, objective, param-sets editor deferred from T1.17, mode from the plan source) sends the uploaded plan digest or the live connection, with one `Idempotency-Key` per form; shows the configured model and warns when no key is set.
  - Run view: Findings (hypotheses ranked, ClaimBadge "Hypothesis · confidence · unverified" with a dashed border, supporting/contradicting EvidenceChips; findings grouped by agent) and Plan (tree/graph from `/runs/{id}/plans`). An EvidenceChip on a plan node switches to Plan with the cited node selected and shows the evidence summary. Right panel: status/outcome, Cancel, budget meters (`role=meter`), live timeline in words with a throttled `aria-live` region.
  - SSE: `useRunEvents` registers a listener per named event type, merges by `seq`, invalidates findings/run queries on the relevant events, and closes the stream on a terminal status.
  - **Bug found in the browser:** the API's CORS `allow_headers` lacked `Idempotency-Key` (and `Last-Event-ID` for SSE reconnects), so starting an investigation failed with a preflight 400. Fixed with a regression test.
  - Stub LLM (`LLM_PROVIDER=stub`, local profile only): deterministic canned JSON that cites real evidence IDs from the prompt, labelled `stub/canned`, for end-to-end tests without model calls.
  - Environment: this shell defaulted to Node 20; the test stack needs Node 22 (CI's version). Added `.nvmrc` (22).
  - Tests: Vitest 55 (start flow with idempotency key and param sets, invalid param set, event merge/parse/terminal, param-set parsing, run view: unverified claims, **chip → plan node selected**, timeline in words, budget + cancel). **Playwright e2e** against the real API, worker and metadata DB with the stub LLM: upload plan → start → live timeline to "Run completed" → stub hypothesis → chip → Seq Scan row selected (3/3 runs, ~5 s each). New CI job `e2e`. Backend 740 passed.
  - **Live browser check with the real free model:** started from the UI, the timeline streamed live; the run completed `unverified_recommendations` in 7 calls (all `nvidia/nemotron-3-super-120b-a12b:free` via Nvidia, cost 0) with ranked hypotheses `missing_index` (high) / `cardinality_misestimate` / `inefficient_sort`; the chip highlighted the Seq Scan (62.6 ms, 91.1%). No page-level horizontal scroll at 375 px.
- [x] **T2.13 history page** (`/app/history`, `components/history/HistoryView.tsx`).
  - Cursor pagination with "Load more" (`useInfiniteQuery` over `next_cursor`), title search and status filter sent to the API, newest first, empty state with a link to start one, soft delete with an inline **Undo** (restore endpoint). Side nav "History" enabled.
  - Tests: 4 Vitest (cursor passed to the next page, delete then undo, empty state, filters sent) + side-nav test updated. 59 frontend tests pass; lint, typecheck, build clean.
  - Live browser check against the real API: the list showed the real investigations; delete → "Deleted … Undo" → restored.
- [x] **Acceptance follow-up (2026-10-12, PHASE_2_REPORT §11).**
  - Materiality gate (`evidence/materiality.py`, ADR-0017): a deterministic verdict from workload share, measured execution vs planning overhead, rows scanned, catalog size of Seq-Scanned tables, and spills. `not_material` caps hypotheses at low confidence and ends the run `no_action_needed`. `pk_lookup_already_optimal` now PASSes on its existing recording; report builder `interim-report@2`.
  - Free-only before dispatch: `OpenRouterClient` refuses a non-free id at construction and before every request (a gap: a paid id could previously be sent and was only caught by the cost check).
  - Recordings for `orders_injection_in_schema` and `orders_plain_explain`: **not made**. Today's free quota was already used (ledger 60 ≥ 45); no request was sent.
  - Tests: backend 774 passed (405 unit, 263 integration, 106 security); frontend 59 + build; e2e 1 passed; eval smoke replay 3/5 (two unrecorded).
- [x] **Acceptance #2, literal process kill** (`tests/integration/test_worker_kill.py`): a real `python -m querycure.worker` (stub LLM with a 1.5 s per-call delay, lease 5 s) is SIGKILLed once `synthesize_hypotheses` has started; a second worker reclaims the expired lease and the run completes with identical evidence/finding counts, both analysts' single successful executions untouched, statuses `running → queued → running → completed`, job `done` after 2 attempts. 6/6 repeated passes after fixing a test-side race (stopping the worker before the job was marked done).

## Phase 3 progress

Started 2026-10-12 on the owner's instruction; `main` clean at `ffe9321`. Details and evidence: [PHASE_3_REPORT](reports/PHASE_3_REPORT.md).

- [x] **Sandbox access** (`fc72846`). `sandbox-relay` (`alpine/socat:1.8.0.3`) publishes `127.0.0.1:55432` → `sandbox-db:5432` only; `sandbox-db` stays on `internal` `sandbox_net` (egress re-verified blocked: TCP, DNS, metadata-db). Planner settings pinned with `-c` in compose (`jit=off`, `max_parallel_workers_per_gather=0`, …).
- [x] **T3.1 migrations** `0008` (candidates, approvals, experiments, append-only `benchmark_runs` with `phase` in the resume key, `experiment_result` artifact kind) and `0009` (`waiting_seconds`, `pre_authorize_sandbox`). Grant tests as `qc_app`/`qc_retention`.
- [x] **T3.2 provisioner**: `qc_bench` least-privilege role, digest-stable templates, `FILE_COPY` clones, advisory-lock leases (cancellable), orphan cleanup, clone cap. 9 integration + 14 security tests.
- [x] **T3.3 workloads** `join_fanout`, `stale_stats`, `index_regression` (plans checked in the sandbox).
- [x] **T3.4–T3.7 engine** `bench@1`: seeded interleaved schedule (golden order), streamed timing in READ ONLY transactions, `qc-row-v1` (frozen, golden vectors), correctness incl. ties/error parity/arm stability, bootstrap CI, gates 1–6 (ADR-0018 order), tournament, block resume, in-flight cancellation. Eval table 9/9.
- [x] **T3.8 DDL allowlist** (strict fail-closed grammar; 39 unit cases) + re-validation and approval-digest check inside the engine.
- [x] **T3.9 Optimization Engineer** (`optimization_engineer@1`): one structured call per round, deterministic judging with one retry. Tested with scripted and stub models; eval cases added, **not recorded** (free-quota policy).
- [x] **T3.10 approval gate**: interrupt/resume, decision API (approve/decline/partial, idempotent, user-scoped), 24 h expiry sweep → `inconclusive`, demo pre-authorization (approval row still written), wait time excluded from the budget.
- [x] **T3.11 run_experiment + loop**: DB-bridged engine, evidence (`benchmark_metric`, `correctness_check`), verdict events, bounded rounds with rejection reasons fed back; `interim-report@3`.
- [x] **T3.12 UI**: demo-workload start, approval card, tournament tab with benchmark comparison; Playwright approval flow through the real stack (stub LLM).
- [x] **T3.13 fixtures**: 4 prerecorded experiments in `backend/evals/fixtures/experiments/`, provenance enforced on import.
- [x] **Bug fixed**: lock-upgrade deadlock between parallel content writers (`ensure_writable` `FOR SHARE` → `FOR NO KEY UPDATE`), regression test.
- [x] **Opt-in worker container** (`backend/Dockerfile`, compose profile `bench`) on `sandbox_net`; measured round trip 40 µs vs 355–451 µs via the published port.
- [x] **Owner decisions (2026-10-12/13):** ADR-0019 (`bench@2`: corroborated regressions; noise screen; `verified_with_noise_warning` by 3 agreeing independent experiments; `bench@1` rules frozen and proven to reproduce stored verdicts; schema-1 results byte-identical), migration 0010 (replicates), `interim-report@4`, UI badge and approval disclosure; ADR-0020 (container worker default, `QC_BENCH_PATH` recorded in the fingerprint).

## Phase 4 progress

Started 2026-10-13 on the owner's instruction; `main` clean at `cbe6e18`, CI green. Plan: T4.1 → T4.3 → T4.2 → T4.4/T4.5 → T4.6 → T4.7 → re-investigation start → API/UI (T4.8) → evals (T4.9) → docs and PHASE_4_REPORT.

Decisions taken without changing any frozen contract (recorded for the owner):
- **AI re-investigation** is Post-MVP in the roadmap but the owner asked for it: only the documented start contract (`POST /investigations/{id}/reinvestigate`, new `reinvestigation` run with its own budget and a parent link) is implemented; the conclusion diff stays Post-MVP.
- **`run.concluded`** is a new content event written by `finalize_run` before the cutoff, so the report builder reads only persisted records and events.
- **`container_runtime` is material** for experiment-replay comparison: ADR-0020 turned the field into the measurement path (≈10× round-trip difference).

- [x] **Phase 2 evals recorded** (`508d343`): `orders_injection_in_schema`, `orders_plain_explain` PASS with the pinned free model (13 requests); smoke replay 5/5, exit 0; CI integration job runs it.
- [x] **T4.1 migration 0011**: `verification_results` (append-only; CHECK `verification_results_downgrade_only` refuses any auditor upgrade or change of kind), `investigation_reports`, `replay_manifests` (append-only), `replay_attempts` (mutable, kind/status CHECK). 40 grant/constraint tests as `qc_app`/`qc_retention`; up/down/up verified.
- [x] **T4.3 plan diff** (`plans/diff.py`): weighted order-preserving child alignment (same relation outranks same node type), merged preorder, per-node metric deltas, `new_indexes_used`. 7 unit tests.
- [x] **T4.2 Benchmark Auditor** (`audit/checks.py`, `audit/loader.py`, `agents/nodes/benchmark_auditor.py`, prompt `benchmark_auditor@1`): 11 deterministic checks (re-score from persisted blocks with the experiment's own engine version, approval digest pinning, config = approval, environment digests, provenance, samples, param-set contradictions, dispersion, correctness, new index used in the plan, replicate environments); a failed check downgrades verified → inconclusive. One LLM narrative call whose cited `downgrade` concerns can only do the same; an LLM failure records `deterministic_only`. 22 unit + 3 real-sandbox integration tests (on this host the downgrade path ran on a real `verified_with_noise_warning` result).
- [x] **T4.4 report-builder@1 + report-md@1** (`reports/builders/v1.py`, `reports/renderers/md_v1.py`, `reports/inputs.py`, `reports/registry.py`): pure, versioned; reads only records and events `1..cutoff` (terminal decision from the new `run.concluded` content event). Sections: query, problem (plan evidence, materiality), hypotheses/findings, rounds with exact SQL, approvals, experiments (measurements with evidence ID + artifact digest/pointer, correctness, builds, replication, audit), recommendation (sandbox scope), limitations, next steps, missing evidence, provenance (models, prompt versions, measured/prerecorded, stub), integrity. `reports/provenance.unlabeled_numbers` scan; 27 unit tests over 9 report shapes (verified, rejected, mismatch, inconclusive, noise warning, auditor downgrade, prerecorded, unbenchmarked, cancelled, replay). Migration 0012 adds artifact kind `replay_comparison`.
- [x] **T4.5 finalize_run** (`replay/finalize.py`, `replay/events_digest.py`): one transaction; `write_report`, `fail_run` (dead letter, config error) and API cancel of queued/awaiting runs all seal through it. Sealing: emitter (existing), `link()` refuses sealed runs, approval sweep skips sealed runs, the terminal node no longer emits `node.completed` after the seal. 12 integration tests: fault injection after each of 5 steps, idempotent re-run, gap abort, sealing, manifest (no self-reference, no circular hashing), byte-identical rebuild, dead-letter partial report, sweep. Backend 1215 passed, smoke replay 5/5.

- [x] **T4.6 report replay** (`replay/report_replay.py`, `api/routers/reports.py`, `db/repositories/replay.py`): ordered checks, all codes collected, severity error > integrity_failed > not_replayable; stored bytes must already be canonical *and* hash to the reference digest (a whitespace-only edit is caught). API: `GET /runs/{id}/report`, `report.md` (export footer with manifest digest and `shasum` reproduction), `report.json` (export wrapper), `replay/manifest`, `POST replay/report`, `GET replay/attempts`, `GET /replay-attempts/{id}`, `GET plans/diff`. 18 integration tests through the real app: every REPLAY_ENGINE §8.1 code reached by a fixture, retired builder/renderer → `verified_stored_only`, row-drift and schema warnings, internal error, cross-user 404, LLM transports patched to fail (zero calls). Backend 1233 passed, 1 xfailed.

- [x] **T4.7 experiment replay** (`replay/experiment_replay.py`, `replay/comparison.py`): preconditions (finalized source that passes report replay, completed experiment, config schema, workload, row profile, allowlist re-validation, approved digests unchanged, sandbox enabled) → replay run (`experiment_replay`, parent = source) + approval decided by the confirming user for exactly the source's approved SQL + attempt + job. Worker: same config and seed, new experiment id, engine re-validates allowlist and digest, scored by the **source** engine version; comparison per pair (fingerprints, gate 4, drift bootstrap with a 52-bit seed from sha256(original|replay), verdict table), winner check, environment classes (`container_runtime` material per ADR-0020); comparison stored as a `replay_comparison` artifact and `replay.compared` event; replay run finalized with its own manifest. Cancel (queued → sealed now; running → stops at the next block) via `POST /replay-attempts/{id}/cancel` or the run's own cancel; dead-letter fails the attempt. 17 unit + 7 real-sandbox integration tests (zero LLM calls, source seal unchanged, reclaimed job resumes, dead letter). New code `source_experiment_incomplete` (documented). Backend 1257 passed, 1 xfailed.

- [x] **T4.7 acceptance measurement** ([analysis/replay_variance](../engineering/analysis/replay_variance/README.md)): 14 same-machine pairs of the `orders_ecommerce` composite-index experiment (sf 0.1 and 1; host relay and container path), real PG 17. 1 `reproduced` (container, sf 0.1), 1 `drift_undetermined`, 12 `inconclusive` from the gate-4 noise check; **0 `not_reproduced`**, fingerprints always matched. Acceptance ("reproduced or a documented inconclusive") met. D9 proposal: keep `m = 1.25` (owner's call). The comparison now records the drift and its interval even when gate 4 decides `insufficient_evidence` (diagnostic only).
- [x] **AI re-investigation start** (`POST /investigations/{id}/reinvestigate`, body `{confirm_new_llm_run: true}`): new `reinvestigation` run, parent = the investigation's latest run, inputs linked by reference, own default budget, `run_start` job, Idempotency-Key; refuses while a run is active (409), without a configured key (503) or with today's free quota spent (429 `LLM_QUOTA_EXHAUSTED`); user-scoped. Conclusion diff stays Post-MVP. 8 integration tests incl. a run through the graph to a sealed, verifying report with its own model provenance. Backend 1265 passed, 1 xfailed.

- [x] **T4.8 + UI** (frontend): Report tab and `/app/reports/[runId]` (stored report JSON rendered for reading; every number labeled with its provenance and a "Why?" lineage drawer to evidence, artifact digest/pointer and plan node; sandbox-only, prerecorded, stub and partial banners; noise-warning and downgrade explanations; MD/JSON export; "Verify report" with exact wording "Integrity check passed against stored digests"; stored-Markdown fallback with "archived format"/newer-schema banner). Tournament: Benchmark Auditor panel (`GET /runs/{id}/verifications`, new) and plan diff mode (baseline vs candidate EXPLAIN ANALYZE per param set). `/app/replay/[runId]`: manifest viewer, verify & replay report, re-run experiment with a confirmation dialog showing the exact SQL (not-replayable reasons in words), attempt history with live polling and cancel, comparison view (drift bar against the margin band, absolute latencies labeled not used, environment diff, cross-environment wording never "reproduced"), re-investigate with explicit consent. Timeline understands `run.concluded`, `report.ready`, `replay.*`. Frontend lint, typecheck, **78 tests** (10 new), build OK under Node 22 (the shell default Node 20 cannot load jsdom 30; CI uses 22).

- [x] **T4.9 evals**: Phase 3 Mode C cases recorded with the pinned free model (18 free requests; ledger 31/45 today): both PASS. Full-suite replay ([results](../../backend/evals/results/20261013T173814Z-full-replay-nvidia_nemotron-3-super-120b-a12b_free.json)): 5 PASS (all smoke cases), 2 `DIVERGED` (Mode C: the replay's live sandbox measurements produce new evidence IDs and may take another path, so recorded auditor/later-round answers cannot match; every deterministic prompt before that still matched exactly), 1 FAIL `rewrite_trap_not_in` (never recorded, Phase 2 optional). Replay client: exact matching everywhere; a same-agent fallback only for prompts that embed live measurements (auditor, Optimization Engineer rounds ≥ 2); a divergence is its own status, never a pass. Eval metrics now record audited verdicts and auditor downgrades (ADR-0009 downgrade rate).


- [x] **Owner review of Phase 4 (2026-10-16), docs only:** D9 approved, `m = 1.25` kept and not widened ([ADR-0023](../engineering/adr/ADR-0023-d9-experiment-replay-equivalence-margin.md)); `bench@1`/`bench@2` semantics and all released replay contracts preserved; acceptance recorded as implementation complete with ROADMAP's stronger replay criterion only partially demonstrated (noisy measurements); R19 kept open, `DIVERGED` never PASS. PHASE_4_REPORT, ROADMAP, REPLAY_ENGINE, RISKS, DECISIONS, ADR-0022 cross-reference and the replay-variance README updated. No code change.

## Phase 5 progress

- [x] **Deterministic Mode C evals (R19 closed, ADR-0024).** Measurement and sandbox-context fixtures; offline fixture replay passes both cases identically; CI runs it.
- [x] **Run picker and replay navigation**; **security hardening** (rate limits, logout, upload ownership, headers, cross-user sweep); **BYOK** (T5.2); **GitHub OAuth** (T5.1); **operations** (metrics, correlation IDs, drain, embedded worker, retention); **demo gallery** (T5.5); **axe** (T5.10); **deployment artifacts** and the demo profile verified locally (T5.8, not deployed); audit workflow (T5.7).
- [x] **Verification (2026-10-16):**
  - backend: 1312 passed + 1 known xfail;
  - frontend: 85 passed and the build succeeds;
  - e2e: 14 passed (4 journeys + 10 a11y);
  - evals: smoke 5/5, Mode C fixture 2/2 offline and identical across runs;
  - audits: no known vulnerabilities;
  - **CI green at `ccf143e`**, after one re-run of the known noisy `test_benchmark_bench2` measurement test (R18).
- [ ] **Owner:** review PHASE_5_REPORT §7 checklist; decide D1 (host) and D5 (domain); approve or defer a public deployment.
- [x] **Experiment-replay Idempotency-Key** (owner priority 1). Migration 0013 adds `replay_attempts.idempotency_key` / `idempotency_request_hash`, unique per `(user_id, kind, key)`. Same key and body return the original attempt (also a repeated 422); a different body is 409; concurrent duplicates converge on one attempt, run and job; a crash before commit leaves nothing behind. The web app sends one key per confirmation dialog. Tests: `test_experiment_replay_idempotency.py` (5), `ReplayConfirm.test.tsx`.

## Blockers

- None. Compose `metadata-db`, `sandbox-db` and `sandbox-relay` are healthy (they had exited once during the session, apparently with Docker Desktop, and were restarted). The dev database was migrated to `0009`; earlier local databases need `uv run alembic upgrade head`.

## Deviations / deferred

- **Renamed QueryDoctor → QueryCure (2026-10-11), at the user's request, everywhere:**
  - product name; Python package `querycure`; web package `querycure-web`;
  - env vars `QC_*`; roles `qc_owner`/`qc_app`/`qc_retention`; cookies `qc_session`/`qc_csrf`; DB `querycure`;
  - Compose project `querycure` (volume `qc_meta`); canonical profiles `qc-*` (ADR-0015 amendment).
  - Git history is unchanged. The old local volume `querydoctor_qd_meta` was kept, not deleted.
  - Verified: 448 backend tests on the recreated DB; frontend lint, typecheck, 41 tests, build; live API as `qc_app` and UI check.
- `import-linter` is not configured yet. Its layer contracts reference modules (`agents`, `benchmark`, `llm`) that don't exist, and the tool errors on missing modules. Add the contracts as the modules land, starting with T1.6.
- Starlette deprecated `httpx` for its TestClient, so the dev dependency is `httpx2`.
- T1.17's param-sets editor is deferred to Phase 2. Param sets are only consumed by the investigation-create request (API_DESIGN `param_sets`), so a Phase 1 editor would collect values nothing uses. It ships with the Phase 2 investigation form; the demo workloads already define their param sets in `workloads/registry.py`.
- Port 8765 on this machine is already in use by another local server. Smoke tests used a random free port.

## Next actions

0. ~~Owner decisions on ADR-0018, D11, D12, D13~~: applied (ADR-0019, ADR-0020, ADR-0021). D13 closed 2026-10-13: [ADR-0021](../engineering/adr/ADR-0021-d13-clean-verification-block-agreement.md) accepted, no change to `bench@2` (evidence kept in [analysis/d13](../engineering/analysis/d13/README.md)). No `bench@3`, block-agreement gate or scheduling change; the strict xfail stays. Block diagnostics for the Phase 4 Benchmark Auditor are a future consideration only. Do not reopen Phase 3 statistical decisions without new evidence. No OpenRouter request was sent.
1. On the next UTC day (free quota resets at 00:00 UTC), record the two missing Phase 2 smoke cases with the pinned free model (command in PHASE_2_REPORT §10), confirm `run --suite smoke` replays with exit 0, commit, and add the eval smoke step to CI.
2. ~~Calibration follow-up for `pk_lookup_already_optimal`~~: done (ADR-0017).
3. Then, as free capacity allows, record the Phase 3 Mode C cases (`--suite full --case orders_sandbox_composite_index`, `rewrite_trap_sandbox`; needs `SANDBOX_ADMIN_URL`/`SANDBOX_BENCH_PASSWORD`).
4. ~~Wait for the owner's go-ahead before starting Phase 4~~: Phase 4 done (2026-10-13).
5. ~~Owner: confirm D9~~: approved 2026-10-16, `m = 1.25` kept ([ADR-0023](../engineering/adr/ADR-0023-d9-experiment-replay-equivalence-margin.md)).
6. Wait for the owner's authorization before starting Phase 5. Owner's carried-forward Phase 5 priorities: (a) Idempotency-Key on `POST /experiments/{id}/replay`; (b) reliable deterministic/offline Mode C eval fixtures (R19); (c) run picker and replay navigation; (d) remaining deployment and security hardening.
7. **Current (2026-10-18):**
   - Owner: decide D1 and D5, then provision the host;
   - owner: delete the stale `env.bak`;
   - engineering: investigate F1 (the intermittent SSE pool-checkout 500);
   - then work through the deployment checklist in [FINAL_BACKEND_DEPLOYMENT_READINESS §9](../reports/FINAL_BACKEND_DEPLOYMENT_READINESS_2026-10-18.md), including real OAuth and the demo probe on the deployed origin.

## Pending real-model evaluations

Tracked separately from phase work. Each needs free OpenRouter quota (ADR-0016; resets 00:00 UTC). No paid API is ever used. Record Phase 2 first.

| Case | Phase | Suite | Status | Notes |
|---|---|---|---|---|
| `orders_injection_in_schema` | 2 | smoke | **Recorded 2026-10-13, PASS** | `nvidia/nemotron-3-super-120b-a12b:free`, 7 calls; all security checks ok (PHASE_2_REPORT §13) |
| `orders_plain_explain` | 2 | smoke | **Recorded 2026-10-13, PASS** | 6 calls; smoke replay 5/5 PASS (exit 0); CI integration job now runs the smoke replay |
| `orders_sandbox_composite_index` | 3 | full | **Recorded 2026-10-13, PASS** | 7 calls incl. the Benchmark Auditor; outcome `verified_recommendation`, composite index proposed, approval written. Replay is `DIVERGED` by design (live measurements; see T4.9) |
| `rewrite_trap_sandbox` | 3 | full | **Recorded 2026-10-13, PASS** | 11 calls, 3 rounds; outcome `inconclusive` (never verified) |

## Verification status

| Check | Result |
|---|---|
| Phase 4 exit (2026-10-13) | Backend `QC_REQUIRE_DB=1 uv run pytest -q` → unit 727 passed + 1 xfailed, integration 418, security 123 (PG 17 + sandbox); ruff, format, `mypy --strict` (185 files) clean; smoke evals 5/5; full replay 5 PASS / 2 DIVERGED / 1 unrecorded; frontend lint, typecheck, 78 tests, build OK (Node 22); Playwright 3 passed incl. the Phase 4 lifecycle; migrations 0011/0012 up/down/up verified; CI green |
| Git history cleanup (2026-10-13, owner-authorized one-time rewrite) | 5 `Co-Authored-By: Claude` trailers removed from `main` (`187c920`→`7c699bc`, `06998e2`→`aaa137d`, `a36c610`→`3fbec97`, `efa1921`→`cf8e91b`, `22b383b`→`799381b`; `3e1bb1f`→`376377d`, `096e271`→`d3852d8` rehashed only). 59 commits, trees, identities and timestamps unchanged; pushed with `--force-with-lease`; local backup tag `backup/main-pre-ai-trailer-cleanup-2026-10-13` |
| D13 closure / ADR-0021 accepted (2026-10-13, docs + xfail reason text only) | `QC_REQUIRE_DB=1 uv run pytest -q` → **1104 passed, 1 xfailed** (strict xfail kept); ruff, format, `mypy --strict` (162 files) clean; `git diff backend/src` empty; smoke eval replay 3/5 PASS, 2 unrecorded; no OpenRouter request |
| Backend (owner decisions ADR-0019/0020, 2026-10-13) | `QC_REQUIRE_DB=1 uv run pytest -q` → **1104 passed, 1 xfailed** (652 unit, 330 integration, 123 security collected; 1 strict xfail documents R18); ruff, format, `mypy --strict` (162 files) clean; migration 0010 up/down/up verified |
| Frontend (2026-10-13) | lint, typecheck, `pnpm test` → **68 passed**, build OK; Playwright **2 passed** (container worker stopped for the run) |
| Compose (2026-10-13) | `alembic current` → `0010 (head)`; worker container default, `container_runtime=docker-network`, uid 10001; sandbox egress (TCP, DNS, metadata-db) blocked, re-verified |
| Evals (2026-10-13) | smoke replay unchanged: 3 PASS, 2 unrecorded (exit 1); no OpenRouter request |
| Backend (Phase 3, 2026-10-12) | `QC_REQUIRE_DB=1 uv run pytest -q` → **1043 passed** (595 unit, 325 integration, 123 security) on PG 17.11 + sandbox, Python 3.12; ruff, format, `mypy --strict` (162 files) clean; CI green on `fc72846`, `53fa425`, `510f766` |
| Frontend (Phase 3) | lint, typecheck, `pnpm test` → **65 passed**, build OK; Playwright **2 passed** (incl. sandbox approval flow) |
| Evals (Phase 3) | smoke replay unchanged: 3 PASS, 2 unrecorded (exit 1); Mode C cases unrecorded; benchmark-engine eval table 9/9 |
| Compose (Phase 3) | `alembic current` → `0009 (head)`; sandbox egress blocked (re-verified) |
| Required files exist | See Phase 0 validation in the final summary |
| Internal links | Checked by script during Phase 0 |
| Mermaid syntax | Reviewed manually (no renderer installed; not executed) |
| Backend (Phase 2, 2026-10-12) | `uv run pytest -q` → **743 passed** (375 unit, 262 integration incl. a real-process SIGKILL test, 106 security) on PG 17.11, Python 3.12; ruff, format, `mypy --strict` (134 files) clean; CI green on 3.12/3.13 + integration |
| Frontend (Phase 2) | lint, typecheck, `pnpm test` → **59 passed**, build OK (Node 22); Playwright e2e **1 passed** (real API/worker/DB, stub LLM; CI job `e2e` green); browser-verified start → live timeline → findings → evidence chip → plan node, history delete/undo, 375 px |
| Backend (acceptance follow-up, 2026-10-12) | `QC_REQUIRE_DB=1 uv run pytest -q` → **774 passed** (405 unit, 263 integration, 106 security); ruff, format, `mypy --strict` (135 files) clean. Frontend lint/typecheck/59 tests/build clean; Playwright e2e 1 passed |
| Evals (replay) | `python -m querycure.evals run --suite smoke` → **3 PASS** (incl. `pk_lookup_already_optimal`, formerly XFAIL), 2 not yet recorded → exit 1 |
| Backend (injection security evaluation, 2026-10-12) | `QC_REQUIRE_DB=1 uv run pytest -q` → **804 passed** (430 unit, 265 integration, 109 security); ruff, format, `mypy --strict` (135 files) clean. Eval replay under the stricter per-agent check: same 3 PASS, 2 unrecorded → exit 1. Frontend not re-run (unchanged) |
| Compose (Phase 2) | `alembic current` → `0007 (head)` |
| Backend (through T1.19) | `uv run pytest -q` → 448 passed: 359 unit/security + 89 integration on PG 17.11, Python 3.12; CI also runs 3.13 and a `postgres:17` integration job. `ruff check`/`format --check` clean; `mypy --strict` clean on 57 files. Live API check as `qc_app`: readyz ok, session flow 401 → 201 → 200, CSRF 403 envelope |
| Frontend (through T1.18) | `pnpm lint` and `pnpm typecheck` clean; `pnpm test` → 41 passed; `pnpm build` compiles; browser-verified against the live API, including 375 px width |
| Compose | Running: `metadata-db` and `sandbox-db` healthy; `alembic current` → `0002 (head)`; `qc_app` login verified (INSERT yes, UPDATE no on `artifacts`) |

## Open decisions

Defaults are chosen so implementation can proceed; change any before the listed phase.

| # | Decision | Default chosen | Must resolve before |
|---|---|---|---|
| D1 | Public demo backend host (Fly.io / Railway / Render / Cloud Run) | Any small always-on container; decide on price at deploy time | Phase 5 (T5.8) |
| D2 | Enable Mode B (live inspection) on the public demo? | Disabled | Phase 5 |
| D3 | Default LLM models per agent | **Decided by the owner (2026-10-12): free OpenRouter models only, every phase** ([ADR-0016](../engineering/adr/ADR-0016-free-openrouter-models-only.md)). The specific `:free` model is pinned from the Phase 2 eval benchmark | Phase 2 exit (model pin) |
| D4 | Allow user-provisioned sandbox connections (Mode C on user's own non-prod DB) in MVP? | Yes in local profile only, with attestation. **Not implemented in Phase 3** (demo workloads only); revisit with Phase 5 | Phase 5 |
| D5 | Custom domain for demo (needed for same-site cookies) | Required; name TBD | Phase 5 |
| D6 | Write-overhead benchmark in MVP or Post-MVP | Post-MVP (qualitative class shown until then) | Phase 3 |
| D7 | ~~Initialize git + branching model~~ | **Resolved:** git on `main`, **main-only workflow** (CLAUDE.md §10 / AGENTS.md Git Branch Policy); push once a remote is configured | — |
| D8 | Manifest signing (key outside DB) or external timestamping | Deferred; digests + append-only grants + manifest digest in exports (REPLAY_ENGINE §6) | Phase 5 security review |
| D9 | ~~Replay equivalence margin `m`~~ | **Decided by the owner (2026-10-16): keep 1.25** (±25% speed-up drift), not widened to raise reproduction success ([ADR-0023](../engineering/adr/ADR-0023-d9-experiment-replay-equivalence-margin.md)). Evidence: 14 same-machine pairs, 2 passed gate 4; 1 reproduced at 1.25, 1 had an upper drift bound of 1.26–1.43 | — |
| D10 | Retirement policy for old report builders/renderers | Keep all versions; fallback to stored artifacts if ever retired | Before first builder@2 |
| D11 | ~~Sample-quality gate on very fast winning arms~~ | **Decided by the owner (2026-10-12): no plain waiver.** The single experiment keeps `inconclusive`. `verified_with_noise_warning` needs a noise screen (n ≥ 30, no censoring, no param-set regression, quartile separation, every block ≥ `min_effect`) plus agreement of 3 independent experiments ([ADR-0019](../engineering/adr/ADR-0019-noise-warning-verification-and-corroborated-regression.md), `bench@2`) | — |
| D12 | ~~Container worker by default?~~ | **Decided by the owner (2026-10-12): yes** for local Mode C benchmarking. The host worker + relay stays supported, and sandbox isolation is unchanged ([ADR-0020](../engineering/adr/ADR-0020-container-worker-default-for-local-benchmarks.md)) | — |
| D13 | ~~Block agreement for the clean `verified` gate and/or more, smaller blocks (risk R18)~~ | **Decided by the owner (2026-10-13): no change to `bench@2`** ([ADR-0021](../engineering/adr/ADR-0021-d13-clean-verification-block-agreement.md), accepted). 0 of 2,250 real experiments with a true effect < 1.10× were verified; the only rule that fixes the strict-xfail fixture costs about 28 points of correct verifications at 1.18× and still leaves about 27% of the simulated generalized pattern verified. Engine, rules and tests unchanged; strict xfail kept; R18 accepted as documented | — |

- [x] **Final UI polish and production-readiness audit (2026-10-23, UI_UX §3.18, [polish report](../reports/FINAL_UI_POLISH_2026-10-23.md), [readiness audit](../reports/PRODUCTION_READINESS_AUDIT_2026-10-23.md)).** Frontend only; no backend, contract, schema, benchmarking, sealed-report or claims change.
  - **Result summary** above the trace from the sealed report: outcome, headline, verdict, candidate, primary speedup with 95% CI, callouts and every limitation.
  - **Candidate descriptions** derived deterministically from the allowlisted DDL (`describeCandidate`), key kept.
  - **Statistics glossary** (speedup, CI, IQR, robust CV, transport floor, p95; "faster is not verified").
  - **Correctness panel** (UI_UX §3.8, previously not built): recorded fingerprints per param set and the gate-3 outcome; never "equivalent".
  - **Verified:** lint, typecheck, 230 unit tests, build; Playwright 18/18 on two consecutive runs (axe light and dark, 390 px); browser check at 1366 px light/dark and 375 px; backend security tests 145/145; `pnpm audit --prod` and `pip-audit` clean.
  - **Readiness audit:** blockers B1 (no host/domain/deploy) and B2 (real OAuth unverified); high H1 (F1 SSE 500, not reproduced in 2 runs) and H2 (no alerting); medium M1: master-key rotation is not operable (no re-encrypt job, one key loaded); SECURITY §5 corrected. Nothing deployed.

- [x] **UI rebuild Phase 1: design system, shell, dashboard (2026-10-24, UI_UX §3.2, DESIGN_SYSTEM §2–§5, §7; owner-approved 2026-10-24).** Frontend only; existing endpoints; no backend, contract or schema change.
  - **Tokens:** A · Clinical Teal (dark) and H · Teal Light refined for contrast: `--muted` 7.6:1 dark / 6.6:1 light, slightly stronger borders, `--scrim`, larger `--shadow-pop`. Utilities `qc-page-title`, `qc-section-title`, `qc-label`, `qc-panel-header`, `qc-tag`, `qc-kbd`, `qc-btn-danger`, `qc-btn-sm`; eyebrow 11 → 12px.
  - **Shell:** collapsible sidebar (240px or 56px rail, per-browser preference), *Active runs* from the recent list, theme toggle beside the account.
  - **Dashboard:** prototype Layout 3 on real data only (`lib/investigations/dashboard.ts`, TDD): active investigations with run usage vs budget and approval expiry, run outcomes and median run time of the 25 recent investigations, recent table, status counts. Panels say "unavailable" on a load error instead of showing empty states.
  - **Verified:** frontend lint, typecheck, 253 unit tests, production build; e2e 18/18 (axe clean); screenshots at 1440×900, 1280×800 and 390×844 in both themes, no horizontal overflow.
  - **Polish after review:** top cards stretch to one height (no gap under the shorter card) and the duplicate History link left the 24-hour footer; the 24-hour footer reads *Last 24 h · concluded runs* and the outcomes panel *Sample · 25 most recent … not a time window*; truncated titles carry `title` and wrap to two lines on coarse pointers; drawer footer sign-in links, theme and sign-out controls are 44px on touch, with safe-area bottom padding. Re-verified: lint, typecheck, 253 unit tests, build, e2e 18/18; dark/light at 1440, 1280 and 390 with the dev overlay removed.

- [x] **UI rebuild Phase 2: investigation workspace (2026-10-24, UI_UX §3.6a; owner-approved 2026-10-24; committed locally, not pushed).** Frontend plus one backend contract test; no API, schema or event change.
  - Waterfall trace with time axis, zoom and recorded-only segments; graph view from the compiled LangGraph topology (JSON copy guarded by a backend test); activity line and figures strip; resizable inspector with execution switcher; row context menu; phone bottom sheet; container-width split for the sidebar rail.
  - **Fixes:** the interrupted `approval_gate` execution showed "did not finish" (now closed at the decision with the wait recorded); `useRunEvents` reports `stream` (connecting/live/reconnecting/offline/closed); the Plan diff scroll box is a focusable region.
  - **Verified:** frontend lint, typecheck, 275 unit tests, production build; backend agent unit tests 185 (incl. topology contract), ruff; Playwright 20/20 (new `workspace.spec.ts`: graph, context menu, splitter, phone sheet, axe light/dark); screenshots of a completed and an approval-waiting local stub run at 1440×900, 1280×800 (expanded and rail) and 390×844 in both themes, no horizontal overflow.
  - **Polish pass after review (2026-10-24, not committed):**
    - Graph: narrower three-column layout with a right-hand bus to `write_report` (fit 104% at 1440×900, 85% at 1280×800, was about 60%); fit to width and height within 85–115%; panel sized to the graph; drag-to-pan; centred zoom; no clipped names. A new geometry test found and fixed an exit drawn behind `run_experiment`.
    - Waterfall: opt-in compressed time for approval waits ≥ 25% of the run, labelled breaks and a not-to-scale note; linear stays the default. Axis labels laid out by width (fixed overlapping right-edge ticks).
    - Compact result summary: provenance always visible, limitations behind a disclosure.
    - Phone sheet: one header row (name, Actions, Close). Focus moves to the node/row after "Show in graph/waterfall" (it went to the page). Toolbar wraps (fixed a 71px overflow at 390px). Inspector default 38%.
    - **Verified:** lint, typecheck, 285 unit tests, production build, Playwright 20/20 (workspace spec now also checks graph focus, fit ≥ 85% and the single sheet header); screenshots of a completed and an approval-waiting local stub run at 1440×900, 1280×800 and 390×844 in both themes, no horizontal overflow. Backend unchanged (not re-run).
  - **Final improvements (2026-10-24, after approval):** the graph has a "Selected node" status strip under the canvas with the node's full name, state and recorded details, unscaled and wrapping, so nothing depends on the 85% canvas text; a "Drag to explore" hint in that strip on touch screens while the canvas overflows, gone after the first scroll; on narrow trace panes the compressed-time note is one line ("Not to scale across ≈ breaks; the Time column is real.").
    - **Verified:** lint, typecheck, 286 unit tests, production build, backend agent unit tests 185 incl. the topology contract, ruff, format, mypy; Playwright 20/20; browser check at 390×844.

- [x] **UI rebuild Phase 3: evidence and benchmark UI (2026-10-24, UI_UX §3.19; owner-approved visually 2026-10-24; committed locally, not pushed).** Frontend only; existing endpoints (`/findings`, `/evidence/{id}`, `/candidates`, `/verifications`, `/experiments/{id}`); no API, schema, verdict or claims change.
  - Evidence tab: five-column relationship graph from recorded references, one inferred link type (finding → hypothesis by shared supporting evidence) drawn and labelled apart, selected-path / everything, record inspector with provenance, artifact and recorded backlinks, navigation to plan, trace step and benchmark; stacked list below 880 px of panel width.
  - Benchmark studio: arms rail, verdict card with measured and predicted kept apart, measurement notes, forest plot with the selection marked, distributions, correctness and auditor gates; full tables behind "Show data tables".
  - **Fix found in browser verification:** links that skip a column (evidence → verdict cited by the auditor) passed behind the candidate cards and looked as if they ended there; they now run through the gutters and a lane under the cards. The width observer missed panels that first mounted empty, so the split inspector drew the wide graph at 432 px.

  - **Verified:** frontend lint, typecheck, 303 unit tests (evidence graph 9, explorer 5, studio 2 new, evidence-span index 1), production build; backend unit 1015 passed (incl. the topology contract); Playwright: the first full run had 1 failure in `sandbox-approval.spec.ts` that was not captured, then it passed alone and the full suite passed 20/20 twice in a row. Screenshots of a local stub sandbox run (Evidence in the Results view and the Tournament studio) at 1440×900, 1280×800 and 390×844 in dark and light; no horizontal page overflow.
  - **Not done / open:** the results tab bar scrolls sideways on phones (five tabs); evidence cards truncate long eyebrows (full text in the card's name, tooltip and record panel); the speedup axis shows few ticks when every interval is close to 1×; the intermittent sandbox e2e failure was not reproduced.
  - **UX polish pass (2026-10-24, owner request; awaiting visual approval, not committed).** Frontend only, UI_UX §3.19 updated.
    - Evidence: "Selected path" keeps unrelated records listed, quieter and selectable; first selection is the verified verdict; crossing-reducing column order; link tooltip and record-panel readout (source, target, relationship, field or inference basis, recorded / inferred / contradicting); end dots on links; readable cards with short ID + copy, Show more when stacked.
    - Charts (`lib/benchmark/scale.ts`, TDD): width-adaptive log ticks, collision-free labels, a minimum axis span that is stated when applied, deterministic sample dodging, Tukey outlier rings, keyboard sample slider, focusable interval strips with exact values.
    - Phones: distributions, checks and plan diff become disclosures with summaries; checks stay open on warnings; verdict card adds correctness and tested scope.
    - **Verified:** lint, typecheck, 335 unit tests, production build; Playwright full suite three times: 20/20, 19/20, 20/20; axe clean on the new states (sections open, sample and interval focused, link inspected) at 1440 and 390 in both themes; no horizontal overflow at 1440, 1280 and 390.
    - **Found in that run (fixed below):** the 19/20 run failed in `workspace.spec.ts` (phone bottom sheet) during the new-investigation form. The trace shows Step 2's Continue clicked 29 ms after "Analyze plan", while `POST /inspect/plan` (40 ms) was in flight. `continueFromSource` then shows "Analyze a plan first" without advancing, and the test's next Continue advanced only to Step 3. Proposed fix: disable Step 2's Continue while the analysis or EXPLAIN is pending, and wait for each step heading in `finishedOfflineRun`. The earlier sandbox-spec failure did not recur and is still unexplained; the sandbox path has no async step and its spec waits between steps, so it is probably not the same race.
  - **Wizard race fix (2026-10-24, UI_UX §3.14).** Root cause confirmed in `Workspace.tsx`: `continueFromSource` rejected a Continue click made while `POST /inspect/plan` was pending ("Analyze a plan first"), and `workspace.spec.ts` clicked Continue twice without waiting, so the second click only reached Step 3 and the Title field never appeared.
    - Step 2's Continue is disabled until the source is ready, with the reason beside it (`aria-describedby`); while the analysis or EXPLAIN is pending it reads *Analyzing plan…* / *Running EXPLAIN…* and Ctrl/Cmd+Enter is ignored. A failed request keeps the API message and offers *Retry analysis* / *Retry EXPLAIN*.
    - Stale responses: a plan records the input it came from (plan text, or connection + SQL); a response for edited input is displayed but never makes the step ready or reaches the create request.
    - e2e: shared `e2e/wizard.ts` (`advanceTo` waits for an enabled button and asserts the next step; `analyzeUploadedPlan` waits for the tree and an enabled Continue), used by the four wizard specs. No timeouts added.
    - **Regression tests:** unit (pending analysis cannot advance by click or shortcut, failure + retry, edited/stale plan, disabled-with-reason) and e2e (`/inspect/plan` held pending by `page.route`, with axe; a refused analysis with retry, with axe). Both fail against the old code (4 unit, the e2e at "Analyzing plan…") and pass with the fix.
    - **Verified:** lint, typecheck, 338 unit tests, production build; Playwright full suite 22/22 on two consecutive runs. Backend not affected (no backend change) and not re-run.
  - **Chart polish pass (2026-10-24, owner request; owner-approved visually 2026-10-24, committed).** Frontend only, UI_UX §3.19 and DESIGN_SYSTEM SpeedupForest updated; no scale, interval, threshold or measurement change.
    - Speedup forest: on narrow studios (all current layouts, 324–606 px) each row is one header line (candidate and param set left, estimate, interval and n right) over a 24 px strip, with rules between rows; the wide three-column grid is kept above 42 rem. The 1× line is solid ink with a halo; the legend reads "1× no change" like the in-chart label; the caption is one paragraph.
    - Timing distributions: arm figures on one line (they wrap as a unit); a compact key (median, outliers kept, transport floor with its value) replaces the paragraph; the full explanation is in a *How to read this chart* disclosure; *Recorded samples · n 30 / 30* no longer wraps. Charts are 23–29% shorter (speedup 397 → 304 px, distributions 468 → 356 px at 1440×900).
    - **Verified:** lint, typecheck, 340 unit tests (2 new), production build; Playwright full suite 22/22 after updating the one assertion on the renamed legend (the first run of the three relevant specs failed on it: `sandbox-approval.spec.ts` looked for "1× no improvement"). Scripted browser check of a local stub sandbox run at 1440×900, 1280×800, 390×844 and 2560×1300 in both themes: no label collisions, tooltip inside its strip, hover and keyboard give exact recorded latencies, both disclosures open by keyboard, axe clean, no horizontal overflow; the wide grid checked by forcing a 760 px studio. Near-1× rendering covered by the unit test only (the stub run is not near 1×).
    - **Open (minor, documented, not fixed):** the results tab bar scrolls sideways on phones (five tabs); evidence cards truncate long eyebrows (full text in the card's name, tooltip and record panel); near-1× rendering verified by unit test only; the wide (≥ 42 rem studio) speedup grid is reached by no current layout and was checked only at a forced width; the one earlier sandbox e2e failure was never reproduced or explained. Phase 4 not started (needs owner approval).

- [x] **UI rebuild Phase 4, workstream 1: Plan Diff (2026-10-25, UI_UX §3.20; owner-approved visually 2026-10-25; committed locally together with workstream 2, not pushed).** Frontend only; existing `GET /runs/{id}/plans/diff` and experiment data; no API, schema, verdict, benchmark or replay change.
  - `lib/plan/diff.ts` (TDD, 11 tests): rows for both layouts, change labels, metric provenance (measured vs planner estimate), summary figures, estimate-only detection, ratio wording.
  - `PlanDiffView`: summary cards with source tags, benchmark median kept apart from the single capture, side-by-side and unified layouts, per-node recorded-metrics panel (focus returns to its marker), estimate-only note, skeleton while loading, plan digests.
  - `tournament/PlanCompare`: candidate select (drives the studio selection) and parameter-set select; missing captures stated; the section no longer remounts on arm change, so a phone disclosure stays open.
  - **Verified:** lint, typecheck, 360 unit tests (11 diff lib + 9 component new), production build; Playwright full suite 22/22, then the two Mode C specs again 2/2 (sandbox spec now covers both layouts, keyboard open/close with focus return, axe with the metrics panel open in light and dark). Scripted screenshots of a local stub sandbox run at 1440 and 390 px in both themes, no horizontal page overflow.
  - **Limitations:** the diff carries property names, not condition values; the ≥ 42 rem column layout is reached by no current studio layout (unit-tested markup only); on phones the node-metrics table scrolls sideways inside its focusable region. The five Phase 3 minor issues remain open.

- [x] **UI rebuild Phase 4, workstream 2: Approval drawer + Plan Diff refinements (2026-10-25, UI_UX §3.20–3.21; visual direction owner-approved 2026-10-25; final polish below; committed locally, not pushed).** Frontend only; no API, schema, verdict, benchmark or replay change.
  - Plan Diff refinements from the workstream 1 review: stacked baseline/candidate summary values on narrow cards; truncated long identifiers with the full text in the node panel; stacked node-metric cards in narrow panels.
  - `lib/approval/review.ts` (TDD, 7 tests): decision semantics, outcome (recorded vs already decided), review phase incl. expiry by clock, countdown, verbatim statements, candidate context join with digest check, byte formatting.
  - `useApprovalDecision` (shared by card and drawer), `ApprovalDrawer`, `ApprovalReview`; `ApprovalCard` gains *Review details* and refuses decisions past the expiry time; workspace keeps the drawer open across the decision.
  - **Verified:** lint, typecheck, 383 unit tests (12 drawer + 7 review lib + 3 plan diff + 1 card new), production build; Playwright full suite 22/22 (sandbox spec now approves through the drawer: exact SQL, digest, axe in light and dark, Esc with focus return, focus to the page heading after closing on success); Mode C specs again 2/2 after the last edit. Scripted screenshots at 1440 and 390 px in both themes: axe clean and 0 px horizontal overflow in every drawer state and the plan diff. Multi-candidate, expired, error and already-decided screenshots use browser-side fixture responses (labelled FIXTURE); the single-candidate request, success and decline are real stub runs.
  - **Found and fixed in verification:** a 4.47:1 contrast failure (approval badge on the selected card's accent tint, light theme); mobile footer wrapping.
  - **Open:** one full-suite run failed the Evidence-tab phone-width overflow check (scrollWidth 1152 right after resizing to 390); the spec passed 2/2 alone and 22/22 in the next full run; not reproduced or explained. Index size is never recorded by the backend today, so that row never shows. A stub run proposes one candidate only, so multi-candidate e2e coverage is unit-level.
  - **Final polish (2026-10-25, after the owner's 9/10 review):**
    - **Expired request stayed actionable (P0), root cause:** a 409 from the decision endpoint ("This approval request has expired.", sent only once the worker's sweep has marked it expired) was handled like any error: the message showed, the approvals list was refetched, and the phase stayed `pending` until a refetch said otherwise. Until then, or for good if the list still said pending, both actions stayed enabled (a unit test asserted that retry). The client clock also only ticked every 15 s, so the expiry time could pass unnoticed for up to 15 s. **Fix:** a 409 is a refusal (`isRefusal`). It moves the request to a new *not recorded* phase at once, in the card and the drawer. The footer becomes *Close*, the server's message and request id stay, the expiry time is restated, and the server's status replaces it when the refetch lands. Other failures stay retryable and are never shown as decisions. The clock is re-read at the expiry instant. `submit` sends only while pending and nothing is in flight (a synchronous guard against double click, Enter plus click, or card plus drawer). No backend or contract change.
    - Mobile footer: the count on its own line, then *Decline all* sized to its label and *Approve selected* filling the rest of the row; the countdown no longer wraps. The inline card's workload id now wraps (it overflowed the page by 11 px at 320 px).
    - Hierarchy: the header subtitle is one truncated line (*Round N · investigation*); request metadata is compact. A candidate record that links no hypothesis says so.
    - Fixtures: the screenshot harness now uses chronologically consistent fixtures (expired: requested 25 h ago, expired 1 h ago; refusal: browser clock 2 min behind the server, expired 1 min ago; already decided: decided after the request) with an on-page FIXTURE banner.
    - Plan Diff: no regression found at 320, 390 and 1440 px in either theme (axe clean, 0 px overflow); unchanged.
    - **Verified:** lint, typecheck, 393 unit tests (55 files; new: refusal phase and `isRefusal` lib tests; drawer tests for the 409 refusal, refusal then expired status, retryable non-409 failure, the pending → expired transition at the deadline, one request per decision (fails without the guard), Enter with exact partial ids, copy failure, bounded SQL region, no linked hypothesis); production build; Playwright full suite 22/22. The sandbox spec now checks the drawer footer at 320/375/390 px (one row, unwrapped, inside the sheet, clear of the last candidate, 0 px overflow) and a real-UI 409 refusal. Screenshot harness: 35 states, axe clean in light and dark, 0 px horizontal overflow.
    - **Limitations:** a refused card without the drawer open disappears once the refetch shows the request expired (the run header and timeline then carry the state). The refusal and multi-candidate states are covered by unit tests and browser-side fixtures only, because the stub proposes one candidate and the real API cannot be made to expire on demand in e2e. The Evidence-tab overflow flake noted above did not recur (22/22).

- [x] **Plan Diff metric cards (2026-10-25, UI_UX §3.20; owner visual approval 8.8/10).** Frontend only (`PlanDiffView.tsx` and its tests); no API, schema, benchmark, verdict, selector, layout-toggle, node-metrics, drawer or replay change.
  - **Root cause:** the summary grid was a fixed two columns below a 42 rem diff container, so inside the studio panel (254–464 px wide at 320–1440 px viewports) cards were 123–212 px. Label and value sat side by side within that width, which clipped values at 320 px (`0.33 m`, `22 b`). At 1024 px the four-column wide layout gave 174 px cards.
  - **Change:** one card per row below a 33 rem diff container and two columns from there (container query, not viewport). Each card shows its title and tag, labelled *Baseline* / *Candidate* columns (tabular, no wrap; the candidate wraps under the baseline when both don't fit) and the source below. *What changed* spans the full width and may break index names after `_`. No derived speed-ups.
  - **Verified:** lint, typecheck, 395 unit tests (3 new plan-diff tests), production build. Playwright accessibility, keyboard, workspace and phase4-lifecycle specs 19/19. Scripted screenshots of a real stub run at 320/375/390/640/720/768/1024/1280/1440 px in both themes: axe clean on the plan diff, 0 px page overflow, no clipped, wrapped or overflowing card content. The same checks ran on a browser-side FIXTURE with inflated values (12,346 ms, 123,456,789.12 cost, 18,271,560 blocks). Final verification before commit: lint, typecheck, 395 unit tests, production build, Playwright accessibility, keyboard, workspace, phase4-lifecycle and sandbox-approval specs 20/20. 200 % zoom was checked by emulation, not the browser's zoom control (Playwright cannot drive it): CDP device metrics at 640×450, 720×450 and 512×384 CSS px with device pixel ratio 2 (what 200 % does to 1280, 1440 and 1024 px windows) on a real stub run, light and dark. All five cards were 283–446 px wide, every value sat on one line inside its card, nothing was clipped, and the page overflowed by 0 px.

- [x] **UI rebuild Phase 4, workstream 3: contextual command palette (2026-10-25, UI_UX §3.15; approved by the owner with minor refinements; final polish applied and committed).** Frontend only; no API, schema, backend, verdict, benchmark or replay change; no new dependency.
  - `lib/command/runScope.ts` (TDD, 8 tests): run-scoped items from findings, hypotheses, candidates (recorded status via the shared `lib/benchmark/status.ts`), plan-diff arms and cited evidence (loaded / not loaded / unavailable), stamped with the run; grouping with caps and hidden counts. `lib/investigation/agents.ts` shares agent names with FindingsPanel.
  - `CommandProvider`: `useRunScope`, `usePaletteOpen`. `CommandPalette`: scope chip, Backspace and *Search Run #N only*, loading/notice/empty states, stacked details on phones. `InvestigationView` registers the selected run's scope and handles selection; the experiment detail behind the plan-diff list is read only while the palette is open.
  - Minimal `focusSection`: `TournamentPanel` → `ExperimentView` → `StudioSection` (`reveal` opens the folded disclosure) → `PlanCompare` (`focusRequest` focuses the candidate picker, or the heading when the picker is disabled). An arm without a plan reports done without focusing.
  - **Verified:** lint, typecheck, 416 unit tests (21 new: runScope 8, palette scope 6, page-level palette 5, focusSection 2), production build; Playwright full suite 22/22 twice, with new assertions in `keyboard.spec.ts` (scoped palette on a real offline run, Enter focuses the finding, Backspace widens, axe light and dark) and `sandbox-approval.spec.ts` (recorded candidate status without ×, jump to the plan diff at 390 px opens the folded section and focuses the heading, axe light and dark, no overflow). Scripted screenshots of a real stub sandbox run against the production build: 34 states (global and run-scoped, search, empty, left scope, plan-diff jump) at 320, 390, 768 and 1440 px in both themes, axe clean, 0 px page overflow, palette inside the viewport.
  - **Final polish (owner review, 2026-10-25):** run-scoped results now lead with *This investigation*, then *Actions* and *Navigate* (global order unchanged); same-titled investigations show their creation time (and a short ID when the minute repeats) as an untruncated part of the detail; an empty run-scoped search offers *Search all investigations for “…”*, keeping the query; a replayed same-point mousemove no longer moves the selection, and the first option scrolls its heading back into view; the plan-diff heading's focus ring is flush with a 2 px gap so it no longer covers the description, and a pointer jump focuses without a ring (keyboard keeps it). Global `:focus-visible` is unlayered, so the two overrides live in `globals.css`, not utilities.
  - **Final verification:** lint, typecheck, 428 unit tests (12 new: titles 3, palette 7, plan-diff focus 1, page-level pointer assertion), production build, Playwright full suite 22/22 (keyboard spec: empty-state recovery keeps the query; sandbox spec: keyboard jump shows a solid, flush ring with a gap ≥ its width). Scripted screenshots of real stub runs against the production build: 46 states at 320, 390, 768 and 1440 px in dark and light (global, run-scoped, duplicate titles, empty state and recovery, long list End/wrap, plan-diff keyboard and pointer jumps): axe clean, 0 px page overflow, palette inside the viewport, no clipped time or ID. Viewport emulation only; no browser zoom test in this pass.
  - **Limitations:** a stub run proposes one candidate, so focusing an enabled candidate picker is covered by a unit test only; the plan-diff list reflects the latest round's approved experiment (what the Tournament tab shows by default), not replicates or earlier rounds.

- [x] **CI fix: ⌘K e2e race (2026-10-26).** CI run 40201784103 failed `keyboard.spec.ts` (palette did not open). **Root cause, confirmed:** the test waited for the server-rendered sidebar nav, which is visible before hydration, and pressed ⌘K before `CommandProvider`'s effect attached its `keydown` listener. In the CI trace the press (58 231–58 280 ms) finished before the first client-effect requests (58 279 ms), and the key was lost. Reproduced locally with Chromium CPU throttled 4× and 6× (first cold load lost the key; it never opened later). **Fix:** `CommandProvider` sets `data-shortcuts="ready"` on `<html>` right after attaching the listener and removes it on cleanup. The e2e helper `e2e/shortcuts.ts` waits on it, so there is no timeout change, delay or retried key press. Keys pressed before hydration are still dropped; that is inherent to a server-rendered page and the window is short. **Tests:** a unit test checks the marker is absent while the listener is attached, there is exactly one `keydown` listener across command re-registration, and both are removed on unmount. A new e2e test runs at 6× CPU: ⌘K after readiness, Esc returns focus, `g` navigation across three pages keeps one window `keydown` listener (CDP count) and one press still opens the toggle, and the palette opens in light and dark. With the old visibility wait the same test failed 4/4. **Verified:** lint, typecheck, 429 unit tests, production build, keyboard spec 20/20 (`--repeat-each 5`), full Playwright suite 23/23.

- [x] **UI rebuild Phase 4, Workstream 4 Stage 1: Status Orb and activity indicators (2026-10-26, UI_UX §3.6b, DESIGN_SYSTEM §2/§5/§9). Visually approved by the owner (9.3/10) and committed locally; not pushed, not deployed. Screenshots and the evidence log: `test-results/ws4-stage1/` (repo root, gitignored).** Frontend only; no API, schema, backend, LangGraph, benchmark, verification or replay change; no new dependency. Stage 2 (Run Selector) not started.
  - **Problem:** `StatusIcon` spun for every `running` tone, so polled and stored statuses looked live: sidebar (plus a pulsing dot), History rows, dashboard Running tile and in-flight pills, the header pill, and trace glyphs even while the stream was reconnecting. The trace stripe and graph marker followed the stored status, not the stream. Under reduced motion the global 0.01 ms rule left these loops running (frame jumps), not stopped.
  - **Change:** `StatusOrb` (`tone`, `live`, `size`, `label`): still by default, moves only with `live` + `running` + ≥ 12 px. `StatusIcon`/`StatusPill` draw running as the orb and take `live` (default false); `RunStatusPill` always still. Liveness passed only where the stream is confirmed live: header activity orb (`activityOf().animate`), open trace spans and stripes (`qc-seg-moving` split from `qc-seg-live`), graph running node (`TraceGraph` gains `live`). Sidebar, History, Dashboard, StepDetails, legend and the trace *Live* dot are still. Reduced motion sets status animations to `none`.
  - **Tests (TDD, 20 new, 449 total):** `StatusOrb.test.tsx` 8, `TraceLiveness.test.tsx` 6, `InvestigationView` header 3 (live, reconnecting, offline keeps *Running*), sidebar, History and dashboard stay still 1 each; shared `test/motion.ts` observes moving indicators in the DOM.
  - **Verified:** lint, typecheck, 449 unit tests, production build, Playwright 23/23 (axe, keyboard, reduced-motion specs included). Scripted screenshots against production builds of HEAD (before) and the working tree (after), interleaved on the same real stub sandbox runs (sf=1.0, measuring) at 320, 390, 768 and 1440 px in dark and light: 96 shots plus 4 reduced-motion, axe clean (24 scans), 0 px overflow. After: moving indicators only on live runs with an open step (header orb, open trace row glyph and stripe); none in sidebar, History, Dashboard, reconnecting or completed states; reduced motion computes `animation-name: none`. Reconnecting was produced by aborting the event stream in the browser (route abort + closing the open `EventSource`); the run kept running in the worker. Harness runs were tagged and cleaned up; no active runs before or after.
  - **Finalization (2026-10-26):**
    - **Active trace evidence:** `test-results/ws4-stage1/active-trace/`. Two real stub sandbox runs (sf=1.0, one per theme, 1440×900, production build) were captured 1.0–1.6 s after approval, with the `run_experiment` row scrolled into view under the sticky header. In both themes only three elements had a computed animation: the header activity orb, the `run_experiment` row's orb and its waterfall stripe (`qc-orb` 2.4 s, `qc-stripe` 1 s). Pixel diffs 400 ms apart: the active row and the header changed; the sidebar did not. Another row's pixels also changed, but only because its bar geometry rescaled as the time axis grew (for example `width: 88.6%` → `77.2%`); it had no animation. After the run completed: no animated elements, and the row was unchanged between frames.
    - **Local data:** the earlier Stage 1 harness runs had left 63 investigations titled `WS4S1 harness <stamp> …` (5 invocations; the harness only cancelled its runs). Their provenance was checked: each title stamp is the harness start time and falls 0.8–1.7 s before its batch's first `created_at`; all belong to the local developer user in the Docker metadata DB; the workloads were the harness's own; the last batch's 16 IDs match its evidence log; and all runs had finished. They were soft-deleted with the app's `DELETE /investigations/{id}`, so they can still be restored. That user's live investigations went from 482 to 419, and nothing else changed. The scratch harnesses now soft-delete their own investigations in `finally`.
    - **Final verification:** lint, typecheck, 449 unit tests (60 files), production build, Playwright full suite 23/23.
