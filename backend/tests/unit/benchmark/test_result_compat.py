"""Compatibility of stored results across engine versions (ADR-0019 § Compatibility).

- Stored bench@1 results (and the committed prerecorded fixtures) must re-serialize to the same
  bytes and digest: content-addressed artifacts cannot silently change.
- The frozen bench@1 rules must reproduce every stored bench@1 statistic and verdict, so a
  replay can be scored with its source experiment's rules.
"""

import json
from pathlib import Path

import pytest

from querycure.benchmark.engine import _correctness
from querycure.benchmark.fixtures import PrerecordedExperiment, load_prerecorded
from querycure.benchmark.rules import CandidateEvidence, assess, compute_stats, evaluate
from querycure.domain.benchmark import (
    BASELINE_ARM,
    ENGINE_VERSION,
    ExperimentResult,
    NoiseScreen,
)
from querycure.replay.canonical import canonical_json, to_canonical
from querycure.sql.validator import validate_select
from tests.unit.benchmark.test_rules import blocks_of

FIXTURES = sorted((Path(__file__).parents[3] / "evals" / "fixtures" / "experiments").glob("*.json"))


def test_engine_version_is_bench2() -> None:
    assert ENGINE_VERSION == "bench@2"


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_stored_bench1_fixture_round_trips_byte_identically(path: Path) -> None:
    raw = path.read_text()
    fixture = load_prerecorded(path)

    assert fixture.result.engine_version == "bench@1"
    assert fixture.result.schema_version == 1
    assert fixture.model_dump_json(indent=1) + "\n" == raw
    stored = json.loads(raw)["result"]
    assert canonical_json(to_canonical(fixture.result)) == canonical_json(stored)
    assert "noise_screens" not in fixture.result.model_dump(mode="json")


def test_schema_and_engine_version_must_agree() -> None:
    body = json.loads(FIXTURES[0].read_text())["result"]

    with pytest.raises(ValueError, match="schema"):
        ExperimentResult.model_validate({**body, "schema_version": 2})
    with pytest.raises(ValueError, match="noise_screens"):
        ExperimentResult.model_validate(
            {**body, "noise_screens": [{"arm": "oc_000000000001", "eligible": False,
                                        "checks": [], "max_robust_cv": None}]}
        )  # fmt: skip


def _evidence(fixture: PrerecordedExperiment, arm: str) -> CandidateEvidence:
    config, result = fixture.config, fixture.result
    meta = validate_select(config.baseline_query).metadata
    by = {(m.arm, m.param_set): m for m in result.measurements}
    names = [p.name for p in config.param_sets]
    base = {ps: by[(BASELINE_ARM, ps)] for ps in names}
    cand = {ps: by[(arm, ps)] for ps in names}
    # Fixtures have no failed samples, so the flattened samples split back into blocks exactly.
    assert all(not m.failures for m in result.measurements)
    return CandidateEvidence(
        arm=next(c for c in config.candidates if c.arm == arm),
        build=next(b for b in result.builds if b.arm == arm),
        baseline=base,
        candidate=cand,
        correctness={
            ps: _correctness(
                base[ps],
                cand[ps],
                has_order=bool(meta.order_by),
                has_limit=meta.limit is not None,
                total=result.order_is_total,
            )
            for ps in names
        },
        blocks={
            ps: blocks_of(base[ps].latencies_ns, cand[ps].latencies_ns, config.block_size)
            for ps in names
        },
    )


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_frozen_bench1_rules_reproduce_stored_verdicts(path: Path) -> None:
    fixture = load_prerecorded(path)
    config, result = fixture.config, fixture.result
    params = validate_select(config.baseline_query).metadata.parameter_count > 0

    for verdict in result.verdicts:
        ev = _evidence(fixture, verdict.arm)
        stats = compute_stats(ev, config)
        assert [stats[s.param_set] for s in result.stats if s.arm == verdict.arm] == [
            s for s in result.stats if s.arm == verdict.arm
        ]
        rescored = evaluate(ev, config, stats, query_has_params=params, engine_version="bench@1")
        assert rescored == verdict


def _sf1() -> PrerecordedExperiment:
    return load_prerecorded(
        next(p for p in FIXTURES if p.stem == "orders_ecommerce_sf1_composite_index")
    )


def test_sf1_recording_under_bench2_keeps_its_verdict_and_gets_a_noise_screen() -> None:
    """The real 177x/270x recording (Phase 3 acceptance #2): one experiment alone stays
    inconclusive under bench@2. The screen says whether it may enter replication."""
    fixture = _sf1()
    (verdict,) = fixture.result.verdicts
    ev = _evidence(fixture, verdict.arm)
    stats = compute_stats(ev, fixture.config)

    v2, screen = assess(ev, fixture.config, stats, query_has_params=True, engine_version="bench@2")

    assert v2 == verdict  # still inconclusive at gate 4: one experiment is never enough
    assert isinstance(screen, NoiseScreen)
    assert screen.eligible, screen


def test_result_keeps_a_typed_serialization_schema() -> None:
    """The API's OpenAPI types are generated from serialization mode: it must stay an object
    with typed properties, not an opaque dict (the frontend reads stats and verdicts)."""
    schema = ExperimentResult.model_json_schema(mode="serialization")

    assert {"stats", "verdicts", "noise_screens", "schema_version"} <= set(schema["properties"])


def test_bench2_result_always_serializes_its_noise_screens() -> None:
    result = ExperimentResult.model_validate(
        {**json.loads(FIXTURES[0].read_text())["result"], "schema_version": 2,
         "engine_version": "bench@2"}
    )  # fmt: skip

    assert result.model_dump(mode="json")["noise_screens"] == []
