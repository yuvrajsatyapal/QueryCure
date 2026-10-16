import datetime as dt
import secrets

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.api.deps import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    ConnDep,
    CurrentUser,
    OptionalUser,
    SettingsDep,
    hash_token,
)
from querycure.api.rate_limit import rate_limit
from querycure.api.schemas.session import Features, MeResponse, SessionResponse, UserOut
from querycure.core.config import Profile, Settings
from querycure.db.repositories import sessions, users
from querycure.domain.users import User

router = APIRouter(tags=["session"])
_MAX_USER_AGENT = 256


async def issue_session(
    conn: AsyncConnection, request: Request, response: Response, settings: Settings, user: User
) -> None:
    """A new opaque session token (stored hashed) and a fresh CSRF token, as cookies."""
    token = secrets.token_urlsafe(32)
    await sessions.create_session(
        conn,
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(seconds=settings.session_ttl_seconds),
        user_agent=(request.headers.get("user-agent") or "")[:_MAX_USER_AGENT] or None,
    )
    # HttpOnly session token; the CSRF token must stay readable by the web app (double submit).
    for name, value, httponly in (
        (SESSION_COOKIE, token, True),
        (CSRF_COOKIE, secrets.token_urlsafe(32), False),
    ):
        response.set_cookie(
            name,
            value,
            max_age=settings.session_ttl_seconds,
            path="/",
            domain=settings.cookie_domain,
            secure=settings.profile is not Profile.LOCAL,
            httponly=httponly,
            samesite="lax",
        )


@router.post(
    "/session",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("session_create"))],
)
async def create_session(
    request: Request,
    response: Response,
    conn: ConnDep,
    settings: SettingsDep,
    existing: OptionalUser,
) -> SessionResponse:
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return SessionResponse(user=UserOut.from_user(existing))
    if settings.profile is Profile.LOCAL:
        user = await users.get_or_create_local_user(conn)
    else:
        user = await users.create_anonymous_user(conn)
    await issue_session(conn, request, response, settings, user)
    return SessionResponse(user=UserOut.from_user(user))


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, conn: ConnDep, settings: SettingsDep) -> Response:
    """Revokes the session server-side and clears both cookies. Needs the CSRF token like any
    mutation, so another site cannot sign a user out. Idempotent."""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await sessions.revoke_session(conn, hash_token(token))
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(
            name,
            path="/",
            domain=settings.cookie_domain,
            secure=settings.profile is not Profile.LOCAL,
            httponly=name == SESSION_COOKIE,
            samesite="lax",
        )
    return response


@router.get("/me")
async def me(user: CurrentUser, settings: SettingsDep) -> MeResponse:
    live = settings.profile is Profile.LOCAL or settings.feature_live_inspection_public
    return MeResponse(
        user=UserOut.from_user(user),
        profile=settings.profile,
        features=Features(
            live_inspection=live,
            sandbox=bool(settings.feature_sandbox),
            github_login=settings.github_login_enabled,
        ),
    )
