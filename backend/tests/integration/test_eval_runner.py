"""Eval runner (T2.14): record with a fake model, replay deterministically, detect drift."""

from pathlib import Path

import pytest

from querycure.core.config import Settings
from querycure.evals.cases import load_cases
from querycure.evals.runner import run_case
from tests.fake_llm import RoleClient
from tests.integration.conftest import ADMIN_URL
from tests.integration.test_investigation_graph import happy_scripts

pytestmark = pytest.mark.integration

SETTINGS = Settings(_env_file=None)
MODEL = "test/fake-model:free"


def case(case_id: str):  # type: ignore[no-untyped-def]
    return next(c for c in load_cases() if c.id == case_id)


async def test_recorded_case_replays_to_the_same_result(tmp_path: Path) -> None:
    orders = case("orders_missing_composite_index")
    recorded = await run_case(
        orders,
        mode="record",
        model=MODEL,
        settings=SETTINGS,
        admin_url=ADMIN_URL,
        cap=None,
        reference_tools={},
        recordings_dir=tmp_path,
        live_client=RoleClient(happy_scripts()),
    )
    replayed = await run_case(
        orders,
        mode="replay",
        model=MODEL,
        settings=SETTINGS,
        admin_url=ADMIN_URL,
        cap=None,
        reference_tools={},
        recordings_dir=tmp_path,
    )

    assert recorded.error is None, recorded.error
    assert replayed.error is None, replayed.error
    assert recorded.score is not None
    assert replayed.score is not None
    assert replayed.score.metrics == recorded.score.metrics
    assert [c.passed for c in replayed.score.checks] == [c.passed for c in recorded.score.checks]
    assert replayed.passed, [c for c in replayed.score.checks if not c.passed]


async def test_replay_without_a_recording_fails_the_case(tmp_path: Path) -> None:
    result = await run_case(
        case("orders_plain_explain"),
        mode="replay",
        model=MODEL,
        settings=SETTINGS,
        admin_url=ADMIN_URL,
        cap=None,
        reference_tools={},
        recordings_dir=tmp_path,
    )

    assert not result.passed
    assert "no recording" in (result.error or "")


async def test_budget_case_passes_with_two_calls(tmp_path: Path) -> None:
    result = await run_case(
        case("orders_budget_exhaustion"),
        mode="record",
        model=MODEL,
        settings=SETTINGS,
        admin_url=ADMIN_URL,
        cap=None,
        reference_tools={},
        recordings_dir=tmp_path,
        live_client=RoleClient(happy_scripts()),
    )

    assert result.passed, result.score.checks if result.score else result.error
    assert result.score is not None
    assert result.score.metrics["llm_calls"] == 2
