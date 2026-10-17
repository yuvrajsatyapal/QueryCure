# ADR-0025: PgBouncer-compatible metadata connections (Neon pooler)

- Status: **Accepted** (2026-10-17, owner-requested fix after the first run against Neon)
- Area: Persistence / Operations
- Relates to: [ADR-0006](ADR-0006-metadata-schema-conventions.md), [DEPLOYMENT](../../architecture/DEPLOYMENT.md) §4, [SECURITY](../../architecture/SECURITY.md)

## Context

The metadata engine sent `statement_timeout` and `idle_in_transaction_session_timeout` as connection startup options. Neon's pooled endpoint (PgBouncer, transaction mode) rejects every startup option (`unsupported startup parameter in options`), so with the documented pooled `DATABASE_URL` the API reported `/readyz` 503 and the worker could not claim jobs. Two more paths relied on session state that a transaction pooler does not preserve: the LISTEN connection for SSE was opened from the engine URL, and the LangGraph checkpointer sets `search_path` as a startup option.

## Decision

1. **Timeout scope follows the endpoint.** `make_engine(timeout_scope="auto")` treats a host whose first label ends in `-pooler` as pooled.
   - **Direct endpoints** keep the startup options (server-enforced for every connection, even if code forgets).
   - **Pooled endpoints** send no startup options and disable psycopg's automatic prepared statements. The timeouts are applied with `set_config(name, value, true)` (transaction-local, same as `SET LOCAL`) in a SQLAlchemy `begin` hook, as the first statement of every transaction the engine begins: explicit `begin()`, autobegin, and every retry. They expire with the transaction, so nothing leaks into the shared server connection. Cost: one extra statement per transaction.
2. **Session-level work uses the direct endpoint.** The LISTEN hub and the checkpointer use `DATABASE_URL_DIRECT` (`Settings.direct_database_url()`, falling back to `DATABASE_URL` for single-endpoint setups such as local Docker).
3. **Fail fast on misconfiguration.** Settings reject a pooled `DATABASE_URL` without `DATABASE_URL_DIRECT`, and a pooled `DATABASE_URL_DIRECT`.
4. **Roles are unchanged.** `qc_app` and `qc_retention` stay non-owner, no-DDL roles; a security test pins their privileges (`tests/security/test_metadata_role_privileges.py`).

## Consequences

- Autocommit-isolation connections would bypass the hook. The codebase has none on the engine; the test suite exercises autobegin and explicit transactions.
- The `-pooler` hostname convention is Neon-specific. A different pooler needs `timeout_scope="transaction"` plumbed from config (not needed yet; a wrong guess fails loudly at connect time, never silently).
- A statement outside any transaction on a pooled connection (pool pre-ping `SELECT 1`) runs without the timeout; it is a constant query.
