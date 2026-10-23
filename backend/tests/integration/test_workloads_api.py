import httpx2 as httpx
import pytest

from querycure.api.main import create_app
from querycure.core.config import Profile, Settings

pytestmark = pytest.mark.integration


async def test_workloads_catalog_lists_phase1_workloads() -> None:
    transport = httpx.ASGITransport(app=create_app(Settings(_env_file=None), engine=None))
    async with httpx.AsyncClient(transport=transport, base_url="https://test") as c:
        r = await c.get("/api/v1/workloads")

    assert r.status_code == 200
    items = {w["name"]: w for w in r.json()["items"]}
    assert {"orders_ecommerce", "rewrite_trap", "no_benefit"} <= set(items)
    orders = items["orders_ecommerce"]
    assert orders["id"] == "orders_ecommerce@v1"
    assert orders["availability"] == "live"
    assert orders["example_queries"][0]["param_sets"]


async def test_demo_profile_marks_benchmarks_prerecorded() -> None:
    import base64
    import os

    demo = Settings(
        _env_file=None,
        profile=Profile.DEMO,
        allow_private_targets=False,
        master_key=base64.b64encode(os.urandom(32)).decode(),
        # Required to start outside the local profile; never connected (no lifespan here).
        database_url="postgresql://qc_app:unused@127.0.0.1:1/unused",
        cors_origins=["https://app.test"],
    )
    transport = httpx.ASGITransport(app=create_app(demo, engine=None))
    async with httpx.AsyncClient(transport=transport, base_url="https://test") as c:
        r = await c.get("/api/v1/workloads")

    assert {w["availability"] for w in r.json()["items"]} == {"prerecorded"}
