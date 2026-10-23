"""Restricted trial access (ADR-0031): with RESTRICTED_ACCESS on, no anonymous session is created
and only OAuth accounts with a provider-verified email on ACCESS_ALLOWLIST are admitted, checked
on every request so that removing an address revokes access. Mocked Google and GitHub."""

import base64
import os
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import httpx2
import psycopg
import pytest
from pydantic import SecretStr

from querycure.api.main import create_app
from querycure.core.config import Profile, Settings
from querycure.db.engine import make_engine

pytestmark = pytest.mark.integration
TOKEN = "ya29." + "t0k3n" * 6
APPROVED = "ada@example.com"
STRANGER = "mallory@example.com"
MASTER_KEY = base64.b64encode(os.urandom(32)).decode()


def settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "_env_file": None,
        "profile": Profile.DEMO,
        "allow_private_targets": False,
        "master_key": MASTER_KEY,
        "google_client_id": "1234.apps.googleusercontent.com",
        "google_client_secret": SecretStr("client-secret"),
        "github_client_id": "Iv1.client",
        "github_client_secret": SecretStr("client-secret"),
        "public_api_url": "https://api.querycure.test",
        "web_base_url": "https://app.querycure.test",
        "restricted_access": True,
        "access_allowlist": [APPROVED],
    }
    return Settings(**{**base, **overrides})


class FakeProviders:
    """Google userinfo and GitHub /user + /user/emails, with configurable emails."""

    def __init__(self) -> None:
        self.google_sub = f"g-{uuid.uuid4().hex}"
        self.google_email: str | None = APPROVED
        self.google_verified = True
        self.github_id = int(uuid.uuid4().int % 10**9)
        self.github_emails: list[dict[str, Any]] = [
            {"email": APPROVED, "verified": True, "primary": True}
        ]
        self.email_requests = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if (host, path) in (("oauth2.googleapis.com", "/token"),
                            ("github.com", "/login/oauth/access_token")):  # fmt: skip
            return httpx.Response(200, json={"access_token": TOKEN, "token_type": "bearer"})
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        if host == "openidconnect.googleapis.com":
            profile: dict[str, Any] = {"sub": self.google_sub, "name": "Ada"}
            if self.google_email is not None:
                profile |= {"email": self.google_email, "email_verified": self.google_verified}
            return httpx.Response(200, json=profile)
        if path == "/user":
            return httpx.Response(200, json={"id": self.github_id, "login": "ada"})
        if path == "/user/emails":
            self.email_requests += 1
            return httpx.Response(200, json=self.github_emails)
        return httpx.Response(404)


@pytest.fixture
async def make(migrated_db: str) -> AsyncIterator[Callable[..., Any]]:
    engines = []

    def build(fake: FakeProviders, **overrides: Any) -> Any:
        engine = make_engine(migrated_db, set_role="qc_app")
        engines.append(engine)
        app = create_app(settings(**overrides), engine=engine)
        app.state.oauth_http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
        return app

    yield build
    for engine in engines:
        await engine.dispose()


@pytest.fixture(autouse=True)
def _fresh_state(owner: psycopg.Connection) -> Iterator[None]:
    owner.execute("DELETE FROM rate_limit_buckets")
    yield
    owner.execute("DELETE FROM users WHERE auth_provider IN ('google', 'github')")


def browser(app: Any, address: str) -> httpx2.AsyncClient:
    transport = httpx2.ASGITransport(app=app, client=(address, 1), raise_app_exceptions=False)
    return httpx2.AsyncClient(transport=transport, base_url="https://api.querycure.test")


async def sign_in(client: httpx2.AsyncClient, provider: str) -> httpx2.Response:
    login = await client.get(f"/api/v1/auth/{provider}/login", params={"return_to": "/app"})
    assert login.status_code == 302
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    return await client.get(
        f"/api/v1/auth/{provider}/callback", params={"code": "c0de", "state": state}
    )


def count_users(owner: psycopg.Connection) -> int:
    row = owner.execute("SELECT count(*) FROM users WHERE deleted_at IS NULL").fetchone()
    assert row is not None
    return int(row[0])


def assert_no_list_leak(response: httpx2.Response) -> None:
    for entry in (APPROVED, STRANGER):
        assert entry not in response.text
        assert entry not in response.headers.get("location", "")


