import pytest

from querycure.domain.runs import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATUSES,
    RunStatus,
    sources_for,
)


def test_every_status_has_an_entry() -> None:
    assert set(ALLOWED_TRANSITIONS) == set(RunStatus)


@pytest.mark.parametrize("status", sorted(TERMINAL_STATUSES))
def test_terminal_statuses_have_no_exits(status: RunStatus) -> None:
    assert ALLOWED_TRANSITIONS[status] == frozenset()


def test_cancelling_can_only_finish_as_cancelled() -> None:
    assert ALLOWED_TRANSITIONS[RunStatus.CANCELLING] == {RunStatus.CANCELLED}


def test_sources_for_running() -> None:
    assert sources_for(RunStatus.RUNNING) == {RunStatus.QUEUED}


def test_sources_for_cancelled() -> None:
    assert sources_for(RunStatus.CANCELLED) == {
        RunStatus.QUEUED,
        RunStatus.AWAITING_APPROVAL,
        RunStatus.CANCELLING,
    }


def test_dead_lettered_queued_run_can_fail() -> None:
    assert RunStatus.FAILED in ALLOWED_TRANSITIONS[RunStatus.QUEUED]


def test_queued_cannot_jump_to_completed() -> None:
    assert RunStatus.COMPLETED not in ALLOWED_TRANSITIONS[RunStatus.QUEUED]
