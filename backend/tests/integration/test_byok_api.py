"""BYOK credentials (T5.2): keys are encrypted at rest, never returned, wiped on delete, used
only for their owner's runs, and limited to free models (ADR-0016)."""

import base64
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx2 as httpx
import psycopg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.agents.run import RunServices, execute_run, user_clients
from querycure.api.main import create_app
from querycure.core.config import Profile, Settings
from querycure.core.crypto import EncryptedSecret
from querycure.db.engine import make_engine
from querycure.db.repositories import llm_credentials as creds
from querycure.llm.credentials import resolve_user_credential, secret_box

pytestmark = pytest.mark.integration
KEY = "sk-or-v1-" + "a1b2c3d4" * 6 + "WXYZ"
MASTER = base64.b64encode(os.urandom(32)).decode()


def demo() -> Settings:
    return Settings(
        _env_file=None, profile=Profile.DEMO, allow_private_targets=False, master_key=MASTER
    )


@pytest.fixture
async def app(migrated_db: str) -> AsyncIterator[Any]:
    engine = make_engine(migrated_db, set_role="qc_app")
    yield create_app(demo(), engine=engine)
    await engine.dispose()


@pytest.fixture(autouse=True)
def _fresh_buckets(owner: psycopg.Connection) -> None:
    owner.execute("DELETE FROM rate_limit_buckets")


async def client_for(app: Any, address: str) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, client=(address, 1), raise_app_exceptions=False)
    client = httpx.AsyncClient(transport=transport, base_url="https://test")
    await client.post("/api/v1/session")
    client.headers["X-CSRF-Token"] = client.cookies["qc_csrf"]
    return client


async def test_key_is_encrypted_hinted_and_never_returned(
    app: Any, owner: psycopg.Connection, migrated_db: str
) -> None:
    user = await client_for(app, "203.0.113.40")
    try:
        added = await user.post(
            "/api/v1/settings/llm-credentials",
            json={"provider": "openrouter", "api_key": KEY, "default_model": "x/y:free"},
        )
        listed = await user.get("/api/v1/settings/llm-credentials")
        models = await user.get("/api/v1/settings/models")
    finally:
        await user.aclose()
    assert added.status_code == 201, added.text
    for response in (added, listed, models):
        assert KEY not in response.text
        assert KEY[:-4] not in response.text
    assert added.json()["key_hint"] == "WXYZ"
    assert listed.json()["items"][0]["id"] == added.json()["id"]
    assert models.json()["configured"] is True
    assert models.json()["model"] == "x/y:free"
    row = owner.execute(
        "SELECT ciphertext, nonce, key_version, user_id FROM llm_credentials WHERE id = %s",
        (added.json()["id"],),
    ).fetchone()
    assert row is not None
    assert KEY.encode() not in bytes(row[0])
    # It decrypts only with its own row/user binding (copying the ciphertext elsewhere fails).
    sealed = EncryptedSecret(ciphertext=bytes(row[0]), nonce=bytes(row[1]), key_version=row[2])
    box = secret_box(demo())
    cred_id = uuid.UUID(added.json()["id"])
    assert box.decrypt(sealed, aad=creds.aad(cred_id, row[3])).get_secret_value() == KEY
    with pytest.raises(Exception, match="authentication"):
        box.decrypt(sealed, aad=creds.aad(uuid.uuid4(), row[3]))


async def test_validation_never_echoes_the_key_and_refuses_paid_models(app: Any) -> None:
    user = await client_for(app, "203.0.113.41")
    try:
        spaced = await user.post(
            "/api/v1/settings/llm-credentials", json={"api_key": "sk-or bad key with spaces"}
        )
        paid = await user.post(
            "/api/v1/settings/llm-credentials",
            json={"api_key": KEY, "default_model": "openai/gpt-5"},
        )
        gemini = await user.post(
            "/api/v1/settings/llm-credentials", json={"provider": "gemini", "api_key": KEY}
        )
    finally:
        await user.aclose()
    assert spaced.status_code == 422
    assert "bad key" not in spaced.text
    assert paid.status_code == 422
    assert KEY not in paid.text
    assert gemini.status_code == 403  # free-only: OpenRouter keys only


