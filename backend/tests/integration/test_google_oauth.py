"""Google sign-in (OpenID Connect authorization-code flow with state and PKCE) against a mocked
provider. The linking logic is shared with GitHub (test_github_oauth.py); these tests cover what
is Google-specific: endpoints and parameters, the profile mapping, provider isolation, and that
the two providers can be enabled independently."""

import base64
import os
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import httpx2
import psycopg
import pytest
from pydantic import SecretStr

from querycure.api.main import create_app
from querycure.auth.oauth import challenge
from querycure.core.config import Profile, Settings
from querycure.db.engine import make_engine

pytestmark = pytest.mark.integration
GOOGLE_TOKEN = "ya29." + "t0k3n" * 6


def settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "_env_file": None,
        "profile": Profile.DEMO,
        "allow_private_targets": False,
        "master_key": base64.b64encode(os.urandom(32)).decode(),
        "google_client_id": "1234.apps.googleusercontent.com",
        "google_client_secret": SecretStr("client-secret"),
        "public_api_url": "https://api.querycure.test",
        "web_base_url": "https://app.querycure.test",
    }
    return Settings(**{**base, **overrides})


class FakeGoogle:
    def __init__(self, sub: str = "110248495921238986420", name: str | None = "Ada L") -> None:
        self.sub, self.name = sub, name
        self.token_requests: list[dict[str, list[str]]] = []
        self.fail_token = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com" and request.url.path == "/token":
            form = parse_qs(request.content.decode())
            self.token_requests.append(form)
            if self.fail_token:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": GOOGLE_TOKEN, "token_type": "Bearer"})
        if request.url.host == "openidconnect.googleapis.com":
            assert request.headers["Authorization"] == f"Bearer {GOOGLE_TOKEN}"
            profile: dict[str, Any] = {"sub": self.sub}
            if self.name is not None:
                profile["name"] = self.name
            return httpx.Response(200, json=profile)
        return httpx.Response(404)


@pytest.fixture
async def make(migrated_db: str) -> AsyncIterator[Callable[..., Any]]:
    engines = []

    def build(fake: FakeGoogle, **overrides: Any) -> Any:
        engine = make_engine(migrated_db, set_role="qc_app")
        engines.append(engine)
        app = create_app(settings(**overrides), engine=engine)
        app.state.oauth_http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
        return app

    yield build
    for engine in engines:
        await engine.dispose()


COLLIDING_SUBJECT = "7777001"


@pytest.fixture(autouse=True)
def _fresh_state(owner: psycopg.Connection) -> Iterator[None]:
    owner.execute("DELETE FROM rate_limit_buckets")
    yield
    # The database is shared across the session: leave no OAuth accounts for other suites.
    owner.execute(
        "DELETE FROM users WHERE auth_provider = 'google' OR auth_subject = %s",
        (COLLIDING_SUBJECT,),
    )


async def browser(app: Any, address: str) -> httpx2.AsyncClient:
    transport = httpx2.ASGITransport(app=app, client=(address, 1), raise_app_exceptions=False)
    client = httpx2.AsyncClient(transport=transport, base_url="https://api.querycure.test")
    await client.post("/api/v1/session")
    client.headers["X-CSRF-Token"] = client.cookies["qc_csrf"]
    return client


async def sign_in(client: httpx2.AsyncClient, return_to: str = "/app/history") -> httpx2.Response:
    login = await client.get("/api/v1/auth/google/login", params={"return_to": return_to})
    assert login.status_code == 302
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    return await client.get("/api/v1/auth/google/callback", params={"code": "c0de", "state": state})


async def test_disabled_without_configuration(make: Callable[..., Any]) -> None:
    app = make(FakeGoogle(), google_client_id=None, google_client_secret=None)
    client = await browser(app, "203.0.113.70")
    try:
        r = await client.get("/api/v1/auth/google/login")
        me = await client.get("/api/v1/me")
    finally:
        await client.aclose()
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FEATURE_DISABLED"
    assert me.json()["features"]["google_login"] is False


async def test_providers_are_enabled_independently(make: Callable[..., Any]) -> None:
    app = make(FakeGoogle())  # Google configured, GitHub not
    client = await browser(app, "203.0.113.71")
    try:
        github = await client.get("/api/v1/auth/github/login")
        me = (await client.get("/api/v1/me")).json()
    finally:
        await client.aclose()
    assert github.status_code == 403
    assert me["features"]["google_login"] is True
    assert me["features"]["github_login"] is False


