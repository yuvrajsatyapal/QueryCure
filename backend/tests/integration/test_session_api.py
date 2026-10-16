import base64
import os
from collections.abc import AsyncIterator

import httpx2 as httpx
import pytest

from querycure.api.main import create_app
from querycure.core.config import Profile, Settings
from querycure.db.engine import make_engine

pytestmark = pytest.mark.integration


def demo_settings() -> Settings:
    return Settings(
        _env_file=None,
        profile=Profile.DEMO,
        allow_private_targets=False,
        master_key=base64.b64encode(os.urandom(32)).decode(),
    )


async def make_client(migrated_db: str, settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    url = migrated_db.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = make_engine(url, set_role="qc_app")
    app = create_app(settings, engine=engine)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    await engine.dispose()


@pytest.fixture
async def local_client(migrated_db: str) -> AsyncIterator[httpx.AsyncClient]:
    async for c in make_client(migrated_db, Settings(_env_file=None)):
        yield c


@pytest.fixture
async def demo_client(migrated_db: str) -> AsyncIterator[httpx.AsyncClient]:
    async for c in make_client(migrated_db, demo_settings()):
        yield c


async def test_me_requires_a_session(local_client: httpx.AsyncClient) -> None:
    r = await local_client.get("/api/v1/me")

    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_local_session_resolves_the_single_local_user(
    local_client: httpx.AsyncClient,
) -> None:
    r = await local_client.post("/api/v1/session")

    assert r.status_code == 201
    assert r.json()["user"]["kind"] == "local"
    assert "qc_session" in local_client.cookies
    assert "qc_csrf" in local_client.cookies
    me = (await local_client.get("/api/v1/me")).json()
    assert me["user"]["id"] == r.json()["user"]["id"]
    assert me["profile"] == "local"
    assert me["features"] == {"live_inspection": True, "sandbox": True, "github_login": False}


async def test_session_cookie_flags(local_client: httpx.AsyncClient) -> None:
    r = await local_client.post("/api/v1/session")

    session_cookie = next(
        h for h in r.headers.get_list("set-cookie") if h.startswith("qc_session=")
    )
    csrf_cookie = next(h for h in r.headers.get_list("set-cookie") if h.startswith("qc_csrf="))
    assert "httponly" in session_cookie.lower()
    assert "samesite=lax" in session_cookie.lower()
    assert "httponly" not in csrf_cookie.lower()


async def test_repeated_session_creation_reuses_the_local_user(migrated_db: str) -> None:
    ids = []
    for _ in range(2):
        async for c in make_client(migrated_db, Settings(_env_file=None)):
            ids.append((await c.post("/api/v1/session")).json()["user"]["id"])

    assert ids[0] == ids[1]


async def test_existing_valid_session_is_returned_not_duplicated(
    local_client: httpx.AsyncClient,
) -> None:
    first = await local_client.post("/api/v1/session")
    cookie = local_client.cookies["qc_session"]

    second = await local_client.post("/api/v1/session")

    assert second.status_code == 200
    assert local_client.cookies["qc_session"] == cookie
    assert second.json()["user"]["id"] == first.json()["user"]["id"]


async def test_demo_profile_creates_distinct_anonymous_users(migrated_db: str) -> None:
    users = []
    for _ in range(2):
        async for c in make_client(migrated_db, demo_settings()):
            body = (await c.post("/api/v1/session")).json()
            users.append(body["user"])

    assert {u["kind"] for u in users} == {"anonymous"}
    assert users[0]["id"] != users[1]["id"]


async def test_demo_profile_cookie_is_secure_and_features_restricted(
    demo_client: httpx.AsyncClient,
) -> None:
    r = await demo_client.post("/api/v1/session")

    session_cookie = next(
        h for h in r.headers.get_list("set-cookie") if h.startswith("qc_session=")
    )
    assert "secure" in session_cookie.lower()


async def test_forged_or_unknown_session_token_is_rejected(local_client: httpx.AsyncClient) -> None:
    local_client.cookies.set("qc_session", "forged-token")

    r = await local_client.get("/api/v1/me")

    assert r.status_code == 401


async def test_only_the_token_hash_is_stored(local_client: httpx.AsyncClient, owner) -> None:  # type: ignore[no-untyped-def]
    await local_client.post("/api/v1/session")
    token = local_client.cookies["qc_session"]

    stored = [r[0] for r in owner.execute("SELECT token_hash FROM sessions")]

    assert token not in stored
    assert all(len(h) == 64 for h in stored)


async def test_readyz_reports_database_and_migrations(local_client: httpx.AsyncClient) -> None:
    r = await local_client.get("/api/v1/readyz")

    assert r.status_code == 200
    assert r.json() == {"status": "ok", "database": "ok", "migrations": "current"}
