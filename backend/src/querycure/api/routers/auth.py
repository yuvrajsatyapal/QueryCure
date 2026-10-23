"""OAuth sign-in (GitHub, Google) and account linking (T5.1, ADR-0013).

One flow serves every provider; a `Provider` supplies only its endpoints and credentials.

`GET /auth/<provider>/login` starts the authorization-code flow: a random `state` and a PKCE
verifier go into a short-lived HttpOnly cookie, and the browser is sent to GitHub.
`GET /auth/<provider>/callback` checks the state against the cookie (constant time), exchanges
the code, and links the account:

- no account yet, anonymous session: the anonymous user becomes the signed-in user (same
  row, so investigations, keys and uploads stay);
- an account exists for that (provider, subject): the anonymous user's data moves to it (keys
  re-encrypted for the account) and the anonymous user is retired;
- then the session is rotated (old token revoked, new token and CSRF cookie issued), so a
  token that existed before sign-in is useless afterwards.

Both endpoints are browser navigations (GET, no CSRF header possible); the state check is
the CSRF defence. Failures redirect to the web app with `?auth_error=<code>`.

While access is restricted (ADR-0031) the email scope is requested, and an account with no
verified address on ACCESS_ALLOWLIST is refused (`not_allowed`) before any row or session is
written. There are no anonymous users to link in that mode.
"""

import base64
import binascii
import hmac
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse

from querycure.api.deps import ConnDep, OptionalUser, SettingsDep, hash_token
from querycure.api.rate_limit import rate_limit
from querycure.api.routers.session import issue_session
from querycure.auth import access, github, google, oauth
from querycure.core.config import Profile, Settings
from querycure.core.errors import FeatureDisabledError
from querycure.core.logging import get_logger
from querycure.db.repositories import sessions, users
from querycure.domain.users import UserKind
from querycure.llm.credentials import move_credentials

log = get_logger(__name__)
OAUTH_COOKIE = "qc_oauth"
OAUTH_COOKIE_SECONDS = 600


@dataclass(frozen=True)
class Provider:
    name: str  # URL segment and the stored `users.auth_provider`
    label: str
    credentials: Callable[[Settings], tuple[str, str] | None]
    authorize_url: Callable[..., str]
    exchange: Callable[..., Awaitable[oauth.OAuthIdentity]]

    @property
    def cookie_path(self) -> str:
        return f"/api/v1/auth/{self.name}"


def _github_credentials(settings: Settings) -> tuple[str, str] | None:
    if settings.github_client_id is None or settings.github_client_secret is None:
        return None
    return settings.github_client_id, settings.github_client_secret.get_secret_value()


def _google_credentials(settings: Settings) -> tuple[str, str] | None:
    if settings.google_client_id is None or settings.google_client_secret is None:
        return None
    return settings.google_client_id, settings.google_client_secret.get_secret_value()


GITHUB = Provider("github", "GitHub", _github_credentials, github.authorize_url, github.exchange)
GOOGLE = Provider("google", "Google", _google_credentials, google.authorize_url, google.exchange)


def _redirect_uri(settings: Settings, provider: Provider) -> str:
    return f"{(settings.public_api_url or '').rstrip('/')}/api/v1/auth/{provider.name}/callback"


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


def _enabled(settings: Settings, provider: Provider) -> tuple[str, str]:
    credentials = provider.credentials(settings)
    if credentials is None:
        raise FeatureDisabledError(
            f"{provider.label} sign-in is not configured on this deployment."
        )
    return credentials


def _fail(settings: Settings, provider: Provider, code: str) -> RedirectResponse:
    log.info("oauth_failed", security=True, provider=provider.name, reason=code)
    response = RedirectResponse(_web(settings, f"/app?auth_error={code}"), status_code=302)
    response.delete_cookie(OAUTH_COOKIE, path=provider.cookie_path)
    return response


