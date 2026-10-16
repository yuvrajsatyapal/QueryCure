"""Phase 5 API hardening (T5.3, T5.9): rate limits, logout, upload ownership, response
headers, and a cross-user sweep of every route that takes a resource ID."""

import asyncio
import base64
import os
import re
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx2 as httpx
import psycopg
import pytest

from querycure.api.main import create_app
from querycure.api.rate_limit import consume
from querycure.core.config import Profile, Settings
from querycure.db.engine import make_engine
from querycure.domain.limits import RateLimit

pytestmark = pytest.mark.integration
PLAN = [{"Plan": {"Node Type": "Seq Scan", "Relation Name": "orders", "Total Cost": 10.0,
                  "Plan Rows": 5, "Plan Width": 8, "Startup Cost": 0.0}}]  # fmt: skip


def demo_settings(**overrides: Any) -> Settings:
    return Settings(
        _env_file=None,
        profile=Profile.DEMO,
        allow_private_targets=False,
        master_key=base64.b64encode(os.urandom(32)).decode(),
        **overrides,
    )


@pytest.fixture
async def demo_app(migrated_db: str) -> AsyncIterator[Any]:
    engine = make_engine(migrated_db, set_role="qc_app")
    yield create_app(demo_settings(), engine=engine)
    await engine.dispose()


@pytest.fixture(autouse=True)
def _fresh_buckets(owner: psycopg.Connection) -> None:
    owner.execute("DELETE FROM rate_limit_buckets")


async def signed_in(app: Any, address: str = "203.0.113.7") -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, client=(address, 4000), raise_app_exceptions=False)
    client = httpx.AsyncClient(transport=transport, base_url="https://test")
    r = await client.post("/api/v1/session")
    assert r.status_code == 201, r.text
    client.headers["X-CSRF-Token"] = client.cookies["qc_csrf"]
    return client


# --- rate limits ------------------------------------------------------------------------


async def test_session_creation_is_limited_per_client_address(demo_app: Any) -> None:
    transport = httpx.ASGITransport(app=demo_app, client=("198.51.100.9", 1))
    async with httpx.AsyncClient(transport=transport, base_url="https://test") as anonymous:
        statuses = []
        for _ in range(11):
            anonymous.cookies.clear()
            statuses.append((await anonymous.post("/api/v1/session")).status_code)
        assert statuses[:10] == [201] * 10
        limited = await anonymous.post("/api/v1/session")
    assert statuses[10] == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"
    assert int(limited.headers["Retry-After"]) >= 1
    assert limited.headers["X-RateLimit-Remaining"] == "0"
    # Another address has its own bucket; a spoofed X-Forwarded-For does not (no trusted hops).
    other = httpx.ASGITransport(app=demo_app, client=("198.51.100.10", 1))
    async with httpx.AsyncClient(transport=other, base_url="https://test") as fresh:
        assert (await fresh.post("/api/v1/session")).status_code == 201
    async with httpx.AsyncClient(transport=transport, base_url="https://test") as spoof:
        r = await spoof.post("/api/v1/session", headers={"X-Forwarded-For": "192.0.2.55"})
    assert r.status_code == 429


async def test_the_last_token_is_taken_exactly_once(migrated_db: str) -> None:
    engine = make_engine(migrated_db, set_role="qc_app")
    try:
        limit = RateLimit(capacity=3, per_hour=0.001)
        decisions = await asyncio.gather(*(consume(engine, "t:race", limit) for _ in range(12)))
    finally:
        await engine.dispose()
    assert sum(d.allowed for d in decisions) == 3
    assert all(d.retry_after_seconds >= 1 for d in decisions if not d.allowed)


async def test_inspect_requests_are_limited_per_user(demo_app: Any) -> None:
    client = await signed_in(demo_app)
    try:
        codes = [
            (await client.post("/api/v1/inspect/sql", json={"query": "SELECT 1"})).status_code
            for _ in range(21)
        ]
    finally:
        await client.aclose()
    assert codes[:20] == [200] * 20
    assert codes[20] == 429


# --- logout -----------------------------------------------------------------------------


