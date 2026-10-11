# ADR-0004: PostgreSQL-backed job queue instead of Redis + Celery/Dramatiq in MVP

- Status: Accepted (2026-10-11)
- Area: Infrastructure

## Context
Investigations are long-running async jobs (minutes), low volume (tens/day on the demo), and must survive worker crashes. The stack already requires PostgreSQL; minimizing infrastructure cost is a goal.

## Alternatives
1. **Celery + Redis** — mature; sync-first worker model fights asyncio LangGraph code; adds Redis to deploy and pay for.
2. **Dramatiq + Redis** — simpler than Celery; still Redis; async support limited.
3. **arq (asyncio + Redis)** — async-native; Redis; smaller community.
4. **Postgres table + `FOR UPDATE SKIP LOCKED` + leases + `LISTEN/NOTIFY`** — no new infra; transactional enqueue with the state change; fits the DB-centric project.

## Decision
Option 4, implemented in `jobs/queue.py` (~200 lines) with leases, heartbeats, retries with backoff, dead-lettering, and dedupe keys.

## Rationale & trade-offs
- + Zero extra infrastructure; enqueue is atomic with run creation (no lost jobs between DB commit and broker publish).
- + Great interview topic (MVCC, row locks, SKIP LOCKED).
- − Polling + NOTIFY is less efficient at high throughput; irrelevant at our scale.
- − We own a small piece of infrastructure code; it must be well tested.

## Consequences
Revisit (new ADR) if throughput exceeds ~10 jobs/s or multiple services need the queue. Redis may still be added later for rate limiting or pub/sub fan-out.
