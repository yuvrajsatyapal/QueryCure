# ADR-0001: Modular monolith with separate API and worker processes

- Status: Accepted (2026-10-11)
- Area: Architecture

## Context
One developer, AI-assisted, building a portfolio-grade system with long-running LLM + benchmark work, streaming progress, and strict security boundaries. Deployment budget is near zero.

## Alternatives
1. **Microservices** (API, agent service, benchmark service) — clear isolation, but multiplies deploys, auth between services, and failure modes.
2. **Single process** (API runs graphs in background tasks) — simplest, but long CPU/I/O work competes with request latency and dies with the web process.
3. **Modular monolith, two processes** — one package, `api` and `worker` entrypoints, communicating through the metadata DB.

## Decision
Option 3. Module boundaries enforced by `import-linter` contracts ([FILE_MAP](../FILE_MAP.md)). The worker can run embedded in the API container for the demo profile.

## Rationale & trade-offs
- + One codebase, one image, shared domain models, simple local dev.
- + Request path stays fast; workers can scale independently later.
- − Process boundary still requires a queue and event channel (ADR-0004, ADR-0005).
- − Embedded mode on the demo shares CPU with the API (acceptable at demo scale).

## Consequences
Benchmark/sandbox and agent code never run in the API process in the local profile; `api` must not import `agents`.
