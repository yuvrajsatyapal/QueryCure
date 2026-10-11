# Phase 1 Report — Foundation

- **Dates:** 2026-10-11 → 2026-10-11 (UTC). First Phase 1 commit `d50260d` (T1.1); last commit before this report `93996f6` (T1.19).
- **Exit criteria met:** yes. All five ROADMAP Phase 1 acceptance criteria are met; evidence is in §5.
- **Tasks completed:** T1.1–T1.19 ([TASKS.md](../TASKS.md)).
- **Tasks deferred:**
  - T1.17's **param-sets editor** moves to Phase 2 (T2.12). Param sets are only consumed by the investigation-create request; in Phase 1 the editor would collect values that nothing uses.
  - **`import-linter` layer contracts** wait for their modules. The contracts name modules (`agents`, `benchmark`, `llm`) that don't exist yet, and the tool errors on missing modules.

## 1. What was implemented

**What a user can do today:**
- Start the stack locally from the README.
- Paste an `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` plan and explore it as an accessible tree table or a React Flow graph. Both views show loops-aware self time, per-loop misestimates stated in words, buffers, sort spills, and one labelled hottest node.
- Add a connection to their own PostgreSQL as a restricted role. A capability checklist states each result in words, and superuser connections are refused.
- Run a plain, never-executed `EXPLAIN` through that connection.
- Generate deterministic demo workloads.

**Not available yet:** LLM agents, benchmarks, and reports (Phases 2–4).

**Technical summary:**
- **Backend:** one Python 3.12 package with FastAPI and async SQLAlchemy/psycopg.
  - `core/`: settings, structlog with redaction, error envelope, AES-GCM `SecretBox`.
  - `sql/`: SQLGlot validator (fails closed), fingerprint, DDL parser.
  - `plans/`: parser with duplicate-key rejection; metrics with loop and parallel-worker correction.
  - `connectors/`: SSRF guard with pinned `hostaddr`; inspection gateway with hardened read-only sessions verified by reading the settings back; fixed catalog templates; capability checks; plain or `GENERIC_PLAN` EXPLAIN.
  - `replay/`: frozen canonicalization profiles and an append-only artifact store.
  - `workloads/`: 3 deterministic generators.
  - `api/`: cookie sessions, double-submit CSRF, body limit, request IDs.
- **Metadata DB:** Alembic `0001`–`0002` under ADR-0006 conventions. The `qc_app` role can only `INSERT`/`SELECT` on append-only tables.
- **Frontend:** Next.js 16 with Tailwind 4 tokens, light/dark themes, generated OpenAPI types, and case conversion only in `lib/api`.

## 2. Important architecture decisions

| Decision | ADR / doc updated | Why |
|---|---|---|
| Canonicalization profiles, digest = SHA-256(profile ‖ LF ‖ bytes); artifacts stored as `BYTEA` | ADR-0015, REPLAY_ENGINE, DATABASE_DESIGN | JSONB/TEXT re-serialize, which breaks byte-exact replay |
| `qc_app` restricted to INSERT/SELECT on artifacts; tests run under `SET ROLE` | DATABASE_DESIGN §5, TESTING_STRATEGY | Append-only must be enforced by the DB, not only by convention |
| Plain ASGI middlewares instead of `BaseHTTPMiddleware` | API_DESIGN | `BaseHTTPMiddleware` turned an over-limit body into a 500 |
| Plan uploads allow JSON depth 256 (others stay at 64) | CODING_STANDARDS §3 | Plan JSON nests two levels per node; deep join trees are legitimate |
| `GENERIC_PLAN` only for `$n` queries on PG16+ | BENCHMARK_ENGINE §11, SECURITY §4.3 | Plain EXPLAIN can't plan parameterized SQL |
| Connect failures map to fixed reason codes; only post-network failures are explained to the user | SECURITY §5.3 | Actionable errors (auth, TLS) without a port-scanning oracle or leaking libpq text |
| Plan table compares estimated and actual rows **per loop** | UI_UX (via T1.17 fix) | Matches EXPLAIN; totals moved to node details and graph edges |
| Main-only Git workflow | CLAUDE.md, AGENTS.md, CODING_STANDARDS §7 | User policy |

## 3. Files changed

