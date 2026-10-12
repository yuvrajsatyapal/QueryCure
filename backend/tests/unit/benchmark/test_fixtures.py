"""Prerecorded experiment fixtures (T3.13): exported evidence is labelled prerecorded, and the
loader refuses anything else, so measured and prerecorded samples are never mixed."""

import json
import uuid
from pathlib import Path

import pytest

from querycure.benchmark.fixtures import PrerecordedExperiment, load_prerecorded, to_prerecorded
from querycure.domain.benchmark import (
    CandidateArm,
    EnvironmentFingerprint,
    ExperimentConfig,
    ExperimentResult,
    ParamSetSpec,
)

EXPERIMENT = uuid.UUID(int=7)
CONFIG = ExperimentConfig(
    experiment_id=EXPERIMENT,
    workload_id="orders_ecommerce@v1:sf=0.1:seed=42",
    baseline_query="SELECT 1",
    candidates=[CandidateArm(arm="oc_000000000001", candidate_id=None, kind="analyze_statistics",
                             ddl=["ANALYZE orders"], query=None)],
    param_sets=[ParamSetSpec(name="hot", values=[1])],
    seed=42,
)  # fmt: skip
ENV = EnvironmentFingerprint(
    pg_version="170011",
    pg_settings={"jit": "off"},
    sandbox_image_digest="postgres:17",
    workload_id=CONFIG.workload_id,
    workload_data_digest="d" * 64,
    cpu_arch="aarch64",
    cpu_model="unknown",
    cpu_count=8,
    memory_bytes=1,
    os="Linux",
    container_runtime="docker",
)
RESULT = ExperimentResult(
    experiment_id=EXPERIMENT,
    environment_digest="e" * 64,
    builds=[],
    measurements=[],
    stats=[],
    verdicts=[],
    tournament=[],
    winner=None,
    order_is_total=False,
)


def test_export_relabels_every_layer_as_prerecorded(tmp_path: Path) -> None:
    fixture = to_prerecorded(
        CONFIG, ENV, RESULT, recorded_on="2026-10-12", source_note="local Docker Desktop"
    )
    path = tmp_path / "x.json"
    path.write_text(fixture.model_dump_json(indent=1))

    loaded = load_prerecorded(path)

    assert loaded.provenance == "prerecorded"
    assert loaded.result.provenance == "prerecorded"
    assert loaded.label == "Prerecorded on aarch64 (8 CPUs), Linux, 2026-10-12 — not your database"


def test_measured_evidence_is_refused_on_import(tmp_path: Path) -> None:
    fixture = to_prerecorded(CONFIG, ENV, RESULT, recorded_on="2026-10-12", source_note="x")
    raw = json.loads(fixture.model_dump_json())
    raw["result"]["provenance"] = "measured"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(raw))

    with pytest.raises(ValueError, match="prerecorded"):
        load_prerecorded(path)


def test_fixture_must_belong_to_its_own_experiment(tmp_path: Path) -> None:
    other = RESULT.model_copy(update={"experiment_id": uuid.UUID(int=8)})

    with pytest.raises(ValueError, match="experiment"):
        to_prerecorded(CONFIG, ENV, other, recorded_on="2026-10-12", source_note="x")


def test_committed_demo_fixtures_load() -> None:
    directory = Path(__file__).parents[3] / "evals" / "fixtures" / "experiments"
    paths = sorted(directory.glob("*.json"))

    assert paths, "no prerecorded demo fixtures committed"
    for path in paths:
        fixture = load_prerecorded(path)
        assert isinstance(fixture, PrerecordedExperiment)
        assert fixture.result.verdicts, path.name
