# Current Phase

| Field | Value |
|---|---|
| Phase | **3 — Optimization & benchmarking** (Phase 1 complete: [PHASE_1_REPORT](reports/PHASE_1_REPORT.md); Phase 2 implemented, acceptance partially met: [PHASE_2_REPORT](reports/PHASE_2_REPORT.md)) |
| Status | **Phase 3 implemented; exit partially met** ([PHASE_3_REPORT](reports/PHASE_3_REPORT.md)). Owner decisions applied 2026-10-12/13: ADR-0018 approved in principle with documented assumptions; **D11** resolved as `verified_with_noise_warning` via independent replication; **D12** container worker is the local default (ADR-0019, ADR-0020, engine `bench@2`, migration 0010); **D13** closed 2026-10-13 as no change to `bench@2` (ADR-0021 accepted). Acceptance #1, #3, #4, #5 met against real PostgreSQL 17. #2: fresh engine-level sf=1 runs (host relay, 5 seeds, not a full API run) ended `verified` (3/5) or `verified_with_noise_warning` (2/5). The committed sf=1 fixture stays the recorded `bench@1` `inconclusive` until re-recorded. **Pending, tracked separately** (see [Pending real-model evaluations](#pending-real-model-evaluations)): Phase 2 smoke recordings `orders_injection_in_schema`, `orders_plain_explain` (Phase 2 acceptance stays partial until recorded) and Phase 3 Mode C recordings `orders_sandbox_composite_index`, `rewrite_trap_sandbox`. No OpenRouter request was sent in Phase 3 or in this change. Phase 4 not started (awaiting go-ahead) |
| Last updated | 2026-10-13 |
| Application code | Phases 1–3: API, metadata DB (migrations 0001–0010), parsing, inspection gateway, artifact store, six demo workloads; multi-agent graph with Optimization Engineer, approval gate (interrupt/resume, expiry), sandbox benchmark engine (`bench@2`: corroborated regressions, noise screen, independent replication) and tournament; web app with workspace (upload / live EXPLAIN / demo workload), live timeline, findings, approval card and tournament tab. |

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
4. Wait for the owner's go-ahead before starting Phase 4.

## Pending real-model evaluations

Tracked separately from phase work. Each needs free OpenRouter quota (ADR-0016; resets 00:00 UTC). No paid API is ever used. Record Phase 2 first.

| Case | Phase | Suite | Status | Notes |
|---|---|---|---|---|
| `orders_injection_in_schema` | 2 | smoke | **Recorded 2026-10-13, PASS** | `nvidia/nemotron-3-super-120b-a12b:free`, 7 calls; all security checks ok (PHASE_2_REPORT §13) |
| `orders_plain_explain` | 2 | smoke | **Recorded 2026-10-13, PASS** | 6 calls; smoke replay 5/5 PASS (exit 0); CI integration job now runs the smoke replay |
| `orders_sandbox_composite_index` | 3 | full | Not recorded | Needs `SANDBOX_ADMIN_URL` / `SANDBOX_BENCH_PASSWORD` |
| `rewrite_trap_sandbox` | 3 | full | Not recorded | As above |

## Verification status

| Check | Result |
|---|---|
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
| D9 | Replay equivalence margin `m` | 1.25 (±25% speedup drift); revisit after measuring same-machine replay variance in Phase 4 | Phase 4 exit |
| D10 | Retirement policy for old report builders/renderers | Keep all versions; fallback to stored artifacts if ever retired | Before first builder@2 |
| D11 | ~~Sample-quality gate on very fast winning arms~~ | **Decided by the owner (2026-10-12): no plain waiver.** The single experiment keeps `inconclusive`. `verified_with_noise_warning` needs a noise screen (n ≥ 30, no censoring, no param-set regression, quartile separation, every block ≥ `min_effect`) plus agreement of 3 independent experiments ([ADR-0019](../engineering/adr/ADR-0019-noise-warning-verification-and-corroborated-regression.md), `bench@2`) | — |
| D12 | ~~Container worker by default?~~ | **Decided by the owner (2026-10-12): yes** for local Mode C benchmarking. The host worker + relay stays supported, and sandbox isolation is unchanged ([ADR-0020](../engineering/adr/ADR-0020-container-worker-default-for-local-benchmarks.md)) | — |
| D13 | ~~Block agreement for the clean `verified` gate and/or more, smaller blocks (risk R18)~~ | **Decided by the owner (2026-10-13): no change to `bench@2`** ([ADR-0021](../engineering/adr/ADR-0021-d13-clean-verification-block-agreement.md), accepted). 0 of 2,250 real experiments with a true effect < 1.10× were verified; the only rule that fixes the strict-xfail fixture costs about 28 points of correct verifications at 1.18× and still leaves about 27% of the simulated generalized pattern verified. Engine, rules and tests unchanged; strict xfail kept; R18 accepted as documented | — |
