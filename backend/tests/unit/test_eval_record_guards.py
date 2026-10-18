"""Record-mode guards (2026-10-18): free requests are scarce (about 45 a day), so a recording
must not be spent on a contended host, and a failing recording must not replace an existing one.
"""

import pytest

from querycure.evals.preflight import QUIET_FLOOR_NS, quiet_host, should_save


@pytest.mark.parametrize(
    ("passed", "expected_failure", "keep_failing", "save"),
    [
        (True, None, False, True),
        (False, "documented baseline failure", False, True),  # known failures are recorded
        (False, None, False, False),  # the existing recording is kept
        (False, None, True, True),
    ],
)
def test_only_passing_or_declared_failing_recordings_are_saved(
    passed: bool, expected_failure: str | None, keep_failing: bool, save: bool
) -> None:
    assert should_save(passed=passed, expected_failure=expected_failure,
                       keep_failing=keep_failing) is save  # fmt: skip


def test_a_quiet_in_network_host_passes() -> None:
    ok, detail = quiet_host([60_000, 65_000, 70_000, 62_000, 68_000] * 10, path="docker-network")
    assert ok, detail


def test_the_contended_host_of_the_failed_recording_is_refused() -> None:
    # In-network floors of 138-470 us during the failed 2026-10-18 recording vs 60-70 us quiet.
    ok, detail = quiet_host(
        [138_000, 219_000, 470_000, 214_000, 169_000] * 10, path="docker-network"
    )
    assert not ok
    assert "contended" in detail


def test_a_bursty_host_is_refused_even_with_a_low_median() -> None:
    samples = [60_000] * 30 + [900_000] * 20
    ok, _ = quiet_host(samples, path="docker-network")
    assert not ok


def test_relay_thresholds_allow_the_relay_round_trip() -> None:
    ok, detail = quiet_host([330_000, 350_000, 360_000, 340_000] * 10, path="docker-relay")
    assert ok, detail
    assert QUIET_FLOOR_NS["docker-relay"] > QUIET_FLOOR_NS["docker-network"]
