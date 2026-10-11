# Current Phase

| Field | Value |
|---|---|
| Phase | **1 — Foundation** (Phase 0 documentation complete) |
| Status | In progress: T1.1–T1.12 and T1.15 done (T1.7 still needs real plan captures) |
| Last updated | 2026-10-11 |
| Application code | Scaffolding only: FastAPI app factory with `/api/v1/healthz`; Next.js shell page; local Compose file. |

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
  - `config.py`: profile-aware settings; the demo profile refuses `ALLOW_PRIVATE_TARGETS=true` and requires `QD_MASTER_KEY`; secrets are `SecretStr`.
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
- [x] **T1.7 `plans/`** (logic done; real-capture fixtures pending Docker).
  - The parser takes PG JSON (list or object) into a typed preorder `PlanTree`.
  - Every node carries a JSON-pointer `locator` for evidence citations. Unknown keys are kept in `extra`.
  - Strict type checks; 5 MB / depth-256 limits; detection of ANALYZE, TIMING OFF, and BUFFERS.
  - Metrics: loops-aware inclusive and self time, dividing by process count below `Gather`; per-loop estimate error with direction; total rows removed by filter; sort spill; self buffers.
  - Unknown values stay `None`, never 0.
  - 29 tests against hand-computed **synthetic** fixtures (labeled as such in `tests/fixtures/plans/README.md`). Real PG 17 captures will be added when Docker is available, to close ROADMAP Phase 1 acceptance #2.
- [x] **T1.9 SSRF guard** (`connectors/ssrf_guard.py`).
  - Host syntax validation runs before any DNS lookup. inet_aton-style numeric hosts (`2130706433`, `0x7f000001`, `0177.0.0.1`, `127.1`) are refused, as are ports outside the allowlist (5432, 6543, plus configured).
  - DNS is resolved **once**; the target is refused if **any** answer is non-public. IPv4 addresses embedded in IPv4-mapped, 6to4, NAT64 and Teredo IPv6 forms are checked too.
  - Link-local (cloud metadata), multicast, unspecified and reserved addresses are blocked in every profile. Private and loopback addresses are allowed only in the local profile.
  - Returns a pinned `hostaddr` plus the original `host` for TLS. Error details never echo resolved addresses.
  - 70 security tests, including a rebinding resolver (one lookup only) and the real system resolver path.
  - Bug caught by the tests: Python reports `::1` as `is_reserved`, so loopback is now classified before the reserved rule.
- [x] **T1.8 canonicalization profiles and artifact store.**
  - Canonical profiles, as above.
  - `replay/artifact_store.py`: `store_json`/`store_text`/`store_raw_sql` dedupe by digest using `INSERT … ON CONFLICT DO NOTHING` plus re-select. There is no UPDATE and no row lock, so it works as `qd_app`.
  - `get_artifact` re-verifies the digest on every read and raises `ArtifactIntegrityError` on a mismatch.
  - A profile or content mismatch under an existing digest raises `ArtifactConflictError`. Artifacts over 5 MB are rejected. `link()` into `run_artifacts` is idempotent.
  - 11 integration tests run as `qd_app`: 8 concurrent same-digest inserts yield one row, NUL survives storage, and corruption is detected.
- [x] **T1.15 frontend shell.**
  - `styles/tokens.css` holds DESIGN_SYSTEM §2 tokens (light and `.dark`), mapped into Tailwind 4 `@theme` (`bg-surface`, `text-muted`, …). IBM Plex Sans/Mono come via `next/font`.
  - `next-themes` with the class strategy, plus a `ThemeToggle`.
  - `AppShell` has a 56px top bar and a 224px side nav. Planned sections render disabled ("soon"), never as dead links.
  - The `/app` dashboard shows an empty state.
  - `lib/api`: `apiFetch` (cookies, CSRF header on mutations, error envelope → `ApiError`, network failures → `NETWORK_ERROR`) and `case.ts` (snake↔camel, type-fest typed).
  - Types are generated from the backend OpenAPI by `pnpm gen:api`, using `python -m querydoctor.api.export_openapi`.
  - 12 new Vitest tests.
  - Verified in the browser: dark mode switches tokens (`#0E1013` background), the font resolves to IBM Plex Sans, the preference persists, and there are no console errors.
  - Not yet: the mobile single-column layout (UI_UX §3.4) arrives with the workspace (T1.17).
- [x] **T1.4 Alembic baseline** (migration `0001`).
  - Contents: `uuid-ossp`, `qd_app`/`qd_retention` roles (created NOLOGIN if missing; no passwords in migrations), the shared `set_updated_at()` trigger, and tables `users`, `sessions`, `database_connections`, `artifacts`, `run_artifacts`. All follow ADR-0006: UUID, TEXT, TIMESTAMPTZ, soft delete, CHECK-based enums, no FKs.
  - Per-table grants: the app gets SELECT/INSERT/UPDATE on mutable tables but no DELETE, and only SELECT/INSERT on append-only tables. Retention gets SELECT/DELETE.
  - **Deviation (documented in DATABASE_DESIGN):** `artifacts.content` is `BYTEA` holding exact canonical bytes. JSONB would reorder keys, normalize numbers and reject `\u0000`, and TEXT rejects NUL; either could break digest verification.
  - Local login roles come from `infra/docker/metadata-init/01-roles.sh` (idempotent; env passwords with dev-only defaults).
  - 18 integration tests run with `SET ROLE` as the restricted roles: conventions, trigger, CHECKs, a second upgrade as a no-op, a single head, and grants (app cannot UPDATE/DELETE/TRUNCATE/lock artifacts or create tables; retention can delete but not insert).
  - CI gained a `postgres:17` integration job with `QD_REQUIRE_DB=1`, so a missing DB fails instead of skipping.