async def test_delete_wipes_the_ciphertext_and_is_owner_only(
    app: Any, owner: psycopg.Connection
) -> None:
    alice = await client_for(app, "203.0.113.42")
    mallory = await client_for(app, "203.0.113.43")
    try:
        cred = (await alice.post("/api/v1/settings/llm-credentials", json={"api_key": KEY})).json()
        foreign = await mallory.delete(f"/api/v1/settings/llm-credentials/{cred['id']}")
        assert foreign.status_code == 404
        assert (await mallory.get("/api/v1/settings/llm-credentials")).json()["items"] == []
        gone = await alice.delete(f"/api/v1/settings/llm-credentials/{cred['id']}")
        assert gone.status_code == 204
        assert (await alice.get("/api/v1/settings/llm-credentials")).json()["items"] == []
    finally:
        await alice.aclose()
        await mallory.aclose()
    row = owner.execute(
        "SELECT ciphertext, nonce, deleted_at IS NOT NULL FROM llm_credentials WHERE id = %s",
        (cred["id"],),
    ).fetchone()
    assert row == (None, None, True)


async def test_demo_runs_need_and_use_the_users_own_key(
    app: Any, owner: psycopg.Connection
) -> None:
    user = await client_for(app, "203.0.113.44")
    body = {"title": "t", "objective": "o", "modes": ["offline"], "query": "SELECT 1"}
    try:
        without = await user.post("/api/v1/investigations", json=body)
        cred = (await user.post("/api/v1/settings/llm-credentials", json={"api_key": KEY})).json()
        other = await user.post(
            "/api/v1/investigations",
            json={**body, "llm": {"credential_id": str(uuid.uuid4())}},
        )
        started = await user.post("/api/v1/investigations", json=body)
    finally:
        await user.aclose()
    assert without.status_code == 503
    assert "own OpenRouter key" in without.json()["error"]["message"]
    assert other.status_code == 404
    assert started.status_code == 202, started.text
    stored = owner.execute(
        "SELECT llm_credential_id FROM investigation_runs WHERE id = %s",
        (started.json()["run"]["id"],),
    ).fetchone()
    assert stored == (uuid.UUID(cred["id"]),)


async def test_worker_resolves_the_key_per_run_and_stops_when_it_is_removed(
    app: Any, owner: psycopg.Connection, app_engine: AsyncEngine, migrated_db: str
) -> None:
    user = await client_for(app, "203.0.113.45")
    try:
        cred = (await user.post("/api/v1/settings/llm-credentials", json={"api_key": KEY})).json()
        run = (
            await user.post(
                "/api/v1/investigations",
                json={"title": "t", "objective": "o", "modes": ["offline"], "query": "SELECT 1"},
            )
        ).json()["run"]
        user_id = owner.execute(
            "SELECT i.user_id FROM investigations i WHERE i.id = %s", (run["investigation_id"],)
        ).fetchone()
        assert user_id is not None
        async with app_engine.begin() as conn:
            credential = await resolve_user_credential(
                conn, demo(), user_id=user_id[0], credential_id=uuid.UUID(cred["id"])
            )
        assert credential.api_key.get_secret_value() == KEY
        assert KEY not in repr(credential)
        client = user_clients(demo(), credential).primary
        assert (client.provider, client.model) == ("openrouter", demo().llm_model)
        # Removing the key stops the run before any provider call.
        await user.delete(f"/api/v1/settings/llm-credentials/{cred['id']}")
    finally:
        await user.aclose()

    def no_clients(_: Any) -> Any:
        raise AssertionError("the server key must not stand in for a removed user key")

    services = RunServices(
        engine=app_engine, settings=demo(), checkpoint_url=migrated_db, clients=no_clients,
        checkpoint_role="qc_app",
    )  # fmt: skip
    await execute_run(services, uuid.UUID(run["id"]), attempt=1, reclaimed=False)
    status = owner.execute(
        "SELECT status, error->>'code' FROM investigation_runs WHERE id = %s", (run["id"],)
    ).fetchone()
    assert status == ("failed", "CONFIGURATION_ERROR")