| Area | Files / modules | Notes |
|---|---|---|
| CI / infra | `.github/workflows/ci.yml`, `infra/docker/compose.yaml`, `infra/docker/metadata-init/01-roles.sh` | Backend 3.12/3.13, PG17 integration job, frontend; sandbox on an internal network |
| Backend core | `core/{config,errors,crypto,logging,redaction,ids}.py` | |
| Persistence | `migrations/versions/0001_baseline.py`, `0002_single_local_user.py`, `db/engine.py`, `db/repositories/*` | |
| Parsing | `sql/{parser,validator,fingerprint,ddl}.py`, `plans/{models,parser,metrics}.py` | |
| Connectors | `connectors/{ssrf_guard,inspection_gateway,models}.py`, `catalog_queries/*.sql` | |
| Replay contracts | `replay/canonical/*`, `replay/digest.py`, `replay/artifact_store.py` | Golden vectors in `tests/fixtures/canonical` |
| Workloads | `workloads/{registry,loader,__main__}.py` | |
| API | `api/{main,middleware,deps,export_openapi}.py`, `api/routers/*`, `api/schemas/*` | |
| Frontend | `app/**`, `components/{layout,theme,common,connections,editor,plan,workspace}`, `lib/{api,plan,format}` | |
| Docs | README, CURRENT_PHASE, TASKS, ROADMAP, SECURITY, API_DESIGN, DATABASE_DESIGN, DEPLOYMENT, BENCHMARK_ENGINE, TESTING_STRATEGY, CODING_STANDARDS, LEARNING | |

## 4. Tests executed

Run on 2026-10-11 against PostgreSQL 17.11 in the compose `metadata-db`, with Python 3.12.

| Suite | Command | Result | Notes |
|---|---|---|---|
| Unit | `uv run pytest tests/unit -q` | 274 passed | Sockets blocked |
| Security | `uv run pytest tests/security -q` | 85 passed | 70 SSRF, 15 validator evasion |
| Integration | `uv run pytest tests/integration -q` | 89 passed | Migrations, grants, session API, artifact store, gateway, connections/inspect/workloads APIs |
| All backend | `uv run pytest -q` | 448 passed | `-m "not integration"` 359 + `-m integration` 89 |
| Static | `ruff check .`, `ruff format --check .`, `mypy src` (strict) | clean; mypy clean on 57 files | |
| Evals | — | not applicable | No agents in Phase 1 |
| Frontend | `pnpm lint && pnpm typecheck && pnpm test && pnpm build` | lint/types clean; 41 tests passed in 11 files; build compiles | Vitest + Testing Library |
| CI | GitHub Actions `ci.yml` on every push to `main` | green through T1.19 (`93996f6`) | backend 3.12/3.13, PG 17 integration, frontend |

## 5. Acceptance criteria

| Criterion (from ROADMAP) | Status | Evidence |
|---|---|---|
| 1. Validator unit suite passes, including fail-closed on unparseable input | Met | `tests/unit/sql` 92 passed (incl. `test_unparseable_input_fails_closed`, `test_empty_input_fails_closed`); `tests/security/test_sql_validator_evasion.py` 15 passed |
| 2. A PG 17 `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` upload renders a tree with correct loops-aware self times | Met | `tests/unit/plans` 37 passed (incl. `test_loops_multiply_inner_side_of_nested_loop`, `test_parallel_nodes_divide_loops_by_process_count`, real `pg17_*.json` fixtures). Browser checks: Seq Scan on orders 62.6 ms (91.1%) under Gather Merge; join fixture Hash Join self 23.4 ms = 41.617 − 18.077 − 0.142 |
| 3. A restricted-role connection to `orders_ecommerce` returns capabilities and a plain EXPLAIN; a superuser connection is refused | Met | Integration tests `test_capabilities_of_restricted_role`, `test_explain_returns_plain_plan_without_executing`, `test_superuser_connections_are_refused`. Browser: `qc_demo_inspector` → `LAST TEST: OK` with the checklist; Live EXPLAIN rendered with the estimates-only banner |
| 4. All private/loopback/metadata forms blocked in the `demo` profile | Met | `tests/security/test_ssrf_guard.py` 70 passed (`test_non_public_addresses_are_blocked`, `test_localhost_blocked_in_public_profile`, `test_ambiguous_numeric_hosts_are_rejected`, `test_dns_is_resolved_exactly_once_so_rebinding_cannot_swap_the_address`, …). Settings refuse `ALLOW_PRIVATE_TARGETS=true` with `QC_PROFILE=demo` |
| 5. `docker compose up` + `pnpm dev` gives a working UI on a fresh clone following the README | Met | Fresh clone under Compose project `qdfresh` with an empty volume, following README steps 1–6 literally (CURRENT_PHASE T1.19). The run found the TLS-default gap, which is now documented, and a better error message was added |

## 6. Known limitations

- **No agents, investigations, benchmarks, or reports.** "Start investigation" is disabled and says so.
- **No param-sets editor** (deferred to T2.12).
- **Mobile workspace:** below `md` the workspace stacks into one column. The UI_UX §3.4 mobile tab layout waits for the Phase 2 panels. After a viewport resize the graph keeps its zoom until the fit-view control is pressed.
- **Local TLS:** the compose metadata server has no TLS, so local demo connections need `TLS = disable`, which the local profile allows.
- **Shared server:** the demo database lives on the metadata server for convenience. These are separate databases, but not separate servers.
- **Single local user** only. GitHub OAuth arrives in Phase 5.
- **`import-linter` not configured** (see deferred tasks above).
- **Dev tooling:** running `pnpm build` while `pnpm dev` is up left the dev server serving stale CSS until it was restarted.

