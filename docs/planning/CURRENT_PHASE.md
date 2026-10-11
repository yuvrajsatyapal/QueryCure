# Current Phase

| Field | Value |
|---|---|
| Phase | **1 — Foundation** (Phase 0 documentation complete) |
| Status | In progress: T1.1–T1.3 done on `main` |
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
- [ ] T1.4–T1.19 per [TASKS.md](TASKS.md).

## Blockers

- The Docker daemon is not running. `docker compose up` has not been executed; only `docker compose config` was checked. This is needed from T1.4 onward.

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
| Backend (through T1.3) | `uv run pytest -q` → 45 passed (3.12; CI also 3.13); `ruff check` and `ruff format --check` clean; `mypy` strict → no issues in 11 files; uvicorn smoke test: `/api/v1/healthz` 200, `/api/v1/openapi.json` 200 |
| Frontend (T1.1) | `pnpm lint` clean; `pnpm typecheck` clean; `pnpm test` → 1 passed; `pnpm build` → compiled, `/` prerendered static |
| Compose | `docker compose config` valid; **not started** (daemon down) |

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
