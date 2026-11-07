"""The workload catalog and the fixed dataset (Part B, M6): what the API offers, to whom."""

import base64
import os
from typing import Any

import httpx2 as httpx
import pytest

from querycure.api.main import create_app
from querycure.api.routers.investigations import _check_sandbox
from querycure.api.schemas.investigations import CreateInvestigationRequest
from querycure.core.config import Profile, Settings
from querycure.core.errors import ValidationFailedError

FIXED_REF = "online_retail_ii@v1:data=b3471c34b273"
QUERY = "SELECT * FROM retail_lines WHERE invoice_no = $1 ORDER BY line_id"


def demo_settings(*, sandbox: bool = False) -> Settings:
    return Settings(
        _env_file=None,
        profile=Profile.DEMO,
        allow_private_targets=False,
        master_key=base64.b64encode(os.urandom(32)).decode(),
        database_url="postgresql://qc_app:unused@127.0.0.1:1/unused",
        cors_origins=["https://app.test"],
        feature_sandbox=sandbox,
    )


async def catalog(settings: Settings) -> dict[str, dict[str, Any]]:
    transport = httpx.ASGITransport(app=create_app(settings, engine=None))
    async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
        response = await client.get("/api/v1/workloads")
    assert response.status_code == 200
    return {w["name"]: w for w in response.json()["items"]}


async def test_the_local_catalog_offers_the_fixed_dataset_with_its_full_ref() -> None:
    items = await catalog(Settings(_env_file=None))

    fixed = items["online_retail_ii"]
    assert fixed["id"] == "online_retail_ii@v1"
    assert fixed["ref"] == FIXED_REF
    assert fixed["requires_local_data"] is True
    assert fixed["scale_factors"] == []
    assert fixed["default_seed"] is None
    assert fixed["tables"] == ["retail_lines"]
    assert [q["name"] for q in fixed["example_queries"]] == [
        "recent_lines_for_customer",
        "lines_of_invoice",
        "customer_totals_in_window",
    ]
    assert fixed["availability"] == "live"


async def test_generated_workloads_are_listed_exactly_as_before() -> None:
    items = await catalog(Settings(_env_file=None))

    for name in (
        "orders_ecommerce",
        "rewrite_trap",
        "no_benefit",
        "join_fanout",
        "stale_stats",
        "index_regression",
    ):
        item = items[name]
        assert item["id"] == f"{name}@v1"
        assert item["ref"] is None
        assert item["requires_local_data"] is False
        assert item["scale_factors"] == [0.01, 0.1, 1.0]
        assert item["default_seed"] == 42


async def test_the_demo_profile_does_not_offer_fixed_datasets() -> None:
    items = await catalog(demo_settings())

    assert "online_retail_ii" not in items
    assert {"orders_ecommerce", "stale_stats"} <= set(items)
    assert {w["availability"] for w in items.values()} == {"prerecorded"}


def body(workload_id: str) -> CreateInvestigationRequest:
    return CreateInvestigationRequest(
        title="t",
        objective="o",
        modes=["sandbox_benchmark"],
        query=QUERY,
        workload_id=workload_id,
        param_sets=[{"name": "p", "values": ["489450"]}],
    )


def test_the_demo_profile_refuses_a_fixed_dataset_even_if_asked_by_ref() -> None:
    with pytest.raises(ValidationFailedError) as raised:
        _check_sandbox(body(FIXED_REF), demo_settings(sandbox=True))

    assert raised.value.details == [
        {
            "field": "workload_id",
            "message": "this dataset needs local data and is not available on this deployment",
        }
    ]


def test_the_local_profile_accepts_the_fixed_dataset() -> None:
    settings = Settings(_env_file=None, feature_sandbox=True)

    _check_sandbox(body(FIXED_REF), settings)  # does not raise


def test_a_generated_workload_is_still_accepted_in_the_demo_profile() -> None:
    request = CreateInvestigationRequest(
        title="t",
        objective="o",
        modes=["sandbox_benchmark"],
        query="SELECT * FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 20",
        workload_id="orders_ecommerce@v1:sf=0.1:seed=42",
        param_sets=[{"name": "p", "values": [7]}],
    )

    _check_sandbox(request, demo_settings(sandbox=True))  # does not raise
