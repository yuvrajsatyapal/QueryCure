"""Transport floor (BENCHMARK_ENGINE §4 step 7): a diagnostic recorded beside bench@2 results.

It never touches samples, statistics or verdicts, and a result without it serializes exactly as
before (stored results keep their bytes and digests)."""

import json
from pathlib import Path

import pytest

from querycure.benchmark.fixtures import load_prerecorded
from querycure.domain.benchmark import TRANSPORT_DOMINATED_SHARE, TransportFloor, transport_floor

FIXTURES = sorted((Path(__file__).parents[3] / "evals" / "fixtures").rglob("*.json"))


def test_floor_summarizes_both_windows_and_its_share_of_the_fastest_arm() -> None:
    floor = transport_floor(
        before=[300_000, 320_000, 310_000], after=[330_000, 290_000, 310_000],
        arm_medians_ns=[3_600_000.0, 480_000.0],
    )  # fmt: skip
    assert floor.samples == 6
    assert floor.before_median_ns == 310_000
    assert floor.after_median_ns == 310_000
    assert floor.median_ns == 310_000
    assert floor.share_of_fastest_arm == pytest.approx(310_000 / 480_000, rel=1e-3)
    assert floor.transport_dominated  # >= TRANSPORT_DOMINATED_SHARE of the fastest median
    assert TRANSPORT_DOMINATED_SHARE == 0.5


def test_in_network_floor_is_not_transport_dominated() -> None:
    floor = transport_floor(before=[60_000] * 5, after=[65_000] * 5, arm_medians_ns=[240_000.0])
    assert not floor.transport_dominated
    assert floor.share_of_fastest_arm == pytest.approx(0.26, abs=0.01)


def test_no_arm_medians_means_no_share() -> None:
    floor = transport_floor(before=[1], after=[], arm_medians_ns=[])
    assert floor.share_of_fastest_arm is None
    assert not floor.transport_dominated


def test_empty_windows_are_refused() -> None:
    with pytest.raises(ValueError, match="sample"):
        transport_floor(before=[], after=[], arm_medians_ns=[1.0])


@pytest.mark.parametrize("path", [p for p in FIXTURES if "result" in p.read_text()],
                         ids=lambda p: p.stem)  # fmt: skip
def test_stored_results_have_no_floor_and_keep_their_bytes(path: Path) -> None:
    try:
        fixture = load_prerecorded(path)
    except Exception:  # not an experiment fixture
        pytest.skip("not a prerecorded experiment")
    assert fixture.result.transport_floor is None
    assert "transport_floor" not in json.loads(fixture.result.model_dump_json())


def test_floor_round_trips_when_present() -> None:
    floor = transport_floor(before=[10, 20], after=[30], arm_medians_ns=[100.0])
    assert TransportFloor.model_validate_json(floor.model_dump_json()) == floor