# --- anonymous ------------------------------------------------------------------------------


async def test_no_anonymous_session_is_created(
    make: Callable[..., Any], owner: psycopg.Connection
) -> None:
    before = count_users(owner)
    async with browser(make(FakeProviders()), "203.0.113.80") as client:
        created = await client.post("/api/v1/session")
        me = await client.get("/api/v1/me")
        listing = await client.get("/api/v1/investigations")
    assert created.status_code == 403
    assert created.json()["error"]["code"] == "ACCESS_DENIED"
    assert "qc_session" not in created.cookies
    assert me.status_code == 401
    assert listing.status_code == 401
    assert count_users(owner) == before
    assert_no_list_leak(created)


async def test_an_anonymous_session_from_before_the_restriction_is_refused(
    make: Callable[..., Any],
) -> None:
    open_app = make(FakeProviders(), restricted_access=False, access_allowlist=[])
    async with browser(open_app, "203.0.113.81") as client:
        assert (await client.post("/api/v1/session")).status_code == 201
        cookies = client.cookies
    async with browser(make(FakeProviders()), "203.0.113.81") as client:
        client.cookies = cookies
        client.headers["X-CSRF-Token"] = cookies["qc_csrf"]
        me = await client.get("/api/v1/me")
        stream = await client.get(f"/api/v1/runs/{uuid.uuid4()}/events")
        again = await client.post("/api/v1/session")
    assert me.status_code == 401
    assert stream.status_code == 401
    assert again.status_code == 403  # an existing anonymous session is not handed back


async def test_auth_options_are_public_and_reveal_no_list(make: Callable[..., Any]) -> None:
    async with browser(make(FakeProviders()), "203.0.113.82") as client:
        r = await client.get("/api/v1/auth/options")
    assert r.status_code == 200
    assert r.json() == {"restricted_access": True, "github_login": True, "google_login": True}
    assert_no_list_leak(r)


# --- approved -------------------------------------------------------------------------------


@pytest.mark.parametrize("provider", ["google", "github"])
async def test_an_approved_account_is_admitted(
    make: Callable[..., Any], owner: psycopg.Connection, provider: str
) -> None:
    async with browser(make(FakeProviders()), "203.0.113.83") as client:
        callback = await sign_in(client, provider)
        client.headers["X-CSRF-Token"] = client.cookies["qc_csrf"]
        me = await client.get("/api/v1/me")
        listing = await client.get("/api/v1/investigations")
    assert callback.status_code == 302
    assert callback.headers["location"] == "https://app.querycure.test/app"
    assert me.status_code == 200
    assert me.json()["user"]["kind"] == "oauth"
    assert "email" not in me.json()["user"]  # never returned by the API
    assert listing.status_code == 200
    row = owner.execute("SELECT email FROM users WHERE auth_provider = %s", (provider,)).fetchone()
    assert row == (APPROVED,)


async def test_matching_is_case_insensitive(make: Callable[..., Any]) -> None:
    fake = FakeProviders()
    fake.google_email = "Ada@Example.COM"
    async with browser(make(fake), "203.0.113.84") as client:
        callback = await sign_in(client, "google")
    assert callback.headers["location"] == "https://app.querycure.test/app"


async def test_github_admits_any_verified_address(make: Callable[..., Any]) -> None:
    fake = FakeProviders()
    fake.github_emails = [
        {"email": STRANGER, "verified": True, "primary": True},
        {"email": APPROVED, "verified": True, "primary": False},
    ]
    async with browser(make(fake), "203.0.113.85") as client:
        callback = await sign_in(client, "github")
    assert callback.headers["location"] == "https://app.querycure.test/app"


async def test_restricted_sign_in_requests_the_email_scopes(make: Callable[..., Any]) -> None:
    async with browser(make(FakeProviders()), "203.0.113.86") as client:
        google = await client.get("/api/v1/auth/google/login")
        github = await client.get("/api/v1/auth/github/login")
    assert parse_qs(urlparse(google.headers["location"]).query)["scope"] == ["openid email profile"]
    assert parse_qs(urlparse(github.headers["location"]).query)["scope"] == ["read:user user:email"]


# --- unapproved -----------------------------------------------------------------------------


