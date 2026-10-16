# Phase 5 Report — Production polish

- **Dates:** 2026-10-16 → 2026-10-16 (UTC), one implementation session after the owner authorized Phase 5.
- **Exit criteria met:** **partially.**
  - All P0 code tasks are implemented and verified. The restricted public-demo profile is verified on real containers locally.
  - The phase's exit ("deployed; README reflects what's live") is **not** met. No public deployment was made, because the brief forbids it without the owner's approval, and it needs a domain and hosting accounts.
- **Tasks completed** ([TASKS.md](../TASKS.md)): T5.1, T5.2, T5.3, T5.5, T5.7, T5.9, T5.10. Also the owner's Phase 5 priorities 1–8: replay idempotency, deterministic Mode C evals (R19), the run picker, hardening, deployment architecture, the public demo, reliability, and release verification.
- **Tasks partially done:**
  - **T5.4:** structured logs with correlation IDs and DB-derived Prometheus metrics are done. OTel tracing/export and LangSmith are deferred; they need new dependencies and nothing required them to ship.
  - **T5.6:** run history and mobile layout are done. Plan diff mode already existed from Phase 4; edge weights were not added.
  - **T5.8:** images, the demo compose stack, the release procedure and checklist are prepared and verified locally. **No public URL.**
- **Tasks deferred:** OTel/LangSmith (T5.4 rest), plan-graph edge weights (T5.6 rest), the public deployment (T5.8 exit), user-provisioned sandboxes (D4), nonce-based CSP, and retention of anonymous investigation data. Reasons are in §6 and §10.

## 1. What was implemented

**For users**
- **Run history.** An investigation with several runs shows a run picker, newest first. Each entry says whether the run is the *original*, an *experiment replay* or an *AI re-investigation*, which run it derives from, its status and outcome, the replay result (for example "reproduced with drift"), its creation time, and a link to its sealed report. Selecting a run is a URL (`?run=`); a deleted or foreign run shows a notice and falls back to the latest. It works at 375 px.
- **Safe retries.** Re-running an experiment sends an `Idempotency-Key` per confirmation dialog. A timeout, retry or double click returns the original attempt instead of queueing a second sandbox benchmark.
- **Your own key (BYOK).**
  - Settings → Model key stores an OpenRouter key encrypted and shows only its last four characters. Deleting it wipes the ciphertext. Paid models are refused.
  - Runs use your key and your own free daily allowance.
- **GitHub sign-in (optional).** Anonymous work is kept on first sign-in, and merged into the account when signing in from a second device. Sign-out revokes the session on the server.
- **Public demo gallery** (`/demo`, no sign-in, nothing runs):
  - 7 sealed investigations exported from deterministic eval replays (real free-model answers; real sandbox measurements for the two Mode C runs), plus 4 prerecorded benchmark experiments.
  - Every page carries a "Prerecorded … not a live run, not your database" label. "Check stored digests" re-verifies the shipped bytes against the run's manifest.
- **Landing page** that explains what QueryCure does and what the demo cannot do.

**Technical summary** (migrations 0013–0015)