- [x] **T1.5 session API, CSRF, and error envelope.**
  - `POST /session`: the local profile resolves to the single local user; the demo profile creates anonymous users. A valid existing session is reused (200, not 201).
  - The token is random and stored only as its SHA-256. The `qd_session` cookie is HttpOnly and SameSite=Lax (Secure outside local); `qd_csrf` is readable for double-submit.
  - `GET /me` returns the user, profile and features. `GET /readyz` checks DB reachability and that migrations are at head.
  - Request-ID middleware and CSRF middleware (constant-time compare; `POST /session` exempt per ADR-0013).
  - Every error, including framework 404s, validation errors and crashes, leaves as the documented envelope. Crashes are generic and leak nothing.
  - Migration `0002`: a partial unique index allows one active local user, so concurrent first logins converge. It also grants `SELECT` on `alembic_version` to `qd_app` for readiness. The test first exposed the missing grant as a 503.
  - Tests: 10 unit tests (envelope, CSRF) plus 10 integration tests, with the app engine running as `qd_app` via `SET ROLE`.
  - Verified live: uvicorn as the `qd_app` login against the dev DB (readyz ok, 401 → 201 → 200, CSRF 403 envelope).
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
  - Other users' IDs get 404 on every route. The demo profile answers `FEATURE_DISABLED`. A missing `QD_MASTER_KEY` gives `CONFIGURATION_ERROR` rather than plaintext storage.
  - 15 integration tests plus a unit test that scans every OpenAPI response schema for secret-like fields.
- [ ] **Remaining:** T1.13–T1.14, T1.16–T1.19, and real PG 17 plan captures for T1.7.

## Blockers

- None. Docker Desktop is running. Compose `metadata-db` and `sandbox-db` are healthy on PostgreSQL 17.11; sandbox egress was verified blocked (TCP and DNS), with metadata-db as the positive control.

## Deviations / deferred

- `import-linter` is not configured yet. Its layer contracts reference modules (`agents`, `benchmark`, `llm`) that don't exist, and the tool errors on missing modules. Add the contracts as the modules land, starting with T1.6.
- Starlette deprecated `httpx` for its TestClient, so the dev dependency is `httpx2`.
- Port 8765 on this machine is already in use by another local server. Smoke tests used a random free port.

## Next actions

1. T1.2 CI workflow (lint, types, unit tests, frontend build).
2. T1.3 `core/` (settings, structlog + redaction, errors, AES-GCM), then T1.6 SQL validator and T1.7 plan parser, written test-first.

## Verification status

| Check | Result |
|---|---|
| Required files exist | See Phase 0 validation in the final summary |
| Internal links | Checked by script during Phase 0 |
| Mermaid syntax | Reviewed manually (no renderer installed; not executed) |
| Backend (through T1.12) | `uv run pytest -q` → 392 passed: 321 unit/security + 71 integration on PG 17.11, Python 3.12; CI also runs 3.13 and a `postgres:17` integration job. `ruff check`/`format --check` clean; `mypy --strict` clean on 50 files. Live API check as `qd_app`: readyz ok, session flow 401 → 201 → 200, CSRF 403 envelope |
| Frontend (through T1.15) | `pnpm lint` clean; `pnpm typecheck` clean; `pnpm test` → 13 passed; `pnpm build` → compiled, `/` and `/app` prerendered static |
| Compose | Running: `metadata-db` and `sandbox-db` healthy; `alembic current` → `0002 (head)`; `qd_app` login verified (INSERT yes, UPDATE no on `artifacts`) |

## Open decisions

Defaults are chosen so implementation can proceed; change any before the listed phase.

| # | Decision | Default chosen | Must resolve before |
|---|---|---|---|
| D1 | Public demo backend host (Fly.io / Railway / Render / Cloud Run) | Any small always-on container; decide on price at deploy time | Phase 5 (T5.8) |
| D2 | Enable Mode B (live inspection) on the public demo? | Disabled | Phase 5 |
| D3 | Default LLM models per agent (Gemini tier vs OpenRouter models) | Configurable; pick after Phase 2 evals compare cost/quality | Phase 2 exit |
| D4 | Allow user-provisioned sandbox connections (Mode C on user's own non-prod DB) in MVP? | Yes in local profile only, with attestation | Phase 3 |
| D5 | Custom domain for demo (needed for same-site cookies) | Required; name TBD | Phase 5 |
| D6 | Write-overhead benchmark in MVP or Post-MVP | Post-MVP (qualitative class shown until then) | Phase 3 |
| D7 | ~~Initialize git + branching model~~ | **Resolved:** git on `main`, **main-only workflow** (CLAUDE.md §10 / AGENTS.md Git Branch Policy); push once a remote is configured | — |
| D8 | Manifest signing (key outside DB) or external timestamping | Deferred; digests + append-only grants + manifest digest in exports (REPLAY_ENGINE §6) | Phase 5 security review |
| D9 | Replay equivalence margin `m` | 1.25 (±25% speedup drift); revisit after measuring same-machine replay variance in Phase 4 | Phase 4 exit |
| D10 | Retirement policy for old report builders/renderers | Keep all versions; fallback to stored artifacts if ever retired | Before first builder@2 |
