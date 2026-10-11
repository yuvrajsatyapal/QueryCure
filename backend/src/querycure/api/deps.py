import hashlib
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from querycure.core.config import Settings
from querycure.core.errors import QueryCureError, UnauthenticatedError
from querycure.db.repositories import sessions
from querycure.domain.users import User

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


SettingsDep = Annotated[Settings, Depends(get_settings)]
ConnDep = Annotated[AsyncConnection, Depends(get_conn)]
CurrentUser = Annotated[User, Depends(current_user)]
OptionalUser = Annotated[User | None, Depends(optional_user)]