async def test_login_redirect_carries_state_and_pkce_and_sanitizes_return_to(
    make: Callable[..., Any],
) -> None:
    app = make(FakeGoogle())
    client = await browser(app, "203.0.113.72")
    try:
        r = await client.get("/api/v1/auth/google/login", params={"return_to": "//evil.example/x"})
    finally:
        await client.aclose()
    location = urlparse(r.headers["location"])
    query = parse_qs(location.query)
    assert (location.scheme, location.netloc) == ("https", "accounts.google.com")
    assert query["client_id"] == ["1234.apps.googleusercontent.com"]
    assert query["redirect_uri"] == ["https://api.querycure.test/api/v1/auth/google/callback"]
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["openid profile"]  # no email: QueryCure never asks for it
    assert query["code_challenge_method"] == ["S256"]
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "Path=/api/v1/auth/google" in cookie
    state, verifier, target = cookie.split("qc_oauth=")[1].split(";")[0].strip('"').split(".")
    assert query["state"] == [state]
    assert query["code_challenge"] == [challenge(verifier)]
    assert base64.urlsafe_b64decode(target).decode() == "/app"


async def test_state_mismatch_and_failed_exchange_never_sign_in(
    make: Callable[..., Any], owner: psycopg.Connection
) -> None:
    fake = FakeGoogle()
    app = make(fake)
    client = await browser(app, "203.0.113.73")
    try:
        await client.get("/api/v1/auth/google/login")
        forged = await client.get(
            "/api/v1/auth/google/callback", params={"code": "c", "state": "attacker"}
        )
        fake.fail_token = True
        failed = await sign_in(client)
        denied = await client.get("/api/v1/auth/google/callback", params={"error": "access_denied"})
        me = await client.get("/api/v1/me")
    finally:
        await client.aclose()
    assert forged.headers["location"].endswith("/app?auth_error=state_mismatch")
    assert failed.headers["location"].endswith("/app?auth_error=token_exchange_failed")
    assert denied.headers["location"].endswith("/app?auth_error=access_denied")
    assert me.json()["user"]["kind"] == "anonymous"
    assert owner.execute(
        "SELECT count(*) FROM users WHERE auth_provider = 'google'"
    ).fetchone() == (0,)


async def test_sign_in_converts_the_anonymous_user_and_stores_no_provider_token(
    make: Callable[..., Any], owner: psycopg.Connection
) -> None:
    fake = FakeGoogle()
    app = make(fake)
    client = await browser(app, "203.0.113.74")
    try:
        before = (await client.get("/api/v1/me")).json()["user"]
        old_token = client.cookies["qc_session"]
        done = await sign_in(client)
        client.headers["X-CSRF-Token"] = client.cookies["qc_csrf"]
        after = (await client.get("/api/v1/me")).json()["user"]
    finally:
        await client.aclose()
    assert done.headers["location"] == "https://app.querycure.test/app/history"
    assert client.cookies["qc_session"] != old_token
    assert after == {"id": before["id"], "kind": "oauth", "display_name": "Ada L"}
    form = fake.token_requests[0]
    assert form["grant_type"] == ["authorization_code"]
    assert form["code_verifier"]
    row = owner.execute(
        "SELECT auth_provider, auth_subject, email FROM users WHERE id = %s", (before["id"],)
    ).fetchone()
    assert row == ("google", "110248495921238986420", None)
    dump = owner.execute("SELECT string_agg(t::text, '') FROM (SELECT * FROM users) t").fetchone()
    assert dump is not None
    assert GOOGLE_TOKEN not in (dump[0] or "")


async def test_missing_name_falls_back_to_a_generic_label(make: Callable[..., Any]) -> None:
    app = make(FakeGoogle(name=None))
    client = await browser(app, "203.0.113.75")
    try:
        await sign_in(client)
        client.headers["X-CSRF-Token"] = client.cookies["qc_csrf"]
        me = (await client.get("/api/v1/me")).json()["user"]
    finally:
        await client.aclose()
    assert me["kind"] == "oauth"
    assert me["display_name"] == "Google user"


async def test_same_subject_on_two_providers_is_two_accounts(
    make: Callable[..., Any], owner: psycopg.Connection
) -> None:
    # A GitHub id and a Google sub that happen to be equal must not collide: the unique key
    # is (provider, subject), and accounts are never merged across providers by guesswork.
    app = make(
        FakeGoogle(sub=COLLIDING_SUBJECT),
        github_client_id="Iv1.client",
        github_client_secret=SecretStr("gh-secret"),
    )
    client = await browser(app, "203.0.113.76")
    try:
        await sign_in(client)
    finally:
        await client.aclose()
    owner.execute(
        "INSERT INTO users (kind, auth_provider, auth_subject, display_name) "
        "VALUES ('oauth', 'github', %s, 'octo')",
        (COLLIDING_SUBJECT,),
    )
    rows = owner.execute(
        "SELECT auth_provider FROM users WHERE auth_subject = %s ORDER BY 1", (COLLIDING_SUBJECT,)
    ).fetchall()
    assert rows == [("github",), ("google",)]
