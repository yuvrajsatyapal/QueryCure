import hashlib
from collections.abc import AsyncIterator
from typing import Annotated, Any

import psycopg
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from querycure.core.config import Settings
from querycure.core.errors import QueryCureError, UnauthenticatedError
from querycure.db.engine import CONNECT_TIMEOUT_SECONDS, KEEPALIVE
from querycure.db.repositories import sessions
from querycure.domain.users import User
from querycure.events.hub import EventHub

SESSION_COOKIE = "qc_session"
CSRF_COOKIE = "qc_csrf"


class DatabaseUnavailableError(QueryCureError):
    code = "SERVICE_UNAVAILABLE"
    status = 503


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_engine(request: Request) -> AsyncEngine:
    engine: AsyncEngine | None = request.app.state.engine
    if engine is None:
        raise DatabaseUnavailableError("Database is not configured.")
    return engine


async def get_conn(
    engine: Annotated[AsyncEngine, Depends(get_engine)],
) -> AsyncIterator[AsyncConnection]:
    async with engine.begin() as conn:
        yield conn


async def optional_user(
    request: Request, conn: Annotated[AsyncConnection, Depends(get_conn)]
) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return await sessions.get_session_user(conn, hash_token(token))


async def current_user(user: Annotated[User | None, Depends(optional_user)]) -> User:
    if user is None:
        raise UnauthenticatedError("Sign in to continue.")
    return user


async def stream_user(
    request: Request, engine: Annotated[AsyncEngine, Depends(get_engine)]
) -> User:
    """Like current_user, but its transaction ends before a streaming response starts.

    Yield-dependencies such as get_conn stay open until the response finishes, which for an
    SSE stream would hold an idle transaction for the stream's whole lifetime.
    """
    token = request.cookies.get(SESSION_COOKIE)
    user = None
    if token:
        async with engine.begin() as conn:
            user = await sessions.get_session_user(conn, hash_token(token))
    if user is None:
        raise UnauthenticatedError("Sign in to continue.")
    return user


def listen_url(settings: Settings, engine: AsyncEngine) -> str:
    """LISTEN needs a session-level connection, so it never goes through the pooler. Tests that
    inject an engine without a configured URL fall back to the engine's own."""
    return settings.direct_database_url() or engine.url.set(
        drivername="postgresql"
    ).render_as_string(hide_password=False)


def get_event_hub(
    request: Request,
    engine: Annotated[AsyncEngine, Depends(get_engine)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> EventHub:
    hub: EventHub | None = request.app.state.event_hub
    if hub is None:
        # LISTEN needs no table privileges; a plain psycopg connection.
        url = listen_url(settings, engine)

        async def connect() -> psycopg.AsyncConnection:
            # Keepalives: a half-open LISTEN connection would silently stop live updates.
            libpq: dict[str, Any] = {"connect_timeout": CONNECT_TIMEOUT_SECONDS, **KEEPALIVE}
            return await psycopg.AsyncConnection.connect(url, autocommit=True, **libpq)

        hub = EventHub(connect)
        request.app.state.event_hub = hub
    return hub


SettingsDep = Annotated[Settings, Depends(get_settings)]
EngineDep = Annotated[AsyncEngine, Depends(get_engine)]
StreamUser = Annotated[User, Depends(stream_user)]
HubDep = Annotated[EventHub, Depends(get_event_hub)]
ConnDep = Annotated[AsyncConnection, Depends(get_conn)]
CurrentUser = Annotated[User, Depends(current_user)]
OptionalUser = Annotated[User | None, Depends(optional_user)]
