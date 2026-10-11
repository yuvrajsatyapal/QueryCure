"""LangGraph checkpointer in schema `langgraph` (tables created by migration 0004).

The serializer is strict: it only revives LangGraph's own safe types, never arbitrary
classes named in checkpoint data. Graph state is JSON-only (agents/state.py), so nothing
else is needed. setup() is never called: the app role cannot run DDL.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

POOL_MAX_SIZE = 4


def strict_serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=None)


@asynccontextmanager
async def open_checkpointer(
    url: str, *, role: str | None = None
) -> AsyncIterator[AsyncPostgresSaver]:
    """`url` is a plain postgresql:// URL for the app role. `role` is for tests: an owner
    connection that runs with exactly that role's privileges."""
    options = "-c search_path=langgraph" + (f" -c role={role}" if role else "")
    async with AsyncConnectionPool(
        url,
        max_size=POOL_MAX_SIZE,
        open=False,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
            "options": options,
        },
    ) as pool:
        yield AsyncPostgresSaver(pool, serde=strict_serializer())  # type: ignore[arg-type]
