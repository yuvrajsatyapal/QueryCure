"""Transaction-scoped timeouts (Neon PgBouncer mode) must protect every transaction the app
opens, exactly as the startup-option form does on direct endpoints."""

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.db.engine import make_engine


def _engine(url: str, **kwargs: int) -> AsyncEngine:
    return make_engine(
        url, set_role="qc_app", pool_size=1, max_overflow=0, timeout_scope="transaction", **kwargs
    )


async def _show(conn, name: str) -> str:  # type: ignore[no-untyped-def]
    return (await conn.execute(text(f"SHOW {name}"))).scalar_one()


async def test_transaction_scope_applies_timeouts_inside_each_transaction(migrated_db: str) -> None:
    engine = _engine(migrated_db, statement_timeout_ms=1500, idle_in_transaction_timeout_ms=4000)
    try:
        async with engine.begin() as conn:
            assert await _show(conn, "statement_timeout") == "1500ms"
            assert await _show(conn, "idle_in_transaction_session_timeout") == "4s"
    finally:
        await engine.dispose()


async def test_transaction_scope_sends_no_startup_options(migrated_db: str) -> None:
    engine = _engine(migrated_db, statement_timeout_ms=1500)
    try:
        async with engine.connect() as conn:
            raw = await conn.get_raw_connection()
            assert "statement_timeout" not in (raw.driver_connection.info.options or "")  # type: ignore[union-attr]
    finally:
        await engine.dispose()


async def test_a_slow_statement_is_cancelled_by_the_server(migrated_db: str) -> None:
    engine = _engine(migrated_db, statement_timeout_ms=500)
    try:
        async with engine.begin() as conn:
            with pytest.raises(DBAPIError, match="statement timeout"):
                await conn.execute(text("SELECT pg_sleep(3)"))
    finally:
        await engine.dispose()


async def test_autobegin_connections_are_protected_too(migrated_db: str) -> None:
    engine = _engine(migrated_db, statement_timeout_ms=500)
    try:
        async with engine.connect() as conn:  # no explicit begin(): autobegin on first execute
            with pytest.raises(DBAPIError, match="statement timeout"):
                await conn.execute(text("SELECT pg_sleep(3)"))
    finally:
        await engine.dispose()


async def test_the_next_transaction_on_the_same_connection_is_protected_after_a_failure(
    migrated_db: str,
) -> None:
    """A retry after a timed-out transaction reuses the pooled connection: the timeout is
    re-armed per transaction, not carried (or lost) from the failed one."""
    engine = _engine(migrated_db, statement_timeout_ms=500)
    try:
        for _ in range(3):
            async with engine.begin() as conn:
                assert await _show(conn, "statement_timeout") == "500ms"
                with pytest.raises(DBAPIError, match="statement timeout"):
                    await conn.execute(text("SELECT pg_sleep(3)"))
    finally:
        await engine.dispose()


async def test_the_timeout_does_not_leak_to_the_session_after_commit(migrated_db: str) -> None:
    """SET LOCAL semantics: outside our transactions the connection keeps server defaults, which
    is what lets PgBouncer hand the same server connection to another client safely."""
    engine = _engine(migrated_db, statement_timeout_ms=500)
    try:
        async with engine.connect() as conn:
            raw = await conn.get_raw_connection()
            await conn.execute(text("SELECT 1"))
            await conn.commit()
            cur = await raw.driver_connection.execute("SHOW statement_timeout")  # type: ignore[union-attr]
            assert (await cur.fetchone()) == ("0",)
            await raw.driver_connection.rollback()  # type: ignore[union-attr]
    finally:
        await engine.dispose()


async def test_an_idle_open_transaction_is_terminated_by_the_server(migrated_db: str) -> None:
    engine = _engine(migrated_db, idle_in_transaction_timeout_ms=700)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            await asyncio.sleep(1.8)
            with pytest.raises(DBAPIError):
                await conn.execute(text("SELECT 1"))
    finally:
        await engine.dispose()


async def test_session_scope_still_uses_startup_options(migrated_db: str) -> None:
    engine = make_engine(
        migrated_db, set_role="qc_app", timeout_scope="session", statement_timeout_ms=1500
    )
    try:
        async with engine.connect() as conn:
            raw = await conn.get_raw_connection()
            assert "statement_timeout=1500" in (raw.driver_connection.info.options or "")  # type: ignore[union-attr]
            assert await _show(conn, "statement_timeout") == "1500ms"
    finally:
        await engine.dispose()