async def test_logout_revokes_the_session_server_side(demo_app: Any) -> None:
    client = await signed_in(demo_app)
    try:
        token = client.cookies["qc_session"]
        assert (await client.get("/api/v1/me")).status_code == 200
        no_csrf = await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": ""})
        assert no_csrf.status_code == 403
        out = await client.post("/api/v1/auth/logout")
        assert out.status_code == 204
        assert "qc_session=" in out.headers.get("set-cookie", "")
        # A stolen copy of the old cookie no longer works.
        client.cookies.set("qc_session", token)
        assert (await client.get("/api/v1/me")).status_code == 401
        # The CSRF cookie was cleared too; with a token pair again, a repeat is a no-op.
        client.cookies.set("qc_csrf", client.headers["X-CSRF-Token"])
        assert (await client.post("/api/v1/auth/logout")).status_code == 204
    finally:
        await client.aclose()


# --- uploads are not capabilities -------------------------------------------------------


async def test_another_users_upload_digest_cannot_start_a_run(demo_app: Any) -> None:
    alice, mallory = (
        await signed_in(demo_app, "203.0.113.20"),
        await signed_in(demo_app, "203.0.113.21"),
    )
    try:
        uploaded = await alice.post("/api/v1/inspect/plan", json=PLAN)
        assert uploaded.status_code == 200, uploaded.text
        body = {
            "title": "t", "objective": "o", "modes": ["offline"],
            "plan_artifact_sha256": uploaded.json()["artifact_sha256"],
        }  # fmt: skip
        stolen = await mallory.post("/api/v1/investigations", json=body)
        assert stolen.status_code == 422
        assert stolen.json()["error"]["details"][0]["field"] == "plan_artifact_sha256"
        # The uploader can use it (the demo profile has no model key: 503, not 422).
        own = await alice.post("/api/v1/investigations", json=body)
        assert own.status_code != 422, own.text
    finally:
        await alice.aclose()
        await mallory.aclose()


# --- headers ----------------------------------------------------------------------------


async def test_security_headers_and_no_docs_page_on_the_demo(demo_app: Any) -> None:
    client = await signed_in(demo_app)
    try:
        r = await client.get("/api/v1/me")
        docs = await client.get("/api/v1/docs")
        schema = await client.get("/api/v1/openapi.json")
    finally:
        await client.aclose()
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"
    assert "max-age=" in r.headers["strict-transport-security"]
    assert docs.status_code == 404
    assert schema.status_code == 200


# --- cross-user sweep -------------------------------------------------------------------

BODIES: dict[str, Any] = {
    "/api/v1/approvals/{approval_id}/decision": {"decision": "approve"},
    "/api/v1/experiments/{experiment_id}/replay": {"confirm_ddl": True},
    "/api/v1/investigations/{investigation_id}/reinvestigate": {"confirm_new_llm_run": True},
    "/api/v1/connections/{connection_id}/explain": {"query": "SELECT 1"},
}
QUERY: dict[str, dict[str, str]] = {
    "/api/v1/runs/{run_id}/plans/diff": {"from": "ab" * 32, "to": "ab" * 32},
}