## 7. Security considerations

**Controls in place, each with negative tests:**
- **L1 validator:** fails closed; full-tree walk catches data-modifying CTEs hidden under a SELECT root.
- **L2 gateway operation allowlist.**
- **L3 hardened read-only session:** settings are read back, and `test_read_only_session_holds_even_if_validator_is_bypassed` covers the "validator bypassed" case.
- **L4 role refusal:** superuser, CREATEROLE, and BYPASSRLS roles are refused.
- **L5 SSRF guard:** resolves once, pins `hostaddr`, blocks private ranges in the demo profile.

**Credentials and sessions:**
- Credentials are sealed with AES-GCM, bound to table/row/user AAD, and wiped on soft delete.
- Cookie sessions are HttpOnly, with double-submit CSRF.
- A 6 MB body limit is enforced before parsing.
- Redacted logs: connect failures log only the error class and a fixed reason code.

**Residual risks:**
- The SQLGlot grammar may diverge from PostgreSQL; L3–L5 are the real boundary.
- Plan-time evaluation of immutable functions (SECURITY §4.3).
- The demo DB shares a server with metadata, in local development only.

**Needs review before the public demo:**
- Mode B stays disabled there by default (SECURITY §5.4).
- Rate limits and per-user connection caps are not built yet.

## 8. What I should study

See [LEARNING.md Phase 1](../../engineering/LEARNING.md#phase-1--foundation).

1. `backend/src/querycure/plans/metrics.py` — self time = inclusive × loops − children, and the parallel correction that divides loops by process count.
2. `backend/src/querycure/sql/validator.py` — why the walk covers the whole tree, and identifier folding (`_pg_name`).
3. `backend/src/querycure/connectors/ssrf_guard.py` — resolve once, check every answer, pin `hostaddr`.
4. `backend/src/querycure/connectors/inspection_gateway.py` — hardened session verified by reading settings back, capability refusal, connect-failure classification.
5. `backend/src/querycure/replay/canonical/json_v1.py` + `digest.py` — RFC 8785 and profile-tagged digests.
6. `backend/migrations/versions/0001_baseline.py` — grants as the enforcement of append-only tables.
7. `frontend/src/components/plan/PlanTreeTable.tsx` — treegrid keyboard model (roving tabindex).
8. `frontend/src/lib/plan/layout.ts` — dagre centre → top-left conversion; log-scaled edges.

## 9. Interview-relevant implementation details

1. **A loops bug that looked right.** The plan table showed per-loop estimates next to all-loops actual rows (Seq Scan: 4,333 vs 10,014 under 3 loops). That suggested a 2.3× underestimate while the ratio column correctly said 1.3× over. Caught in the browser against a real PG 17 plan, not in tests. Fixed test-first by making both columns per loop and moving totals to node details and graph edges.
2. **A fresh-clone test found what unit tests couldn't.** Following the README literally, the default `verify-full` TLS failed against the TLS-less compose server with only "Could not connect". libpq doesn't return a SQLSTATE at connect time, so the gateway now classifies the message into fixed reason codes. It explains auth, database, and TLS failures, keeps refused/timeout generic (no port-scanning oracle), and never logs libpq's text. The classifier was checked against real libpq output.
3. **Append-only enforced by the database.** `qc_app` has no UPDATE/DELETE on artifacts, and integration tests run under `SET ROLE qc_app`. A side effect: `/readyz` returned 503 until migration `0002` granted SELECT on `alembic_version`.
4. **Correlated hashes in a "random" generator.** Salted multiplicative hashes left the hot customer with 5 orders instead of about 100. Switching to an md5 mix fixed the skew. Checksums are identical across independent loads and across the f-string → `psycopg.sql` rewrite.
5. **Framework failure modes.** Starlette's `BaseHTTPMiddleware` converted a 413 into a 500, so the middlewares became plain ASGI. Next 16's instant-navigation validation needs `instant = false` on each session-gated page, not only the layout.

## 10. Remaining work

- **Phase 2** starts only on the user's go-ahead: T2.1–T2.14, plus the param-sets editor in T2.12.
- **Add `import-linter` contracts** as `agents`, `llm`, and `benchmark` modules land.
- **Before enabling Mode B publicly:** rate limits and per-user connection caps (SECURITY §5.4).
- **RISKS.md:** no new risks beyond those listed. The local-TLS onboarding friction is mitigated by the README and the new error hint.
