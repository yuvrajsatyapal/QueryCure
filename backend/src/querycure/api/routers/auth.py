"""GitHub sign-in and account linking (T5.1, ADR-0013).

`GET /auth/github/login` starts the authorization-code flow: a random `state` and a PKCE
verifier go into a short-lived HttpOnly cookie, and the browser is sent to GitHub.
`GET /auth/github/callback` checks the state against the cookie (constant time), exchanges
the code, and links the GitHub account:

- no account yet, anonymous session: the anonymous user becomes the GitHub user (same row,
  so investigations, keys and uploads stay);
- an account exists: the anonymous user's data moves to it (keys re-encrypted for the
  account) and the anonymous user is retired;
- then the session is rotated (old token revoked, new token and CSRF cookie issued), so a
  token that existed before sign-in is useless afterwards.

Both endpoints are browser navigations (GET, no CSRF header possible); the state check is
the CSRF defence. Failures redirect to the web app with `?auth_error=<code>`.
"""

import base64
import binascii
import hmac
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse

from querycure.api.deps import ConnDep, OptionalUser, SettingsDep, hash_token
from querycure.api.rate_limit import rate_limit
from querycure.api.routers.session import issue_session
from querycure.auth import github
from querycure.core.config import Profile, Settings
from querycure.core.errors import FeatureDisabledError
from querycure.core.logging import get_logger
from querycure.db.repositories import sessions, users
from querycure.domain.users import UserKind
from querycure.llm.credentials import move_credentials

router = APIRouter(prefix="/auth/github", tags=["auth"])
log = get_logger(__name__)
OAUTH_COOKIE = "qc_oauth"
OAUTH_COOKIE_SECONDS = 600
PROVIDER = "github"


def _redirect_uri(settings: Settings) -> str:
    return f"{(settings.public_api_url or '').rstrip('/')}/api/v1/auth/github/callback"


def _safe_return_to(value: str | None) -> str:
    """Only same-site relative paths: no scheme, no host, no protocol-relative `//`."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/app"
    return value[:300]


def _web(settings: Settings, path: str) -> str:
    return f"{(settings.web_base_url or '').rstrip('/')}{path}"


def _http(request: Request) -> httpx.AsyncClient:
    client: httpx.AsyncClient | None = getattr(request.app.state, "oauth_http", None)
    if client is None:
        client = httpx.AsyncClient()
        request.app.state.oauth_http = client
    return client


def _enabled(settings: Settings) -> tuple[str, str]:
    if settings.github_client_id is None or settings.github_client_secret is None:
        raise FeatureDisabledError("GitHub sign-in is not configured on this deployment.")
    return settings.github_client_id, settings.github_client_secret.get_secret_value()


def _fail(settings: Settings, code: str) -> RedirectResponse:
    log.info("oauth_failed", security=True, reason=code)
    response = RedirectResponse(_web(settings, f"/app?auth_error={code}"), status_code=302)
    response.delete_cookie(OAUTH_COOKIE, path="/api/v1/auth/github")
    return response


@router.get("/login", dependencies=[Depends(rate_limit("session_create"))])
async def github_login(
    settings: SettingsDep, return_to: Annotated[str | None, Query(max_length=300)] = None
) -> RedirectResponse:
    client_id, _ = _enabled(settings)
    state, verifier = github.new_state(), github.new_verifier()
    target = base64.urlsafe_b64encode(_safe_return_to(return_to).encode()).decode()
    response = RedirectResponse(
        github.authorize_url(
            client_id=client_id,
            redirect_uri=_redirect_uri(settings),
            state=state,
            verifier=verifier,
        ),
        status_code=302,
    )
    response.set_cookie(
        OAUTH_COOKIE,
        f"{state}.{verifier}.{target}",
        max_age=OAUTH_COOKIE_SECONDS,
        path="/api/v1/auth/github",
        secure=settings.profile is not Profile.LOCAL,
        httponly=True,
        samesite="lax",  # sent on GitHub's top-level redirect back to us
    )
    return response


@router.get("/callback")
async def github_callback(
    request: Request,
    conn: ConnDep,
    settings: SettingsDep,
    current: OptionalUser,
    code: Annotated[str | None, Query(max_length=200)] = None,
    state: Annotated[str | None, Query(max_length=200)] = None,
    error: Annotated[str | None, Query(max_length=100)] = None,
) -> Response:
    client_id, client_secret = _enabled(settings)
    if error is not None:
        return _fail(settings, "access_denied")
    parts = request.cookies.get(OAUTH_COOKIE, "").split(".")
    if len(parts) != 3 or not code or not state:
        return _fail(settings, "state_missing")
    expected, verifier, target = parts
    if not hmac.compare_digest(expected.encode(), state.encode()):
        return _fail(settings, "state_mismatch")
    try:
        return_to = _safe_return_to(base64.urlsafe_b64decode(target.encode()).decode())
    except (binascii.Error, UnicodeDecodeError):
        return_to = "/app"
    try:
        identity = await github.exchange(
            _http(request),
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=_redirect_uri(settings),
            code=code,
            verifier=verifier,
        )
    except github.OAuthError as exc:
        return _fail(settings, exc.code)

    account = await users.find_oauth_user(conn, provider=PROVIDER, subject=identity.subject)
    anonymous = current if current is not None and current.kind is UserKind.ANONYMOUS else None
    if account is None and anonymous is not None:
        account = await users.convert_to_oauth(
            conn, user_id=anonymous.id, provider=PROVIDER, subject=identity.subject,
            display_name=identity.login,
        )  # fmt: skip
    elif account is None:
        account = await users.create_oauth_user(
            conn, provider=PROVIDER, subject=identity.subject, display_name=identity.login
        )
    else:
        await users.touch_oauth_user(conn, account.id, identity.login)
        if anonymous is not None and anonymous.id != account.id:
            await move_credentials(conn, settings, from_user=anonymous.id, to_user=account.id)
            await users.merge_user_data(conn, from_user=anonymous.id, to_user=account.id)
    old_token = request.cookies.get("qc_session")
    if old_token:
        await sessions.revoke_session(conn, hash_token(old_token))
    response = RedirectResponse(_web(settings, return_to), status_code=302)
    await issue_session(conn, request, response, settings, account)
    response.delete_cookie(OAUTH_COOKIE, path="/api/v1/auth/github")
    log.info("oauth_signed_in", security=True, linked=anonymous is not None)
    return response
