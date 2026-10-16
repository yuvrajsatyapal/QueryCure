"""GitHub OAuth and account linking (T5.1) against a mocked provider: state and PKCE checks,
same-row conversion of an anonymous user, merging a second anonymous user's data, session
rotation, safe redirects, and no stored provider token."""

import base64
import json
import os
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import httpx2
import psycopg
import pytest
from pydantic import SecretStr

from querycure.api.main import create_app
from querycure.auth.github import challenge
from querycure.core.config import Profile, Settings
from querycure.db.engine import make_engine

pytestmark = pytest.mark.integration
GITHUB_TOKEN = "gho_" + "t0k3n" * 6
KEY = "sk-or-v1-" + "9f8e7d6c" * 6 + "LMNO"


def settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "_env_file": None,
        "profile": Profile.DEMO,
        "allow_private_targets": False,
        "master_key": base64.b64encode(os.urandom(32)).decode(),
        "github_client_id": "Iv1.client",
        "github_client_secret": SecretStr("client-secret"),
        "public_api_url": "https://api.querycure.test",
        "web_base_url": "https://app.querycure.test",
    }
    return Settings(**{**base, **overrides})


class FakeGitHub:
    def __init__(self, user_id: int = 4242, login: str = "octo") -> None:
        self.user_id, self.login = user_id, login
        self.token_requests: list[dict[str, list[str]]] = []
        self.fail_token = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login/oauth/access_token":
            form = parse_qs(request.content.decode())
            self.token_requests.append(form)
            if self.fail_token:
                return httpx.Response(200, json={"error": "bad_verification_code"})
            return httpx.Response(200, json={"access_token": GITHUB_TOKEN, "token_type": "bearer"})
        if request.url.path == "/user":
            assert request.headers["Authorization"] == f"Bearer {GITHUB_TOKEN}"
            return httpx.Response(200, json={"id": self.user_id, "login": self.login})
        return httpx.Response(404)


@pytest.fixture
async def make(migrated_db: str) -> AsyncIterator[Callable[..., Any]]:
    engines = []

    def build(fake: FakeGitHub, **overrides: Any) -> Any:
        engine = make_engine(migrated_db, set_role="qc_app")
        engines.append(engine)
        app = create_app(settings(**overrides), engine=engine)
        app.state.oauth_http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
        return app

    yield build
    for engine in engines:
        await engine.dispose()


@pytest.fixture(autouse=True)
def _fresh_buckets(owner: psycopg.Connection) -> None:
    owner.execute("DELETE FROM rate_limit_buckets")


async def browser(app: Any, address: str) -> httpx2.AsyncClient:
    transport = httpx2.ASGITransport(app=app, client=(address, 1), raise_app_exceptions=False)
    client = httpx2.AsyncClient(transport=transport, base_url="https://api.querycure.test")
    await client.post("/api/v1/session")
    client.headers["X-CSRF-Token"] = client.cookies["qc_csrf"]
    return client


async def sign_in(client: httpx2.AsyncClient, return_to: str = "/app/history") -> httpx2.Response:
    login = await client.get("/api/v1/auth/github/login", params={"return_to": return_to})
    assert login.status_code == 302
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    return await client.get("/api/v1/auth/github/callback", params={"code": "c0de", "state": state})


async def test_disabled_without_configuration(make: Callable[..., Any]) -> None:
    app = make(FakeGitHub(), github_client_id=None, github_client_secret=None)
    client = await browser(app, "203.0.113.60")
    try:
        r = await client.get("/api/v1/auth/github/login")
        me = await client.get("/api/v1/me")
    finally:
        await client.aclose()
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FEATURE_DISABLED"
    assert me.json()["features"]["github_login"] is False


async def test_login_redirect_carries_state_and_pkce_and_sanitizes_return_to(
    make: Callable[..., Any],
) -> None:
    app = make(FakeGitHub())
    client = await browser(app, "203.0.113.61")
    try:
        r = await client.get("/api/v1/auth/github/login", params={"return_to": "//evil.example/x"})
    finally:
        await client.aclose()
    location = urlparse(r.headers["location"])
    query = parse_qs(location.query)
    assert (location.scheme, location.netloc) == ("https", "github.com")
    assert query["client_id"] == ["Iv1.client"]
    assert query["redirect_uri"] == ["https://api.querycure.test/api/v1/auth/github/callback"]
    assert query["code_challenge_method"] == ["S256"]
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    state, verifier, target = cookie.split("qc_oauth=")[1].split(";")[0].strip('"').split(".")
    assert query["state"] == [state]
    assert query["code_challenge"] == [challenge(verifier)]
    assert base64.urlsafe_b64decode(target).decode() == "/app"  # not the foreign host