def _build_router(provider: Provider) -> APIRouter:
    router = APIRouter(prefix=f"/auth/{provider.name}", tags=["auth"])

    @router.get(
        "/login",
        dependencies=[Depends(rate_limit("session_create"))],
        operation_id=f"{provider.name}_login_api_v1_auth_{provider.name}_login_get",
    )
    async def login(
        settings: SettingsDep, return_to: Annotated[str | None, Query(max_length=300)] = None
    ) -> RedirectResponse:
        client_id, _ = _enabled(settings, provider)
        state, verifier = oauth.new_state(), oauth.new_verifier()
        target = base64.urlsafe_b64encode(_safe_return_to(return_to).encode()).decode()
        response = RedirectResponse(
            provider.authorize_url(
                client_id=client_id,
                redirect_uri=_redirect_uri(settings, provider),
                state=state,
                verifier=verifier,
                with_email=settings.restricted_access,
            ),
            status_code=302,
        )
        response.set_cookie(
            OAUTH_COOKIE,
            f"{state}.{verifier}.{target}",
            max_age=OAUTH_COOKIE_SECONDS,
            path=provider.cookie_path,
            secure=settings.profile is not Profile.LOCAL,
            httponly=True,
            samesite="lax",  # sent on the provider's top-level redirect back to us
        )
        return response

    @router.get(
        "/callback",
        operation_id=f"{provider.name}_callback_api_v1_auth_{provider.name}_callback_get",
    )
    async def callback(
        request: Request,
        conn: ConnDep,
        settings: SettingsDep,
        current: OptionalUser,
        code: Annotated[str | None, Query(max_length=200)] = None,
        state: Annotated[str | None, Query(max_length=200)] = None,
        error: Annotated[str | None, Query(max_length=100)] = None,
    ) -> Response:
        client_id, client_secret = _enabled(settings, provider)
        if error is not None:
            return _fail(settings, provider, "access_denied")
        parts = request.cookies.get(OAUTH_COOKIE, "").split(".")
        if len(parts) != 3 or not code or not state:
            return _fail(settings, provider, "state_missing")
        expected, verifier, target = parts
        if not hmac.compare_digest(expected.encode(), state.encode()):
            return _fail(settings, provider, "state_mismatch")
        try:
            return_to = _safe_return_to(base64.urlsafe_b64decode(target.encode()).decode())
        except (binascii.Error, UnicodeDecodeError):
            return_to = "/app"
        try:
            identity = await provider.exchange(
                _http(request),
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=_redirect_uri(settings, provider),
                code=code,
                verifier=verifier,
                with_email=settings.restricted_access,
            )
        except oauth.OAuthError as exc:
            return _fail(settings, provider, exc.code)
        email = access.approved_email(settings, identity)
        if settings.restricted_access and email is None:
            return _fail(settings, provider, "not_allowed")

        account = await users.find_oauth_user(
            conn, provider=provider.name, subject=identity.subject
        )
        # A restricted trial never links an anonymous session left over from open mode.
        linkable = current is not None and current.kind is UserKind.ANONYMOUS
        anonymous = current if linkable and not settings.restricted_access else None
        if account is None and anonymous is not None:
            account = await users.convert_to_oauth(
                conn, user_id=anonymous.id, provider=provider.name, subject=identity.subject,
                display_name=identity.display_name,
            )  # fmt: skip
        elif account is None:
            account = await users.create_oauth_user(
                conn,
                provider=provider.name,
                subject=identity.subject,
                display_name=identity.display_name,
                email=email,
            )
        else:
            account = await users.touch_oauth_user(conn, account.id, identity.display_name, email)
            if anonymous is not None and anonymous.id != account.id:
                await move_credentials(conn, settings, from_user=anonymous.id, to_user=account.id)
                await users.merge_user_data(conn, from_user=anonymous.id, to_user=account.id)
        old_token = request.cookies.get("qc_session")
        if old_token:
            await sessions.revoke_session(conn, hash_token(old_token))
        response = RedirectResponse(_web(settings, return_to), status_code=302)
        await issue_session(conn, request, response, settings, account)
        response.delete_cookie(OAUTH_COOKIE, path=provider.cookie_path)
        log.info(
            "oauth_signed_in", security=True, provider=provider.name, linked=anonymous is not None
        )
        return response

    return router


github_router = _build_router(GITHUB)
google_router = _build_router(GOOGLE)
