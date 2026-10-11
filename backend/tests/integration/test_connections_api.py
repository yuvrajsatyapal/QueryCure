import base64
import hashlib
import os
import secrets
from collections.abc import AsyncIterator
from typing import Any

import httpx2 as httpx
import psycopg
import pytest

from querycure.api.main import create_app
from querycure.core.config import Profile, Settings
from querycure.db.engine import make_engine

pytestmark = pytest.mark.integration

MASTER_KEY = base64.b64encode(os.urandom(32)).decode()


def local_settings() -> Settings:
    return Settings(_env_file=None, master_key=MASTER_KEY)


async def api(migrated_db: str, settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    engine = make_engine(migrated_db, set_role="qc_app")
    transport = httpx.ASGITransport(app=create_app(settings, engine=engine))
    async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
        r = await client.post("/api/v1/session")
        assert r.status_code in (200, 201)
        client.headers["X-CSRF-Token"] = client.cookies["qc_csrf"]
        yield client
    await engine.dispose()


@pytest.fixture
async def client(migrated_db: str) -> AsyncIterator[httpx.AsyncClient]:
    async for c in api(migrated_db, local_settings()):
        yield c


def payload(target: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    body = {
        "name": "local orders",
        "host": target["host"],
        "port": target["port"],
        "dbname": target["dbname"],
        "username": target["role"],
        "password": target["password"],
        "sslmode": "disable",
        "environment": "development",
        "purpose": "inspection",
    }
    body.update(overrides)
    return body


async def create(
    client: httpx.AsyncClient, target: dict[str, Any], **overrides: Any
) -> dict[str, Any]:
    r = await client.post("/api/v1/connections", json=payload(target, **overrides))
    assert r.status_code == 201, r.text
    body: dict[str, Any] = r.json()
    return body


async def test_create_never_returns_or_stores_the_plain_password(
    client: httpx.AsyncClient, target: dict[str, Any], owner: psycopg.Connection
) -> None:
    created = await create(client, target)

    assert "password" not in created
    assert created["has_password"] is True
    row = owner.execute(
        "SELECT password_ciphertext, password_nonce, key_version "
        "FROM database_connections WHERE id = %s",
        (created["id"],),
    ).fetchone()
    assert row is not None
    assert target["password"].encode() not in bytes(row[0])
    assert len(bytes(row[1])) == 12
    assert row[2] == 1


async def test_list_shows_own_connections(
    client: httpx.AsyncClient, target: dict[str, Any]
) -> None:
    created = await create(client, target, name="listed")

    r = await client.get("/api/v1/connections")

    assert r.status_code == 200
    assert created["id"] in {c["id"] for c in r.json()["items"]}


async def test_test_endpoint_reports_capabilities(
    client: httpx.AsyncClient, target: dict[str, Any]
) -> None:
    created = await create(client, target)

    r = await client.post(f"/api/v1/connections/{created['id']}/test")

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["capabilities"]["is_superuser"] is False
    assert body["capabilities"]["server_version_num"] >= 170000
    listed = (await client.get("/api/v1/connections")).json()["items"]
    stored = next(c for c in listed if c["id"] == created["id"])
    assert stored["last_test_status"] == "ok"


async def test_superuser_connection_test_is_refused_and_recorded(
    client: httpx.AsyncClient, target: dict[str, Any]
) -> None:
    created = await create(
        client, target, username=target["admin_user"], password=target["admin_password"]
    )

    r = await client.post(f"/api/v1/connections/{created['id']}/test")

    assert r.status_code == 422
    assert r.json()["error"]["code"] == "ROLE_TOO_PRIVILEGED"
    listed = (await client.get("/api/v1/connections")).json()["items"]
    assert next(c for c in listed if c["id"] == created["id"])["last_test_status"] == "refused"


async def test_explain_returns_parsed_plan_and_metrics(
    client: httpx.AsyncClient, target: dict[str, Any]
) -> None:
    created = await create(client, target)

    r = await client.post(
        f"/api/v1/connections/{created['id']}/explain",
        json={
            "query": "SELECT * FROM orders WHERE customer_id = 7 ORDER BY created_at DESC LIMIT 20"
        },
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plan"]["root"]["node_type"] == "Limit"
    assert body["plan"]["analyzed"] is False
    assert len(body["metrics"]) == len(body["plan"]["nodes"])
    assert body["query"]["fingerprint"]["digest"]


async def test_explain_refuses_writes(client: httpx.AsyncClient, target: dict[str, Any]) -> None:
    created = await create(client, target)

    r = await client.post(
        f"/api/v1/connections/{created['id']}/explain", json={"query": "DELETE FROM orders"}
    )

    assert r.status_code == 422
    assert r.json()["error"]["code"] == "SQL_NOT_ALLOWED"


async def test_production_connections_need_an_investigation_approval(
    client: httpx.AsyncClient, target: dict[str, Any]
) -> None:
    created = await create(client, target, environment="production")

    r = await client.post(
        f"/api/v1/connections/{created['id']}/explain", json={"query": "SELECT 1"}
    )

    assert r.status_code == 409
    assert r.json()["error"]["code"] == "APPROVAL_REQUIRED"


async def test_schema_snapshot_endpoint_is_redacted(
    client: httpx.AsyncClient, target: dict[str, Any]
) -> None:
    created = await create(client, target)

    r = await client.get(
        f"/api/v1/connections/{created['id']}/schema", params={"tables": "public.orders"}
    )

    assert r.status_code == 200
    assert "secret-" not in r.text
    assert r.json()["tables"][0]["name"] == "orders"


async def test_delete_soft_deletes_and_wipes_the_secret(
    client: httpx.AsyncClient, target: dict[str, Any], owner: psycopg.Connection
) -> None:
    created = await create(client, target)

    r = await client.delete(f"/api/v1/connections/{created['id']}")

    assert r.status_code == 204
    row = owner.execute(
        "SELECT deleted_at, password_ciphertext, password_nonce "
        "FROM database_connections WHERE id = %s",
        (created["id"],),
    ).fetchone()
    assert row is not None
    assert row[0] is not None
    assert row[1] is None
    assert row[2] is None
    assert (await client.post(f"/api/v1/connections/{created['id']}/test")).status_code == 404


async def test_other_users_connections_are_invisible(
    client: httpx.AsyncClient, target: dict[str, Any], owner: psycopg.Connection, migrated_db: str
) -> None:
    created = await create(client, target)
    other = owner.execute("INSERT INTO users (kind) VALUES ('anonymous') RETURNING id").fetchone()[
        0
    ]  # type: ignore[index]
    token = secrets.token_urlsafe(32)
    owner.execute(
        "INSERT INTO sessions (user_id, token_hash, expires_at) "
        "VALUES (%s, %s, now() + interval '1 hour')",
        (other, hashlib.sha256(token.encode()).hexdigest()),
    )
    engine = make_engine(migrated_db, set_role="qc_app")
    transport = httpx.ASGITransport(app=create_app(local_settings(), engine=engine))
    async with httpx.AsyncClient(transport=transport, base_url="https://test") as intruder:
        intruder.cookies.set("qc_session", token)
        intruder.cookies.set("qc_csrf", "t")
        intruder.headers["X-CSRF-Token"] = "t"
        cid = created["id"]
        listed = await intruder.get("/api/v1/connections")
        responses = [
            await intruder.post(f"/api/v1/connections/{cid}/test"),
            await intruder.post(f"/api/v1/connections/{cid}/explain", json={"query": "SELECT 1"}),
            await intruder.get(f"/api/v1/connections/{cid}/schema", params={"tables": "orders"}),
            await intruder.delete(f"/api/v1/connections/{cid}"),
        ]
    await engine.dispose()

    assert cid not in {c["id"] for c in listed.json()["items"]}
    assert [r.status_code for r in responses] == [404, 404, 404, 404]


async def test_blocked_targets_are_rejected_at_creation(
    client: httpx.AsyncClient, target: dict[str, Any]
) -> None:
    r = await client.post("/api/v1/connections", json=payload(target, host="169.254.169.254"))

    assert r.status_code == 422
    assert r.json()["error"]["code"] == "CONNECTION_TARGET_BLOCKED"


async def test_creation_requires_csrf_token(
    client: httpx.AsyncClient, target: dict[str, Any]
) -> None:
    del client.headers["X-CSRF-Token"]

    r = await client.post("/api/v1/connections", json=payload(target))

    assert r.status_code == 403


async def test_validation_rejects_unknown_fields_and_bad_enums(
    client: httpx.AsyncClient, target: dict[str, Any]
) -> None:
    extra = await client.post("/api/v1/connections", json={**payload(target), "options": "-c x=y"})
    bad_env = await client.post("/api/v1/connections", json=payload(target, environment="prod"))

    assert extra.status_code == 422
    assert bad_env.status_code == 422


async def test_demo_profile_disables_live_inspection(
    migrated_db: str, target: dict[str, Any]
) -> None:
    demo = Settings(
        _env_file=None, profile=Profile.DEMO, allow_private_targets=False, master_key=MASTER_KEY
    )
    async for c in api(migrated_db, demo):
        r = await c.post("/api/v1/connections", json=payload(target))

        assert r.status_code == 403
        assert r.json()["error"]["code"] == "FEATURE_DISABLED"


async def test_missing_master_key_refuses_to_store_credentials(
    migrated_db: str, target: dict[str, Any]
) -> None:
    async for c in api(migrated_db, Settings(_env_file=None)):
        r = await c.post("/api/v1/connections", json=payload(target))

        assert r.status_code == 503
        assert r.json()["error"]["code"] == "CONFIGURATION_ERROR"
