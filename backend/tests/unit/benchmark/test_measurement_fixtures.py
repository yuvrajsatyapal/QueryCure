"""FixtureMeasure (R19): recorded measurements fed back through the engine hooks, with every
mismatch refused rather than substituted."""

from pathlib import Path
from typing import Any

import pytest

from querycure.benchmark.engine import ApprovedExperiment, BlockRecord, sql_digest
from querycure.benchmark.fixtures import load_prerecorded
from querycure.benchmark.measurement_fixtures import (
    FixtureMeasure,
    MeasurementFixture,
    MeasurementFixtureMismatchError,
    RecordedReplicate,
    RecordedRound,
)
from querycure.domain.benchmark import EnvironmentFingerprint, ExperimentConfig

FIXTURE = Path(__file__).parents[3] / "evals/fixtures/experiments/index_regression_sf01.json"


class Hooks:
    def __init__(self) -> None:
        self.blocks: list[BlockRecord] = []
        self.env: EnvironmentFingerprint | None = None
        self.states: list[str] = []

    def existing(self) -> list[BlockRecord]:
        return []

    def persist(self, record: BlockRecord) -> None:
        self.blocks.append(record)

    def progress(self, state: str, **details: Any) -> None:
        assert details == {"prerecorded": True}
        self.states.append(state)

    def environment(self, env: EnvironmentFingerprint, env_digest: str) -> None:
        self.env = env

    def cancelled(self) -> bool:
        return False


def _fixture(
    blocks: list[dict[str, Any]] | None = None,
) -> tuple[MeasurementFixture, ExperimentConfig]:
    pre = load_prerecorded(FIXTURE)
    arm = pre.config.candidates[0]
    block = {
        "arm": arm.arm, "candidate_id": str(arm.candidate_id) if arm.candidate_id else None,
        "param_set": "p", "phase": "measure", "block": 0, "latencies_ns": [1, 2, 3],
    }  # fmt: skip
    fixture = MeasurementFixture(
        case_id="c",
        model="m:free",
        recorded_on=pre.recorded_on,
        source_note="unit",
        rounds=[
            RecordedRound(
                replicates=[
                    RecordedReplicate(
                        config=pre.config,
                        environment=pre.environment,
                        env_digest="d",
                        blocks=[block] if blocks is None else blocks,
                        result=pre.result,
                    )
                ],
                replication=None,
            )
        ],
    )
    return fixture, pre.config


def _approved(config: ExperimentConfig, digest: str | None = None) -> ApprovedExperiment:
    return ApprovedExperiment(
        approval_request_id="a",
        approved_sql={c.arm: digest or sql_digest(c) for c in config.candidates},
    )


def test_recorded_round_flows_through_the_hooks_as_prerecorded() -> None:
    fixture, config = _fixture()
    hooks, results = Hooks(), []
    measure = FixtureMeasure(fixture)

    run = measure(
        config, _approved(config), hooks_for=lambda cfg, i: hooks,
        on_result=lambda cfg, i, r: results.append(r),
    )  # fmt: skip

    assert measure.provenance == "prerecorded"
    assert [b.latencies_ns for b in hooks.blocks] == [[1, 2, 3]]
    assert hooks.env == fixture.rounds[0].replicates[0].environment
    assert hooks.states == ["measuring", "scoring"]
    assert [r.provenance for r in results] == ["prerecorded"]
    assert run.replicates[0].result == fixture.rounds[0].replicates[0].result
    assert measure.mismatch is None
    assert measure.unused_rounds() == 0


def test_unapproved_sql_is_refused() -> None:
    fixture, config = _fixture()
    measure = FixtureMeasure(fixture)

    with pytest.raises(MeasurementFixtureMismatchError):
        measure(config, _approved(config, "0" * 64), hooks_for=lambda cfg, i: Hooks())

    assert "not the approved SQL" in (measure.mismatch or "")


def test_a_different_config_is_refused() -> None:
    fixture, config = _fixture()
    measure = FixtureMeasure(fixture)
    other = config.model_copy(update={"seed": config.seed + 1})

    with pytest.raises(MeasurementFixtureMismatchError):
        measure(other, _approved(other), hooks_for=lambda cfg, i: Hooks())

    assert "config differs" in (measure.mismatch or "")


def test_an_extra_round_is_refused() -> None:
    fixture, config = _fixture(blocks=[])
    measure = FixtureMeasure(fixture)
    measure(config, _approved(config), hooks_for=lambda cfg, i: Hooks())

    with pytest.raises(MeasurementFixtureMismatchError):
        measure(config, _approved(config), hooks_for=lambda cfg, i: Hooks())

    assert "round 2" in (measure.mismatch or "")


def test_measured_results_are_refused_in_a_fixture() -> None:
    fixture, _ = _fixture()
    rep = fixture.rounds[0].replicates[0]
    measured = rep.result.model_copy(update={"provenance": "measured"})

    with pytest.raises(ValueError, match="labelled prerecorded"):
        MeasurementFixture.model_validate(
            {
                **fixture.model_dump(),
                "rounds": [
                    {"replicates": [{**rep.model_dump(), "result": measured.model_dump()}],
                     "replication": None}
                ],
            }
        )  # fmt: skip
