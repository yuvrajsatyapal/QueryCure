import re
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

_ROLE = re.compile(r"^[a-z_][a-z0-9_]*$")


def async_url(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    raise ValueError("database URL must use the postgresql:// scheme")


def make_engine(url: str, *, set_role: str | None = None) -> AsyncEngine:
    """`set_role` is for tests: an owner connection running with exactly that role's privileges."""
    engine = create_async_engine(async_url(url), pool_pre_ping=True)
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