| Area | Implementation |
|---|---|
| Replay idempotency | `replay_attempts.idempotency_key/request_hash`, unique per `(user_id, kind, key)`. Lookup before work; a losing concurrent transaction rolls back its run, approval and job, then answers with the winner's attempt. A repeated 422 for `not_replayable`; 409 for another body; rate limit charged only after the lookup |
| Deterministic Mode C evals ([ADR-0024](../../engineering/adr/ADR-0024-deterministic-mode-c-evals-measurement-fixtures.md)) | Two seams on `RunContext`: `measure` (the experiment) and `context_inspector` (sandbox context reads). Record mode captures both into a fixture labelled `prerecorded`. Fixture replay feeds them back, with exact prompt matching, approval-digest and config checks, and the frozen-rule check on recorded replication verdicts. Needs no sandbox, benchmark or model |
| Security | Postgres token buckets (`api/rate_limit.py`, `domain/limits.py`), logout/revocation, `user_uploads` ownership, API security headers, no docs page on the demo, demo startup refuses a server model key |
| BYOK | `llm_credentials` (AES-256-GCM, AAD = table:row:user), `investigation_runs.llm_credential_id`; the worker decrypts per run (`llm/credentials.resolve_user_credential`); per-credential `DailyQuota` |
| OAuth | `auth/github.py`, `api/routers/auth.py`: state + PKCE S256 in a path-scoped HttpOnly cookie, session rotation, conversion/merge with key re-encryption |
| Operations | Worker contextvars (`job_id`, `run_id`, …); `/internal/metrics` (Prometheus text from the DB, token-gated); `report_stuck_work` + periodic sandbox-orphan cleanup; SIGTERM drain grace; server-side metadata timeouts and pool settings; `WORKER_MODE=embedded`; `python -m querycure.ops retention` as `qc_retention` |
| Demo | `demo/gallery.py` (bundle model, verifier, loaders), `demo/export.py` (from a finalized run), eval `--export-demo`, `api/routers/demo.py` (public GETs) |
| Deployment | `backend/Dockerfile` (API/worker/migrate, ships migrations and fixtures), `frontend/Dockerfile`, `infra/docker/compose.demo.yaml`, `.github/workflows/audit.yml`, CI image builds, web CSP and security headers |

## 2. Important architecture decisions

| Decision | ADR / doc updated | Why |
|---|---|---|
| Mode C evals replay prerecorded measurements **and** recorded sandbox context; live re-benchmarking stays as a separate mode | ADR-0024 (new), TESTING_STRATEGY | Agent decision quality and live performance are different things to test; ANALYZE sampling made even the context nondeterministic |
| Idempotency keys scoped per user and operation on the resource row (unique index), not a generic key table | API_DESIGN, DATABASE_DESIGN | Same convention as investigation creation, but without cross-user conflicts; atomic with the work it guards |
| Rate limits in Postgres (row-locked token buckets), strict only on the demo | API_DESIGN, SECURITY §5c | ADR-0004 (no Redis); the local profile is one developer on localhost, so its limits are a runaway backstop |
| Uploads are recorded per user; a digest alone is no longer a capability | SECURITY §5 | Closes the documented Phase 2 trade-off before going public |
| OAuth implemented on `httpx` (already locked through openai) instead of Authlib | ADR-0013 (unchanged), pyproject | No new package; the flow is ~150 lines and fully tested against a mocked provider |
| No live sandbox on free hosting; demo shows prerecorded, labelled benchmarks | DEPLOYMENT §3, RISKS R21 | Free shared platforms cannot provide internal networks, resource limits or quiet hardware |
| Metrics computed from the database instead of OTel | OBSERVABILITY §0 | No new dependency; covers restarts and every worker; OTel deferred |

No released contract changed: canonicalization profiles, `report-builder@1` / `report-md@1`, digest algorithms, `bench@1`/`bench@2` semantics, and the template builder `tpl@1` are untouched. Accepted ADRs were not edited.

## 3. Files changed

`git diff --stat f890e4d..29edec0`: 142 files, +28,015 / −319. Most of the added lines are recorded eval data: two measurement fixtures (≈ 0.5 MB) and seven demo bundles (≈ 0.5 MB).

