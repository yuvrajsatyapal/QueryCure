# Coding Standards

Applies from Phase 1. Tooling decisions: [ADR-0014](adr/ADR-0014-python-tooling.md).

## 1. Python

### Tooling
- Python 3.12; `uv` for env + lockfile; `ruff` (lint + format, line length 100); `mypy --strict`; `pytest` + `pytest-asyncio`; `import-linter` for layer contracts ([FILE_MAP §2](FILE_MAP.md#dependency-direction-enforced-by-import-linter-contract)).

### Types & models
- Every function fully annotated; no `Any` except at JSON boundaries (then narrow immediately via Pydantic).
- Pydantic v2 for all data crossing a boundary (API, LLM I/O, artifacts, jobs). `model_config = ConfigDict(extra="forbid", frozen=True)` for domain models unless mutation is required.
- `StrEnum` for statuses/kinds; values identical to DB `CHECK` lists. Never compare against string literals when an enum exists.
- `SecretStr` for passwords/keys; `.get_secret_value()` only at the point of use.
- Prefer `dataclass(slots=True)` for internal non-serialized structs (e.g., benchmark schedule).

### Async
- API and worker are async end to end: `psycopg` async connections, SQLAlchemy `AsyncSession`, `httpx.AsyncClient`.
- No blocking calls in async code; CPU-bound work (bootstrap with 2,000 resamples) runs via `asyncio.to_thread`.
- Bound concurrency with `asyncio.Semaphore`; use `asyncio.TaskGroup` for fan-out so failures cancel siblings.
- Always propagate `asyncio.CancelledError` (never catch-and-swallow); `except Exception` must not wrap `await` points that should be cancellable without re-raising `CancelledError`.
- Every external call has a timeout (`asyncio.timeout`).

### Errors
- Domain exceptions in `core/errors.py` (`QueryDoctorError` → `NotFound`, `InvalidState`, `SqlNotAllowed`, `TargetBlocked`, `BudgetExhausted`, `RunCancelled`…), each with a stable `code`.
- API maps exceptions to the error envelope in one middleware. No HTTP concerns below the router layer.
- Never `except:` bare; never swallow — log with context then re-raise or convert. Fallbacks must log.
- Retry only idempotent operations, with bounded attempts and jittered backoff (`tenacity` is not added; a 20-line helper in `core/retry.py` suffices).

### Logging
- `structlog` JSON; bind `request_id`, `user_id` (hashed), `investigation_id`, `run_id`, `node`, `agent`.
- Levels: `debug` dev-only detail, `info` lifecycle, `warning` degraded/fallback, `error` failed operation.
- Redaction processor mandatory; never log SQL parameter values from targets, prompts in full (log prompt hash + token counts), or secrets.

### Database
- Repositories are the only code that writes SQL against the metadata DB. Every user-scoped repository method takes `user_id`.
- Every select on soft-deletable tables filters `deleted_at IS NULL`.
- Multi-table writes in one transaction (`async with session.begin()`); events inserted in the same transaction as the state change they describe.
- Target/sandbox SQL lives in `.sql` template files or the benchmark engine; never f-strings with values. Identifiers via `psycopg.sql.Identifier`.

### Style
- Comments explain *why*. No docstrings that restate the name.
- Constants and thresholds in config/budget models, not magic numbers inline.
- Small modules; one public concept per module. Prefer functions over classes unless state is real.
- Named arguments for calls with ≥ 2 non-obvious parameters.

## 2. TypeScript / React

- `strict: true`, `noUncheckedIndexedAccess: true`. No `any`; use `unknown` + narrowing.
- API types generated from OpenAPI (`openapi-typescript`) into `lib/api/generated/` (snake_case, mirrors the wire). Resource modules convert to camelCase with a typed `toCamel`/`toSnake` (`CamelCasedPropertiesDeep` from `type-fest`) — conversion happens **only** in `lib/api/`.
- Server data → TanStack Query (query keys factory per resource); SSE events update the query cache via `setQueryData` (no refetch flashes). Client-only UI state → Zustand. Never duplicate server data in Zustand.
- Errors: surface `error.message` from the backend envelope; never the raw fetch error text. Every query has loading/empty/error rendering.
- Components: function components, props typed explicitly, no default exports except Next.js route files. Co-locate component tests.
- Styling: Tailwind with token classes only; `cn()` helper for conditional classes; no inline style except computed graph geometry.
- Accessibility: interactive elements are buttons/links (no clickable divs); labels for inputs; keyboard paths tested in Playwright.
- `pnpm lint && pnpm typecheck && pnpm build` before every commit touching `frontend/`.

## 3. Validation

- Validate at boundaries (API input, uploaded files, LLM output, artifacts on read). Trust validated domain objects internally.
- Size limits: SQL 100 KB, plan JSON 5 MB, DDL 1 MB, objective 2,000 chars; JSON nesting depth ≤ 64.

## 4. Testing conventions

- Test names describe behaviour: `test_validator_rejects_data_modifying_cte`.
- Arrange/act/assert; one behaviour per test; fixtures in `conftest.py` scoped narrowly.
- No network in unit tests (an autouse fixture blocks sockets). Integration tests use real Postgres.
- See [TESTING_STRATEGY.md](TESTING_STRATEGY.md).

## 5. Dependencies

Before adding a package: (1) can stdlib or an existing dependency do it? (2) is it maintained and widely used? (3) what does it pull in? Record non-trivial additions in the PR description; architecture-relevant ones get an ADR. Pin via lockfiles; Dependabot weekly.

## 6. Security in code

- Follow [SECURITY.md](../architecture/SECURITY.md). Any change to `sql/`, `connectors/`, `sandbox/`, `llm/credentials.py`, or `core/crypto.py` requires a matching security test change and reviewer attention.
- No `eval`/`exec`, no `pickle` for untrusted data, no `shell=True`. Docker operations through the Docker SDK with fixed arguments.

## 7. Git

- **Main only:** all work is committed directly to `main` (see *Git Branch Policy* in [CLAUDE.md](../../CLAUDE.md) and [AGENTS.md](../../AGENTS.md)). No feature branches or worktrees. Never force-push.
- Conventional commit messages (`feat(benchmark): add bootstrap CI`), referencing task IDs where applicable.
- Small PRs mapped to TASKS.md IDs (`T2.4`).
