import datetime as dt
import secrets

from fastapi import APIRouter, Request, Response, status

from querycure.api.deps import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    ConnDep,
    CurrentUser,
    OptionalUser,
    SettingsDep,
    hash_token,
)
from querycure.api.schemas.session import Features, MeResponse, SessionResponse, UserOut
from querycure.core.config import Profile
from querycure.db.repositories import sessions, users

router = APIRouter(tags=["session"])
_MAX_USER_AGENT = 256


@router.post("/session", status_code=status.HTTP_201_CREATED)
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
    return SessionResponse(user=UserOut.from_user(user))


@router.get("/me")
async def me(user: CurrentUser, settings: SettingsDep) -> MeResponse:
    live = settings.profile is Profile.LOCAL or settings.feature_live_inspection_public
    return MeResponse(
        user=UserOut.from_user(user),
        profile=settings.profile,
        features=Features(live_inspection=live, sandbox=bool(settings.feature_sandbox)),
    )