| Area | Files / modules | Notes |
|---|---|---|
| Migrations | `0013_replay_attempt_idempotency`, `0014_rate_limits_and_upload_owners`, `0015_llm_credentials` | expand-only |
| API | `routers/{reports,investigations,settings,session,auth,demo,metrics,inspect,connections}.py`, `rate_limit.py`, `middleware.py`, `schemas/{settings,demo,investigations,session}.py` | |
| Domain/repos | `domain/limits.py`, `db/repositories/{llm_credentials,uploads,users,sessions,replay,investigations}.py` | |
| Agents/evals | `benchmark/measurement_fixtures.py`, `agents/{runtime,run}.py`, `agents/nodes/{run_experiment,collect_context}.py`, `evals/{runner,recording,scoring,__main__}.py`, `agents/prompts/__init__.py` | |
| Auth/LLM | `auth/github.py`, `llm/{credentials,rate_limit}.py` | |
| Ops | `worker/{__main__,runner}.py`, `ops/retention.py`, `db/engine.py`, `core/{config,errors}.py` | |
| Demo | `demo/{gallery,export}.py`, `demo/bundles/*.json` (7) | |
| Frontend | `investigation/RunPicker.tsx`, `settings/SettingsView.tsx`, `layout/{AccountMenu,SessionGate,SideNav,AppShell}.tsx`, `demo/*`, `app/demo/*`, `app/page.tsx`, `next.config.ts`, a11y fixes | |
| Infra/CI | `backend/Dockerfile`, `frontend/Dockerfile`, `infra/docker/compose.demo.yaml`, `.github/workflows/{ci,audit}.yml` | |
| Docs | ADR-0024, DEPLOYMENT, SECURITY, API_DESIGN, DATABASE_DESIGN, OBSERVABILITY, TESTING_STRATEGY, RISKS, RELEASE_CHECKLIST (new), README, CURRENT_PHASE, TASKS, ROADMAP, LEARNING | |

## 4. Tests executed (real output, 2026-10-16, macOS arm64, PostgreSQL 17 + sandbox in Docker, Python 3.12, Node 22)

| Suite | Command | Result | Notes |
|---|---|---|---|
| Backend lint/format/types | `uv run ruff check . && uv run ruff format --check . && uv run mypy src` | clean (203 source files) | |
| Backend, all | `uv run pytest -q` (compose DBs up) | **1312 passed, 1 xfailed** in 166.7 s | 850 non-integration (incl. 109 security unit), 442 integration, 21 security integration; the xfail is the documented R18 limitation |
| New Phase 5 backend tests | `test_experiment_replay_idempotency` (5), `test_eval_measurement_fixtures` (1), `unit/benchmark/test_measurement_fixtures` (6), `security/test_api_hardening` (7), `test_byok_api` (5), `test_github_oauth` (5), `test_operations` (7), `test_retention` (1), `unit/test_demo_gallery` (7) | all pass | |
| Eval smoke | `python -m querycure.evals run --suite smoke` | **5/5 PASS** (recorded, no model calls) | |
| Eval Mode C, fixture | `python -m querycure.evals run --suite full --measurements fixture --case orders_sandbox_composite_index --case rewrite_trap_sandbox` with **no sandbox settings** | **2/2 PASS, byte-identical output on two consecutive runs** | both end `inconclusive` (the recorded live measurements were noisy) |
| Eval Mode C, live | same with `--measurements live` (earlier recording) | 2/2 PASS, but **different path**: both ended `verified_recommendation` with 8 calls, vs `inconclusive` with 11 when recorded | shows live variability (R1); not used as a gate |
| Frontend | `pnpm lint && pnpm typecheck && pnpm test && pnpm build` | 0 lint errors; types OK; **85 tests in 20 files pass**; build OK | |
| End-to-end | `pnpm exec playwright test` (real API, worker, Postgres, sandbox; stub LLM) | **14 passed** (44.7 s), of which 4 are journeys: investigation, sandbox approval, Phase 4 lifecycle (now incl. run-picker navigation and a 375 px overflow check), demo gallery | |
| Accessibility | `pnpm exec playwright test e2e/accessibility.spec.ts` | **10 passed**: axe WCAG 2.1 A/AA clean on 7 core pages × light/dark, plus the history empty state; keyboard focus ring; reduced motion | the first local run found 3 violations (badge contrast, keyboard access to scrollable code, editor scroller). CI then found a 4th that only appears on an empty database (an inline link distinguished by colour alone). All fixed; the empty state now has its own test |
| Dependency audits | `uvx pip-audit@2.9.0 -r <uv export>`; `pnpm audit --prod` | **No known vulnerabilities** (both) | |
| Demo profile | `docker compose -f infra/docker/compose.demo.yaml up --build` + probes | all restrictions hold (DEPLOYMENT §2b) | SIGTERM → `worker_stopped`, exit in ~2 s |
| CI | GitHub Actions | `29edec0`: everything green **except e2e**, where one axe check failed on the empty History page (fixed in the following commit; final run recorded in CURRENT_PHASE). `004e69c`: failed only the new Mode C eval step (the ANALYZE finding, §9). `Audit` workflow green | |

