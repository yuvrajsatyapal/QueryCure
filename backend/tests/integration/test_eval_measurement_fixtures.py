"""Deterministic Mode C evals (R19, Phase 5): record once with live measurements, then replay
the case any number of times from the captured measurement fixture with exact prompt
matching and identical scores. Tampering is a visible failure, never a pass."""

import json
from pathlib import Path

import pytest
from pydantic import SecretStr

from querycure.core.config import Settings
from querycure.evals.runner import measurement_fixture_path, run_case
from querycure.sandbox.provisioner import SandboxProvisioner
from tests.fake_llm import RoleClient
from tests.integration.conftest import ADMIN_URL
from tests.integration.sandbox_fixtures import SANDBOX_URL
from tests.integration.test_eval_runner import MODEL, case
from tests.integration.test_optimization_graph import INDEX, NOTHING_MORE, candidates, scripts

pytestmark = pytest.mark.integration


@pytest.fixture
def settings(provisioner: SandboxProvisioner, bench_password: str) -> Settings:
    return Settings(
        _env_file=None,
        sandbox_admin_url=SecretStr(SANDBOX_URL),
        sandbox_bench_password=SecretStr(bench_password),
    )


async def _replay(settings: Settings, tmp_path: Path, measurements: str = "fixture"):  # type: ignore[no-untyped-def]
    return await run_case(
        case("orders_sandbox_composite_index"),
        mode="replay",
        model=MODEL,
        settings=settings,
        admin_url=ADMIN_URL,
        cap=None,
        recordings_dir=tmp_path / "rec",
        fixtures_dir=tmp_path / "fix",
        measurements=measurements,  # type: ignore[arg-type]
    )


async def test_mode_c_case_replays_deterministically_from_its_fixture(
    settings: Settings, tmp_path: Path
) -> None:
    sandbox_case = case("orders_sandbox_composite_index")
    recorded = await run_case(
        sandbox_case,
        mode="record",
        model=MODEL,
        settings=settings,
        admin_url=ADMIN_URL,
        cap=None,
        recordings_dir=tmp_path / "rec",
        fixtures_dir=tmp_path / "fix",
        live_client=RoleClient(scripts([candidates(INDEX), NOTHING_MORE, NOTHING_MORE])),
    )
    assert recorded.error is None, recorded.error
    fixture_file = measurement_fixture_path(sandbox_case, MODEL, tmp_path / "fix")
    fixture = json.loads(fixture_file.read_text())
    assert fixture["provenance"] == "prerecorded"
    replicates = [r for round_ in fixture["rounds"] for r in round_["replicates"]]
    assert all(r["result"]["provenance"] == "prerecorded" for r in replicates)
    assert replicates[0]["blocks"], "raw blocks are kept for the auditor's checks"

    assert fixture["context"]["explains"], "the sandbox context reads are recorded too"
    # Replays get no sandbox configuration at all: nothing may touch a sandbox server.
    offline = Settings(_env_file=None)
    first = await _replay(offline, tmp_path)
    second = await _replay(offline, tmp_path)

    for replayed in (first, second):
        assert replayed.error is None, replayed.error
        assert replayed.score is not None
        assert recorded.score is not None
        assert replayed.provenance["measurements"] == "fixture"
        assert replayed.provenance["context"] == "recorded"
        assert replayed.provenance["measurement_fixture_sha256"]
        assert replayed.provenance["prompt_versions"]["benchmark_auditor"] == "benchmark_auditor@1"
        assert replayed.provenance["scoring_version"] == "eval-scoring@1"
        # Identical decisions to the recording: every check, and the scored metrics.
        assert [(c.name, c.passed) for c in replayed.score.checks] == [
            (c.name, c.passed) for c in recorded.score.checks
        ]
        assert replayed.score.metrics == recorded.score.metrics
    assert first.score is not None
    assert second.score is not None
    assert [c.detail for c in first.score.checks] == [c.detail for c in second.score.checks]

    # Tampered measurements change what the auditor is shown: the replay fails loudly.
    data = json.loads(fixture_file.read_text())
    stats = data["rounds"][0]["replicates"][0]["result"]["stats"][0]
    stats["speedup"] = stats["speedup"] * 3
    fixture_file.write_text(json.dumps(data))
    tampered = await _replay(offline, tmp_path)
    assert not tampered.passed
    assert "re-record" in (tampered.error or "")

    # A fixture whose candidate SQL differs from the run's approved SQL is refused.
    first_config = data["rounds"][0]["replicates"][0]["config"]
    first_config["candidates"][0]["ddl"] = ["CREATE INDEX ON orders (status)"]
    fixture_file.write_text(json.dumps(data))
    swapped = await _replay(offline, tmp_path)
    assert not swapped.passed
    assert "measurement fixture mismatch" in (swapped.error or "")

    # Without a fixture the case fails with instructions; it is never silently re-measured.
    fixture_file.unlink()
    missing = await _replay(offline, tmp_path)
    assert not missing.passed
    assert "no measurement fixture" in (missing.error or "")
