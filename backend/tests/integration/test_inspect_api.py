import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx2 as httpx
import psycopg
import pytest

from querycure.api.main import create_app
from querycure.core.config import Settings
from querycure.db.engine import make_engine

pytestmark = pytest.mark.integration
PLANS = Path(__file__).parents[1] / "fixtures" / "plans"


@pytest.fixture
async def client(migrated_db: str) -> AsyncIterator[httpx.AsyncClient]:
    engine = make_engine(migrated_db, set_role="qc_app")
    transport = httpx.ASGITransport(app=create_app(Settings(_env_file=None), engine=engine))
    async with httpx.AsyncClient(transport=transport, base_url="https://test") as c:
        await c.post("/api/v1/session")
        c.headers["X-CSRF-Token"] = c.cookies["qc_csrf"]
        yield c
    await engine.dispose()


async def test_inspect_sql(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/api/v1/inspect/sql", json={"query": "SELECT * FROM orders WHERE id = $1"}
    )

    assert r.status_code == 200
    body = r.json()
    assert body["statement_type"] == "select"
    assert body["metadata"]["parameter_count"] == 1
    assert len(body["fingerprint"]["digest"]) == 64


async def test_inspect_sql_refuses_writes(client: httpx.AsyncClient) -> None:
    r = await client.post("/api/v1/inspect/sql", json={"query": "DROP TABLE orders"})

    assert r.status_code == 422
    assert r.json()["error"]["code"] == "SQL_NOT_ALLOWED"


async def test_inspect_plan_parses_and_stores_artifact(
    client: httpx.AsyncClient, owner: psycopg.Connection
) -> None:
    raw = (PLANS / "synthetic_canonical_seqscan_sort.json").read_bytes()

    r = await client.post(
        "/api/v1/inspect/plan", content=raw, headers={"content-type": "application/json"}
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plan"]["root"]["node_type"] == "Limit"
    assert body["metrics"][2]["self_time_ms"] == pytest.approx(100.0)
    stored = owner.execute(
        "SELECT kind, canonicalization FROM artifacts WHERE sha256 = %s", (body["artifact_sha256"],)
    ).fetchone()
    assert stored == ("plan_analyze", "qc-json-v1")


async def test_identical_plans_dedupe(client: httpx.AsyncClient) -> None:
    raw = (PLANS / "synthetic_nested_loop.json").read_text()
    reformatted = json.dumps(json.loads(raw), indent=4)

    a = await client.post(
        "/api/v1/inspect/plan", content=raw, headers={"content-type": "application/json"}
    )
    b = await client.post(
        "/api/v1/inspect/plan", content=reformatted, headers={"content-type": "application/json"}
    )

    assert a.json()["artifact_sha256"] == b.json()["artifact_sha256"]


@pytest.mark.parametrize("bad", [b"not json", b'{"Planning Time": 1}', b"[]"])
async def test_invalid_plans_are_400(client: httpx.AsyncClient, bad: bytes) -> None:
    r = await client.post(
        "/api/v1/inspect/plan", content=bad, headers={"content-type": "application/json"}
    )

    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_PLAN_FORMAT"


async def test_inspect_schema_parses_ddl_and_stores_artifact(
    client: httpx.AsyncClient, owner: psycopg.Connection
) -> None:
    r = await client.post(
        "/api/v1/inspect/schema",
        json={"ddl": "CREATE TABLE orders (id bigint PRIMARY KEY, customer_id int NOT NULL);"},
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schema"]["tables"][0]["name"] == "orders"
    kind = owner.execute(
        "SELECT kind FROM artifacts WHERE sha256 = %s", (body["artifact_sha256"],)
    ).fetchone()
    assert kind == ("schema_snapshot",)


async def test_inspect_requires_a_session(migrated_db: str) -> None:
    engine = make_engine(migrated_db, set_role="qc_app")
    transport = httpx.ASGITransport(app=create_app(Settings(_env_file=None), engine=engine))
    async with httpx.AsyncClient(transport=transport, base_url="https://test") as c:
        c.cookies.set("qc_csrf", "t")
        r = await c.post(
            "/api/v1/inspect/sql", json={"query": "SELECT 1"}, headers={"X-CSRF-Token": "t"}
        )
    await engine.dispose()

    assert r.status_code == 401
