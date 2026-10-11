from fastapi import APIRouter, Request
from fastapi.testclient import TestClient

from querydoctor.api.main import create_app
from querydoctor.core.config import Settings


def client() -> TestClient:
    app = create_app(Settings(_env_file=None), engine=None)
    router = APIRouter()

    @router.post("/echo-size")
    async def echo_size(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    app.include_router(router, prefix="/api/v1/test")
    c = TestClient(app)
    c.cookies.set("qd_csrf", "t")
    c.headers["X-CSRF-Token"] = "t"
    return c


def test_bodies_over_the_limit_are_refused_with_413() -> None:
    r = client().post("/api/v1/test/echo-size", content=b"x" * (6 * 1024 * 1024 + 1))

    assert r.status_code == 413
    assert r.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_streamed_bodies_without_content_length_are_counted() -> None:
    def chunks():  # type: ignore[no-untyped-def]
        for _ in range(7):
            yield b"x" * (1024 * 1024)

    r = client().post("/api/v1/test/echo-size", content=chunks())

    assert r.status_code == 413


def test_normal_bodies_pass() -> None:
    r = client().post("/api/v1/test/echo-size", content=b"x" * 1000)

    assert r.json() == {"size": 1000}