**Free model requests spent:** 43 of 45 on 2026-10-16, all for re-recording the two Mode C cases:
- 18 in the first combined attempt, of which 7 were lost to a sandbox-password conflict I caused;
- 12 re-recording the orders case;
- 13 re-recording it again after the ANALYZE finding.

## 5. Acceptance criteria

| Criterion (ROADMAP Phase 5) | Status | Evidence |
|---|---|---|
| 1. Public demo runs offline analysis with a user's key end to end; prerecorded benchmarks visibly labeled | **Partially met.** Labels met; BYOK run path tested, not exercised against OpenRouter from the demo stack | Gallery labels: `demo-gallery.spec.ts`, `test_demo_gallery.py`. BYOK: `test_byok_api.py` (key resolved per run, removed key stops the run). Demo stack: no-key run → 503, sandbox → 403. A real-key run from the demo containers was not done, to avoid spending the last free requests and sending a key from a throwaway stack |
| 2. Playwright suite + axe scan pass on CI | **Met locally; CI result in CURRENT_PHASE** | 4 journeys + 10 a11y checks pass locally; CI caught one empty-state violation, now fixed and covered |
| 3. Security test suite fully green; manual review checklist signed off in the phase report | **Suite green; checklist below, awaiting the owner's sign-off** | 130 security tests + the hardening sweep; §7 |
| 4. Demo infra cost within target (record actual) | **Not applicable yet**: nothing deployed, actual cost $0 | DEPLOYMENT §3 lists the free-tier fit honestly |
| Exit: deployed; README reflects what's live | **Not met** (deployment needs approval) | README says "not publicly deployed" |

Owner-brief acceptance:
- **Priority 1 (idempotency): met.** Unit, integration, concurrency (5 parallel requests) and crash-before-commit tests, plus a frontend retry test.
- **Priority 2 (R19): met.** Fixture evals are deterministic and offline, and `DIVERGED` never counts as a pass.
- **Priority 3 (run picker): met**, including component and browser tests.
- **Priorities 4–8: met as code and local verification**; deployment is prepared but not performed.

## 6. Known limitations

- **No public deployment.** Hosting, domain and secrets need the owner. The demo profile is verified only locally (`compose.demo.yaml`).
- **Free-tier hosting cannot run the sandbox** (R21). The demo has no live Mode C; benchmarks are prerecorded.
- **Demo outcomes cover** `inconclusive`, `unverified_recommendations`, `no_action_needed`, `verified` and `rejected`. There is **no prerecorded `verified_with_noise_warning`**, and the page says so; a demo would need a recorded run that reached it.
- **Gallery verification** checks shipped bytes against the manifest. It is not a full report replay (bundles ship no database records) and not authenticity.
- **Mode C fixtures embed the recording machine's measurements.** A deliberate prompt or rule change needs a re-record (≈ 8–13 free requests per case).
- **Web CSP allows `'unsafe-inline'` scripts.** Next's bootstrap is inline and nonce-based CSP is not wired.
- **OTel tracing/export and LangSmith are not implemented.** Metrics have no LLM-latency histograms yet.
- **Retention covers bookkeeping only** (sessions, rate buckets, wiped keys). Anonymous users' investigations are not purged automatically.
- **A pre-existing test-order dependency:** `test_baseline_migration` fails when run after `test_role_grants` in a custom order. Alphabetical order (CI) passes.

