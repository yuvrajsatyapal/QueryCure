import psycopg
import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import exc as sa_exc

from querycure.api.main import create_app
from querycure.core.config import Settings
from querycure.core.errors import SqlNotAllowedError


class Body(BaseModel):
    name: str


def client() -> TestClient:
    app = create_app(Settings(_env_file=None), engine=None)
    router = APIRouter()

    @router.get("/boom-domain")
    async def boom_domain() -> None:
        raise SqlNotAllowedError("Only SELECT.", details=[{"field": "query", "message": "DELETE"}])

    @router.get("/boom-crash")
    async def boom_crash() -> None:
        raise RuntimeError("postgresql://u:hunter2@h/db exploded")

    @router.get("/boom-db-down")
    async def boom_db_down() -> None:
        orig = psycopg.OperationalError("connection to 10.0.0.1 failed: password hunter2")
        raise sa_exc.OperationalError("SELECT 1", {}, orig)

    @router.get("/boom-pool")
    async def boom_pool() -> None:
        raise sa_exc.TimeoutError("QueuePool limit of size 5 overflow 5 reached")

    @router.get("/boom-statement")
    async def boom_statement() -> None:
        orig = psycopg.errors.QueryCanceled("canceling statement due to statement timeout")
        raise sa_exc.OperationalError("SELECT hunter2", {}, orig)

    @router.post("/echo")
    async def echo(body: Body) -> Body:
        return body

    app.include_router(router, prefix="/api/v1/test")
    return TestClient(app, raise_server_exceptions=False)


def test_domain_errors_use_the_envelope_with_request_id() -> None:
    r = client().get("/api/v1/test/boom-domain")

    assert r.status_code == 422
    body = r.json()["error"]
    assert body["code"] == "SQL_NOT_ALLOWED"
    assert body["details"] == [{"field": "query", "message": "DELETE"}]
    assert body["request_id"].startswith("req_")
    assert r.headers["X-Request-ID"] == body["request_id"]


def test_unknown_routes_use_the_envelope() -> None:
    r = client().get("/api/v1/nope")

    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


def test_validation_errors_name_the_fields() -> None:
    c = client()
    c.cookies.set("qc_csrf", "t")

    r = c.post("/api/v1/test/echo", json={}, headers={"X-CSRF-Token": "t"})

    assert r.status_code == 422
    error = r.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"][0]["field"] == "name"


def test_unexpected_errors_are_generic_and_leak_nothing() -> None:
    r = client().get("/api/v1/test/boom-crash")

    assert r.status_code == 500
    assert r.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "hunter2" not in r.text
    assert "exploded" not in r.text


@pytest.mark.parametrize("path", ["boom-db-down", "boom-pool"])
def test_an_unreachable_database_is_a_retryable_503(path: str) -> None:
    r = client().get(f"/api/v1/test/{path}")

    assert r.status_code == 503
    assert r.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert "hunter2" not in r.text
    assert "10.0.0.1" not in r.text


def test_statement_errors_with_a_sqlstate_stay_internal_errors() -> None:
    r = client().get("/api/v1/test/boom-statement")

    assert r.status_code == 500
    assert r.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "hunter2" not in r.text
