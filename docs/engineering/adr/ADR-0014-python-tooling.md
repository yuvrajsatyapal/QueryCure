# ADR-0014: Python tooling — uv, ruff, mypy --strict, pytest, import-linter

- Status: Accepted (2026-10-11)
- Area: Engineering

## Context
Coding agents will write most code; fast, strict, deterministic tooling catches their mistakes early.

## Alternatives
- Packaging: pip + venv, Poetry, PDM, **uv** (fast, lockfile, Python version management).
- Lint/format: flake8 + black + isort, **ruff** (one fast tool).
- Types: pyright, **mypy --strict** (mature Pydantic plugin; pyright acceptable in editors).
- Architecture: **import-linter** contracts vs convention only.

## Decision
uv, ruff, mypy --strict (with Pydantic plugin), pytest + pytest-asyncio, import-linter. Frontend: pnpm, ESLint, TypeScript strict, Vitest, Playwright.

## Rationale & trade-offs
- + Fast feedback loops; layer rules enforced mechanically (e.g., `benchmark` cannot import `llm`).
- − mypy strictness slows early prototyping; acceptable for a project whose value is rigor.

## Consequences
CI runs all checks; `CLAUDE.md §7` lists the commands.