## 7. Security considerations (manual review checklist vs SECURITY.md)

| # | Control (SECURITY §) | Verified by | Result |
|---|---|---|---|
| T1 | No writes to target DB; plain EXPLAIN only (§4) | Phase 1–4 security tests, unchanged | ✅ green |
| T2/T9 | Session timeouts on target (§4.1 L3) | `test_inspection_gateway`, unchanged | ✅ |
| T3/T8 | SQL validator + function denylist (§4) | `test_sql_validator_evasion` | ✅ |
| T4 | Prompt-injection fencing, injected-tool attempts | `test_prompt_fencing`, eval `orders_injection_in_schema` PASS | ✅ |
| T5 | SSRF guard incl. rebinding (§5.1) | `test_ssrf_guard`; demo forces `ALLOW_PRIVATE_TARGETS=false`; Mode B off on demo (probe: 403) | ✅ |
| T6 | Credentials never exposed (§7) | BYOK tests: hint-only responses, no key in validation errors (`SecretStr`), ciphertext ≠ plaintext, AAD binding, wipe on delete; OAuth token never stored; `UserCredential.__repr__` hides the key | ✅ |
| T7 | Cross-user access (§9) | Sweep of **every** documented route with a path parameter as another user (≥ 25 calls): 404/403 only, no IDs or titles leaked, nothing changed. **Found and fixed:** `reinvestigate` checked model configuration before ownership | ✅ after fix |
| T7b | Upload digests as capabilities (§5) | `user_uploads` + test | ✅ closed |
| T10–T12 | Sandbox isolation, role privileges, no egress (§8) | `test_sandbox_isolation`, unchanged; replay re-checks DDL allowlist and approval digest (Phase 4) and the fixture path re-checks approval digests | ✅ |
| T13 | Cost/abuse: rate limits, BYOK only, concurrency (§9) | `test_api_hardening` (429 + Retry-After, spoofed XFF ignored, last-token race); demo startup refuses a server key | ✅ |
| T14 | Session theft/CSRF (§9) | CSRF tests; logout revocation; OAuth state + PKCE; session rotation on sign-in; Secure/HttpOnly/SameSite cookies on the demo stack | ✅ |
| T15 | Evidence integrity (§10) | Phase 4 replay tests; gallery digest checks, tamper tests | ✅ (consistency, not authenticity) |
| — | Headers | API: nosniff, no-referrer, DENY, `frame-ancestors 'none'`, no-store, HSTS (demo). Web: CSP (with `'unsafe-inline'`), nosniff, DENY, Permissions-Policy | ⚠️ CSP gap documented |
| — | Secrets in repo | `.env` untracked; diffs scanned before every commit; fixtures and bundles checked for host and user paths | ✅ |
| — | Metrics endpoint | 404 without token; empty token treated as unset (found while writing the demo compose file) | ✅ after fix |
| D8 | Manifest signing | Still deferred; integrity ≠ authenticity stated everywhere | open by decision |

**Sign-off:** prepared by the implementer, **awaiting the owner's review**.

## 8. What I should study

1. `api/routers/reports.py::replay_experiment` and migration 0013: an idempotency key as a unique index that rolls back the whole unit of work. → LEARNING Phase 5 §1.
2. `benchmark/measurement_fixtures.py`: separating "what the agent decided" from "what the machine measured"; why the recorded replication verdict is checked rather than recomputed. → §2.
3. `api/rate_limit.py::consume`: a token bucket with `SELECT … FOR UPDATE`, and why the idempotent endpoints charge after the lookup. → §3.
4. `api/routers/auth.py` + `auth/github.py`: state vs PKCE, session rotation, merging accounts when ciphertexts are bound to their owner. → §4.
5. `tests/security/test_api_hardening.py::test_no_route_exposes…`: tests that enumerate the API surface, so new routes cannot skip authorization. → §5.
6. `worker/runner.py::_execute`: drain-on-SIGTERM vs abandon-to-lease; structlog contextvars. → §6.