async def _refused(app: Any, provider: str, owner: psycopg.Connection) -> None:
    before = count_users(owner)
    async with browser(app, "203.0.113.87") as client:
        callback = await sign_in(client, provider)
        me = await client.get("/api/v1/me")
    assert callback.status_code == 302
    assert callback.headers["location"] == "https://app.querycure.test/app?auth_error=not_allowed"
    assert "qc_session" not in callback.cookies
    assert me.status_code == 401
    assert count_users(owner) == before  # no account row for a refused sign-in
    assert_no_list_leak(callback)


@pytest.mark.parametrize("provider", ["google", "github"])
async def test_an_unlisted_account_is_refused(
    make: Callable[..., Any], owner: psycopg.Connection, provider: str
) -> None:
    fake = FakeProviders()
    fake.google_email = STRANGER
    fake.github_emails = [{"email": STRANGER, "verified": True, "primary": True}]
    await _refused(make(fake), provider, owner)


@pytest.mark.parametrize("provider", ["google", "github"])
async def test_a_listed_but_unverified_email_is_refused(
    make: Callable[..., Any], owner: psycopg.Connection, provider: str
) -> None:
    fake = FakeProviders()
    fake.google_verified = False
    fake.github_emails = [{"email": APPROVED, "verified": False, "primary": True}]
    await _refused(make(fake), provider, owner)


async def test_an_account_without_any_email_is_refused(
    make: Callable[..., Any], owner: psycopg.Connection
) -> None:
    fake = FakeProviders()
    fake.google_email = None
    await _refused(make(fake), "google", owner)


async def test_an_empty_allowlist_admits_nobody(
    make: Callable[..., Any], owner: psycopg.Connection
) -> None:
    await _refused(make(FakeProviders(), access_allowlist=[]), "google", owner)


# --- revoked --------------------------------------------------------------------------------


async def test_removing_an_address_revokes_existing_sessions(make: Callable[..., Any]) -> None:
    fake = FakeProviders()
    async with browser(make(fake), "203.0.113.88") as client:
        await sign_in(client, "google")
        cookies = client.cookies
    # The list changes and the API restarts; the old session cookie is presented again.
    revoked = make(fake, access_allowlist=["someone-else@example.com"])
    async with browser(revoked, "203.0.113.88") as client:
        client.cookies = cookies
        client.headers["X-CSRF-Token"] = cookies["qc_csrf"]
        me = await client.get("/api/v1/me")
        listing = await client.get("/api/v1/investigations")
        stream = await client.get(f"/api/v1/runs/{uuid.uuid4()}/events")
        created = await client.post("/api/v1/session")
        again = await sign_in(client, "google")
    for r in (me, listing, stream, created):
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "ACCESS_DENIED"
        assert_no_list_leak(r)
    assert again.headers["location"].endswith("?auth_error=not_allowed")


async def test_an_account_from_open_mode_has_no_access_until_it_signs_in_again(
    make: Callable[..., Any],
) -> None:
    fake = FakeProviders()
    open_app = make(fake, restricted_access=False, access_allowlist=[])
    async with browser(open_app, "203.0.113.89") as client:
        await client.post("/api/v1/session")
        await sign_in(client, "google")
        cookies = client.cookies
    async with browser(make(fake), "203.0.113.89") as client:
        client.cookies = cookies
        stale = await client.get("/api/v1/me")
        await sign_in(client, "google")
        fresh = await client.get("/api/v1/me")
    assert stale.status_code == 403  # no verified email was ever stored for it
    assert fresh.status_code == 200


# --- open mode unchanged --------------------------------------------------------------------


async def test_open_mode_requests_no_email_and_stores_none(
    make: Callable[..., Any], owner: psycopg.Connection
) -> None:
    fake = FakeProviders()
    app = make(fake, restricted_access=False, access_allowlist=[])
    async with browser(app, "203.0.113.90") as client:
        assert (await client.post("/api/v1/session")).status_code == 201
        google = await client.get("/api/v1/auth/google/login")
        await sign_in(client, "github")
        options = await client.get("/api/v1/auth/options")
    assert parse_qs(urlparse(google.headers["location"]).query)["scope"] == ["openid profile"]
    assert fake.email_requests == 0
    row = owner.execute("SELECT email FROM users WHERE auth_provider = 'github'").fetchone()
    assert row == (None,)
    assert options.json()["restricted_access"] is False
