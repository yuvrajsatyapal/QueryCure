"""CORS preflight for the headers the web client actually sends (found in browser testing)."""

import httpx2 as httpx
import pytest

from querycure.api.main import create_app
from querycure.core.config import Settings

ORIGIN = "http://localhost:3000"


@pytest.mark.parametrize(
    ("method", "headers"),
    [
        ("POST", "content-type,x-csrf-token,idempotency-key"),
        ("GET", "last-event-id"),
    ],
)
async def test_preflight_allows_client_headers(method: str, headers: str) -> None:
    app = create_app(Settings(_env_file=None, cors_origins=[ORIGIN]), engine=None)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.options(
            "/api/v1/investigations",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": headers,
            },
        )

    assert r.status_code == 200, r.text
    allowed = r.headers["access-control-allow-headers"].lower()
    for header in headers.split(","):
        assert header in allowed