## 9. Interview-relevant implementation details

1. **"Evals that can't replay green" (R19).**
   - *Problem:* recorded model answers, but prompts embedded fresh benchmark numbers.
   - *Options:* fuzzy matching (hides prompt changes), mocking the auditor (removes the agent under test), or recording the measurements.
   - *Choice:* capture the engine's raw blocks and results as a labelled fixture, and replay them through the same persistence hooks.
   - *Subtlety:* result digests include provenance, so the recorded run itself had to receive the relabelled results; otherwise evidence IDs, and with them the prompts, differ.
   - *Test:* two replays byte-identical; tampered numbers fail as "re-record"; swapped SQL fails as a mismatch.
2. **A bug found by CI, diagnosed properly.**
   - *Symptom:* the fixture replay passed twice locally but failed in CI with "recording does not match".
   - *Hypotheses:* CI's sandbox settings differ, or the context is nondeterministic.
   - *Diagnosis:* I dropped the cached template locally and reproduced the failure; the cause was ANALYZE's random sampling on a 100k-row table.
   - *Fix:* record the sandbox context reads too. Not changing the template builder kept released benchmark conditions intact.
   - *Cost:* one re-record (13 free requests), and the replay now needs no sandbox.
3. **Idempotency under concurrency.**
   - *Mechanism:* a unique index on `(user, operation, key)`. Five concurrent identical requests: four fail at commit, roll back their replay run, approval and job, and answer with the winner's attempt.
   - *Crash before commit:* tested by failing the job insert; nothing persists, and the retry succeeds once.
   - *Interaction:* a retry is never rate-limited.
4. **Authorization sweep.**
   - *Design:* rather than hand-writing a test per route, the test walks the OpenAPI schema and calls every route that takes a resource ID as another user, asserting 404, no leaked IDs, and no changed state.
   - *Findings:* the first run found a real ordering bug (configuration checked before ownership); later runs caught every new route automatically (demo slugs, credential IDs).
5. **Account linking with AEAD.**
   - *Constraint:* BYOK ciphertexts bind table, row and user as associated data, so moving a row to another user would make it undecryptable.
   - *Approach:* merging an anonymous user into an existing GitHub account decrypts with the old binding and re-encrypts for the account, then wipes the old copies in the same transaction.
6. **Honest demo.**
   - *Bundles:* the gallery is exported from deterministic replays of real recordings, never hand-made. Every layer carries `prerecorded`.
   - *Verifier:* it states exactly what it proves (shipped bytes are consistent with the manifest) and what it does not (authenticity, full replay).

## 10. Remaining work

- **Owner decisions:**
  - D1 (host), D5 (domain), approval to deploy, and sign-off of §7.
  - D2 stays "Mode B off on the public demo". D4 (user sandboxes) stays deferred. D8 (signing) stays deferred.
- **Deployment:** follow DEPLOYMENT §4b and RELEASE_CHECKLIST; record actual cost.
- **Deferred tasks:**
  - OTel export and LangSmith opt-in (T5.4);
  - plan-graph edge weights (T5.6);
  - nonce-based CSP;
  - retention of anonymous investigations;
  - a prerecorded `verified_with_noise_warning` demo;
  - a real-key BYOK run on a deployed demo.
- **Risks** ([RISKS.md](../RISKS.md)):
  - R19 closed;
  - R20 (public demo abuse) and R21 (free hosting cannot isolate a sandbox) added;
  - R1 (noise) unchanged;
  - R7 (free-tier changes) relevant at deploy time.
- **CI:**
  - `004e69c` failed only in the new Mode C eval step, which this phase's fix addresses.
  - The result for `29edec0` is recorded in CURRENT_PHASE.