def _alice_resources(owner: psycopg.Connection, alice: uuid.UUID) -> dict[str, str]:
    inv = owner.execute(
        "INSERT INTO investigations (user_id, title, objective, modes) VALUES "
        "(%s, 'secret title', 'o', ARRAY['sandbox_benchmark']) RETURNING id",
        (alice,),
    ).fetchone()
    assert inv is not None
    run = owner.execute(
        "INSERT INTO investigation_runs (investigation_id, run_number, kind, status, budget, "
        "usage, finalized_at) VALUES (%s, 1, 'initial', 'completed', '{}', '{}', now()) "
        "RETURNING id",
        (inv[0],),
    ).fetchone()
    assert run is not None
    owner.execute("UPDATE investigations SET latest_run_id = %s WHERE id = %s", (run[0], inv[0]))
    art = owner.execute(
        "INSERT INTO artifacts (sha256, kind, media_type, canonicalization, content) "
        "VALUES (%s, 'query', 'text/sql', 'qc-text-v1', 'SELECT 1') RETURNING id, sha256",
        ("ab" * 32,),
    ).fetchone()
    assert art is not None
    owner.execute(
        "INSERT INTO run_artifacts (run_id, artifact_id, role, produced_by) "
        "VALUES (%s, %s, 'input.query', 'api')",
        (run[0], art[0]),
    )
    approval = owner.execute(
        "INSERT INTO approval_requests (run_id, user_id, round, kind, payload, expires_at) "
        "VALUES (%s, %s, 0, 'sandbox_execution', '{}', now() + interval '1 hour') RETURNING id",
        (run[0], alice),
    ).fetchone()
    experiment = owner.execute(
        "INSERT INTO experiments (run_id, round, kind, approval_request_id, config_artifact_id, "
        "engine_version, row_profile, seed, status) VALUES (%s, 0, 'single', %s, %s, "
        "'bench@2', 'qc-row-v1', 1, 'completed') RETURNING id",
        (run[0], approval[0] if approval else None, art[0]),
    ).fetchone()
    attempt = owner.execute(
        "INSERT INTO replay_attempts (user_id, kind, source_run_id, status) "
        "VALUES (%s, 'report', %s, 'verified') RETURNING id",
        (alice, run[0]),
    ).fetchone()
    connection = owner.execute(
        "INSERT INTO database_connections (user_id, name, host, port, dbname, username, sslmode, "
        "environment, purpose) VALUES (%s, 'c', 'db.example.com', 5432, 'd', 'u', 'require', "
        "'development', 'inspection') RETURNING id",
        (alice,),
    ).fetchone()
    credential = owner.execute(
        "INSERT INTO llm_credentials (user_id, provider, ciphertext, nonce, key_version, "
        "key_hint) VALUES (%s, 'openrouter', '\\x00', '\\x00', 1, 'abcd') RETURNING id",
        (alice,),
    ).fetchone()
    assert credential is not None
    assert approval is not None
    assert experiment is not None
    assert attempt is not None
    assert connection is not None
    return {
        "investigation_id": str(inv[0]),
        "run_id": str(run[0]),
        "other_run_id": str(run[0]),
        "sha256": art[1],
        "approval_id": str(approval[0]),
        "experiment_id": str(experiment[0]),
        "attempt_id": str(attempt[0]),
        "connection_id": str(connection[0]),
        "evidence_id": "ev_000000000000",
        "credential_id": str(credential[0]),
        "slug": "no-such-demo",  # public demo routes: unknown slugs are 404 for everyone
    }


async def test_no_route_exposes_or_acts_on_another_users_resources(
    demo_app: Any, owner: psycopg.Connection
) -> None:
    alice = owner.execute(
        "INSERT INTO users (kind, display_name) VALUES ('anonymous', 'alice') RETURNING id"
    ).fetchone()
    assert alice is not None
    ids = _alice_resources(owner, alice[0])
    mallory = await signed_in(demo_app, "203.0.113.30")
    checked = []
    try:
        # Every documented route with a path parameter (the OpenAPI schema is the route list).
        for template, operations in demo_app.openapi()["paths"].items():
            if "{" not in template:
                continue
            params = re.findall(r"{(\w+)}", template)
            missing = [p for p in params if p not in ids]
            assert not missing, f"sweep does not know {missing} for {template}: add it"
            path = template.format(**{p: ids[p] for p in params})
            for method in operations:
                r = await mallory.request(
                    method.upper(), path, json=BODIES.get(template), params=QUERY.get(template)
                )
                checked.append((method, template, r.status_code))
                assert r.status_code in (404, 403), (method, template, r.status_code, r.text)
                if r.status_code == 403:  # only the demo's disabled live-inspection routes
                    assert r.json()["error"]["code"] == "FEATURE_DISABLED", template
                assert "secret title" not in r.text
                for value in ids.values():
                    assert value not in r.text or value == "ev_000000000000", (template, value)
    finally:
        await mallory.aclose()
    assert len(checked) >= 25, checked
    rows = owner.execute(
        "SELECT (SELECT status FROM approval_requests WHERE id = %s), "
        "(SELECT count(*) FROM replay_attempts WHERE source_run_id = %s), "
        "(SELECT deleted_at FROM investigations WHERE id = %s)",
        (ids["approval_id"], ids["run_id"], ids["investigation_id"]),
    ).fetchone()
    assert rows == ("pending", 1, None)  # nothing of Alice's changed
    key = owner.execute(
        "SELECT deleted_at FROM llm_credentials WHERE id = %s", (ids["credential_id"],)
    ).fetchone()
    assert key == (None,)
