import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from querydoctor.api.main import create_app
from querydoctor.core.config import Settings


def client() -> TestClient:
    app = create_app(Settings(_env_file=None), engine=None)
    router = APIRouter()

    @router.post("/mutate")
    async def mutate() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(router, prefix="/api/v1/test")
    return TestClient(app)


@pytest.mark.parametrize(
    ("cookie", "header"),
    [(None, None), ("abc", None), (None, "abc"), ("abc", "xyz"), ("", "")],
)
def test_mutations_without_matching_double_submit_token_are_refused(
    cookie: str | None, header: str | None
) -> None:
    c = client()
    if cookie is not None:
        c.cookies.set("qd_csrf", cookie)
    headers = {"X-CSRF-Token": header} if header is not None else {}

    r = c.post("/api/v1/test/mutate", headers=headers)

    assert r.status_code == 403
    assert r.json()["error"]["code"] == "CSRF_FAILED"


def test_matching_token_is_accepted() -> None:
    c = client()
    c.cookies.set("qd_csrf", "tok-123")

    r = c.post("/api/v1/test/mutate", headers={"X-CSRF-Token": "tok-123"})

    assert r.status_code == 200


def test_safe_methods_do_not_need_a_token() -> None:
    assert client().get("/api/v1/healthz").status_code == 200
