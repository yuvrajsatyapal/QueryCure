"""Public demo gallery (T5.5): shipped bundles are prerecorded, labelled, verifiable without a
database, and tampering is detected. No session, no execution."""

import base64
import json
from pathlib import Path

import httpx2 as httpx
import pytest

from querycure.api.main import create_app
from querycure.core.config import Settings
from querycure.demo.gallery import DemoBundle, load_benchmark_fixtures, load_bundles, verify_bundle


def _client() -> httpx.AsyncClient:
    app = create_app(Settings(_env_file=None))  # no database: the gallery never needs one
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def test_every_shipped_bundle_is_prerecorded_labelled_and_consistent() -> None:
    bundles = load_bundles()
    assert len(bundles) >= 5
    for bundle in bundles:
        assert bundle.provenance == "prerecorded"
        assert "not a live run" in bundle.label
        assert all(c.passed for c in verify_bundle(bundle)), bundle.slug
        if bundle.source.measurement_fixture_sha256:
            assert "prerecorded" in bundle.report()["provenance"]["measurements"]
            assert "measured" not in bundle.report()["provenance"]["measurements"]


def test_tampered_report_or_artifact_fails_verification() -> None:
    bundle = next(b for b in load_bundles() if b.artifacts)
    report = bundle.report()
    report["headline"] = "A candidate change was verified."  # a forged claim
    forged = bundle.model_copy(
        update={"report_json_b64": base64.b64encode(json.dumps(report).encode()).decode()}
    )
    assert not next(c for c in verify_bundle(forged) if c.name == "report_json").passed
    art = bundle.artifacts[0].model_copy(
        update={"content_b64": base64.b64encode(b"SELECT 'swapped'").decode()}
    )
    swapped = bundle.model_copy(update={"artifacts": [art, *bundle.artifacts[1:]]})
    assert not all(c.passed for c in verify_bundle(swapped))


def test_bundles_that_claim_to_be_measured_are_refused(tmp_path: Path) -> None:
    raw = json.loads(next(iter(load_bundles())).model_dump_json())
    raw["provenance"] = "measured"
    (tmp_path / "x.json").write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="prerecorded"):
        load_bundles.__wrapped__(tmp_path)  # type: ignore[attr-defined]


def test_benchmark_fixtures_cover_verified_and_rejected_verdicts() -> None:
    verdicts = {v.verdict for e in load_benchmark_fixtures() for v in e.result.verdicts}
    assert {"verified", "rejected", "inconclusive"} <= verdicts
    assert all(e.result.provenance == "prerecorded" for e in load_benchmark_fixtures())


async def test_gallery_api_is_public_read_only_and_labelled() -> None:
    async with _client() as client:
        listing = await client.get("/api/v1/demo/gallery")
        slug = listing.json()["items"][0]["slug"]
        detail = await client.get(f"/api/v1/demo/gallery/{slug}")
        check = await client.get(f"/api/v1/demo/gallery/{slug}/verification")
        missing = await client.get("/api/v1/demo/gallery/does-not-exist")
        write = await client.post(f"/api/v1/demo/gallery/{slug}")
    assert listing.status_code == 200  # no session cookie was ever created
    body = listing.json()
    assert all(i["provenance"] == "prerecorded" and i["label"] for i in body["items"])
    assert all(b["provenance"] == "prerecorded" for b in body["benchmarks"])
    assert detail.json()["report"]["schema_version"] == 1
    assert detail.json()["label"] == body["items"][0]["label"]
    assert check.json()["status"] == "consistent"
    assert "not proof of authenticity" in check.json()["scope"]
    assert missing.status_code == 404
    assert write.status_code in (403, 405)  # CSRF or no such method: nothing is writable


async def test_mode_c_bundle_exposes_plans_and_benchmark_results() -> None:
    sandbox = next(b for b in load_bundles() if b.source.measurement_fixture_sha256)
    async with _client() as client:
        detail = (await client.get(f"/api/v1/demo/gallery/{sandbox.slug}")).json()
    assert detail["plans"]
    assert detail["plans"][0]["plan"]["nodes"]
    assert any(a["role"] == "experiment.result" for a in detail["artifacts"])
    assert detail["source"]["measurements_recorded_on"]


def test_bundle_model_is_strict() -> None:
    raw = json.loads(next(iter(load_bundles())).model_dump_json())
    raw["unexpected"] = 1
    with pytest.raises(ValueError, match="unexpected"):
        DemoBundle.model_validate(raw)
