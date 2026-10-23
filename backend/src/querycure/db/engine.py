import re
from typing import Any, Literal
from urllib.parse import urlsplit

from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

_ROLE = re.compile(r"^[a-z_][a-z0-9_]*$")

TimeoutScope = Literal["auto", "session", "transaction"]

# Client-side libpq settings for every metadata connection (2026-10-18). Without keepalive
# settings the OS default (2 h idle on macOS) applied, so an await on a connection left
# half-open by a suspended Neon compute or a sleeping host hung, and so did worker shutdown.
# A dead peer is now noticed after ~30 s idle + 3 x 10 s probes; a connect attempt is bounded.
CONNECT_TIMEOUT_SECONDS = 10
KEEPALIVE = {"keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10,
             "keepalives_count": 3}  # fmt: skip


def is_pooled_url(url: str) -> bool:
    """Neon marks its PgBouncer endpoints with `-pooler` in the first host label."""
    host = urlsplit(url).hostname or ""
    return host.split(".", 1)[0].endswith("-pooler")


def resolve_timeout_scope(url: str, scope: TimeoutScope) -> Literal["session", "transaction"]:
    if scope == "auto":
        return "transaction" if is_pooled_url(url) else "session"
    return scope


def connect_args_for(
    scope: Literal["session", "transaction"],
    statement_timeout_ms: int | None,
    idle_in_transaction_timeout_ms: int | None,
) -> dict[str, Any]:
    """Transaction mode PgBouncer rejects any startup `options`, and a server connection is
    shared between clients, so a pooled engine sends none and disables prepared statements."""
    base: dict[str, Any] = {"connect_timeout": CONNECT_TIMEOUT_SECONDS, **KEEPALIVE}
    if scope == "transaction":
        return {**base, "prepare_threshold": None}
    options = " ".join(
        f"-c {name}={int(value)}"
        for name, value in (
            ("statement_timeout", statement_timeout_ms),
            ("idle_in_transaction_session_timeout", idle_in_transaction_timeout_ms),
        )
        if value is not None
    )
    return {**base, "options": options} if options else base


def async_url(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    raise ValueError("database URL must use the postgresql:// scheme")


def make_engine(
    url: str,
    *,
    set_role: str | None = None,
    pool_size: int = 5,
    max_overflow: int = 5,
    pool_timeout: float = 30.0,
    statement_timeout_ms: int | None = None,
    idle_in_transaction_timeout_ms: int | None = None,
    timeout_scope: TimeoutScope = "auto",
) -> AsyncEngine:
    """`set_role` is for tests: an owner connection running with exactly that role's privileges.

    The timeouts are server-enforced, not client-side. On direct endpoints they are startup
    options, so they hold for every connection even if application code forgets them. Pooled
    (PgBouncer) endpoints cannot take startup options, so there they are applied with
    `set_config(..., is_local => true)` as the first statement of every transaction the engine
    begins (explicit, autobegin, and each retry); they expire with that transaction, so nothing
    leaks into the shared server connection."""
    scope = resolve_timeout_scope(url, timeout_scope)
    engine = create_async_engine(
        async_url(url),
        pool_pre_ping=True,
        # Statement errors otherwise embed every bound value in str(exc), which reaches logs
        # through tracebacks (user SQL, ciphertext, token hashes). The SQL text stays.
        hide_parameters=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        connect_args=connect_args_for(scope, statement_timeout_ms, idle_in_transaction_timeout_ms),
    )
    if scope == "transaction":
        settings = [
            (name, int(value))
            for name, value in (
                ("statement_timeout", statement_timeout_ms),
                ("idle_in_transaction_session_timeout", idle_in_transaction_timeout_ms),
            )
            if value is not None
        ]
        if settings:
            # Integers only, so inlining them is injection-safe; one round trip per transaction.
            guard = "SELECT " + ", ".join(
                f"set_config('{name}', '{value}', true)" for name, value in settings
            )

            @event.listens_for(engine.sync_engine, "begin")
            def _apply_timeouts(connection: Connection) -> None:
                connection.exec_driver_sql(guard)

    if set_role is not None:
        if not _ROLE.match(set_role):
            raise ValueError("invalid role name")

        @event.listens_for(engine.sync_engine, "connect")
        def _apply_role(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute(f"SET ROLE {set_role}")
            cursor.close()
            # SET outside a committed transaction would be rolled back with the first transaction.
            dbapi_connection.commit()

    return engine
