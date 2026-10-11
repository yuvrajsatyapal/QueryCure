# ADR-0005: Server-Sent Events backed by a persisted, sequenced event log

- Status: Accepted (2026-10-11)
- Area: API

## Context
The UI shows live investigation progress; clients disconnect (mobile, deploys); report replay needs the full timeline.

## Alternatives
1. **WebSockets** — bidirectional; needs custom reconnect/resume; more complex auth and proxies.
2. **Polling** — simple; laggy and wasteful.
3. **SSE from an in-memory bus** — simple; loses events on restart; no replay.
4. **SSE from `investigation_events` with per-run `seq`, `Last-Event-ID` resume, `LISTEN/NOTIFY` wake-ups.**

## Decision
Option 4. Client→server actions (cancel, approve) are ordinary POSTs.

## Rationale & trade-offs
- + Resumable without gaps; the same log powers report replay and history.
- + `EventSource` handles reconnection; cookie auth works.
- − Every event is a DB write (fine at our volume; events are coarse-grained, no token streaming).
- − Each SSE connection holds an HTTP connection; NOTIFY listener is one shared DB connection per API process.

## Consequences
No token-by-token LLM streaming in MVP (agent summaries are emitted per step). Event schema is a public contract documented in API_DESIGN §3.