async def test_state_mismatch_and_failed_exchange_never_sign_in(
    make: Callable[..., Any], owner: psycopg.Connection
) -> None:
    fake = FakeGitHub()
    app = make(fake)
    client = await browser(app, "203.0.113.62")
    try:
        await client.get("/api/v1/auth/github/login")
        forged = await client.get(
            "/api/v1/auth/github/callback", params={"code": "c", "state": "attacker"}
        )
        fake.fail_token = True
        failed = await sign_in(client)
        me = await client.get("/api/v1/me")
    finally:
        await client.aclose()
    assert forged.status_code == 302
    assert forged.headers["location"].endswith("/app?auth_error=state_mismatch")
    assert failed.headers["location"].endswith("/app?auth_error=token_exchange_failed")
    assert me.json()["user"]["kind"] == "anonymous"
    assert owner.execute("SELECT count(*) FROM users WHERE kind = 'oauth'").fetchone() == (0,)


async def test_first_sign_in_keeps_the_anonymous_users_data_and_rotates_the_session(
    make: Callable[..., Any], owner: psycopg.Connection
) -> None:
    fake = FakeGitHub()
    app = make(fake)
    client = await browser(app, "203.0.113.63")
    try:
        before = (await client.get("/api/v1/me")).json()["user"]
        old_token = client.cookies["qc_session"]
        done = await sign_in(client)
        assert done.status_code == 302
        assert done.headers["location"] == "https://app.querycure.test/app/history"
        assert client.cookies["qc_session"] != old_token
        client.headers["X-CSRF-Token"] = client.cookies["qc_csrf"]
        after = (await client.get("/api/v1/me")).json()["user"]
        stale = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app, client=("203.0.113.63", 1)),
            base_url="https://api.querycure.test",
            cookies={"qc_session": old_token},
        )
        async with stale:
            assert (await stale.get("/api/v1/me")).status_code == 401
    finally:
        await client.aclose()
    assert after == {"id": before["id"], "kind": "oauth", "display_name": "octo"}
    # The PKCE verifier went to GitHub; the provider token is stored nowhere.
    assert fake.token_requests[0]["code_verifier"]
    dump = owner.execute("SELECT string_agg(t::text, '') FROM (SELECT * FROM users) t").fetchone()
    assert dump is not None
    assert GITHUB_TOKEN not in (dump[0] or "")


async def test_second_device_merges_into_the_existing_account(
    make: Callable[..., Any], owner: psycopg.Connection
) -> None:
    app = make(FakeGitHub())
    laptop = await browser(app, "203.0.113.64")
    phone = await browser(app, "203.0.113.65")
    try:
        await sign_in(laptop)
        account = (await laptop.get("/api/v1/me")).json()["user"]["id"]
        anonymous = (await phone.get("/api/v1/me")).json()["user"]["id"]
        owner.execute(
            "INSERT INTO investigations (user_id, title, objective, modes) "
            "VALUES (%s, 'from the phone', 'o', ARRAY['offline'])",
            (anonymous,),
        )
        saved = await phone.post("/api/v1/settings/llm-credentials", json={"api_key": KEY})
        assert saved.status_code == 201, saved.text
        await sign_in(phone)
        phone.headers["X-CSRF-Token"] = phone.cookies["qc_csrf"]
        me = (await phone.get("/api/v1/me")).json()["user"]
        keys = (await phone.get("/api/v1/settings/llm-credentials")).json()["items"]
    finally:
        await laptop.aclose()
        await phone.aclose()
    assert me["id"] == account
    owned = owner.execute(
        "SELECT user_id FROM investigations WHERE title = 'from the phone'"
    ).fetchone()
    assert owned == (uuid.UUID(account),)
    retired = owner.execute(
        "SELECT deleted_at IS NOT NULL FROM users WHERE id = %s", (anonymous,)
    ).fetchone()
    assert retired == (True,)
    assert [k["key_hint"] for k in keys] == ["LMNO"]  # re-encrypted for the account
    wiped = owner.execute(
        "SELECT count(*) FROM llm_credentials WHERE user_id = %s AND ciphertext IS NOT NULL",
        (anonymous,),
    ).fetchone()
    assert wiped == (0,)
    assert json.dumps(keys).find(KEY) == -1
