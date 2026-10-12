"""Run outcome and interim report: the materiality verdict decides `no_action_needed`."""

import pytest

from querycure.agents.nodes.write_report import decide
from querycure.domain.runs import RunOutcome, RunStatus
from querycure.reports.interim import BUILDER_VERSION, build_report, render_markdown

RUNNING = RunStatus.RUNNING


def test_not_material_ends_no_action_needed_even_with_hypotheses() -> None:
    assert decide(
        current=RUNNING,
        stop_reason=None,
        has_hypotheses=True,
        has_no_action_evidence=True,
        not_material=True,
    ) == (RunStatus.COMPLETED, RunOutcome.NO_ACTION_NEEDED)


def test_hypotheses_on_a_material_query_stay_recommendations() -> None:
    assert decide(
        current=RUNNING,
        stop_reason=None,
        has_hypotheses=True,
        has_no_action_evidence=False,
        not_material=False,
    ) == (RunStatus.COMPLETED, RunOutcome.UNVERIFIED_RECOMMENDATIONS)


def test_not_material_without_cited_evidence_is_not_no_action() -> None:
    # no_action_needed always needs cited evidence (AGENT_SYSTEM §9).
    assert decide(
        current=RUNNING,
        stop_reason=None,
        has_hypotheses=True,
        has_no_action_evidence=False,
        not_material=True,
    ) == (RunStatus.COMPLETED, RunOutcome.UNVERIFIED_RECOMMENDATIONS)


@pytest.mark.parametrize(
    ("stop", "expected"),
    [
        ("budget_exhausted", (RunStatus.COMPLETED, RunOutcome.INCONCLUSIVE)),
        ("cancelled", (RunStatus.CANCELLED, None)),
        ("failed", (RunStatus.FAILED, None)),
    ],
)
def test_stop_reasons_still_win_over_materiality(
    stop: str, expected: tuple[RunStatus, RunOutcome | None]
) -> None:
    assert (
        decide(
            current=RUNNING,
            stop_reason=stop,
            has_hypotheses=True,
            has_no_action_evidence=True,
            not_material=True,
        )
        == expected
    )


def _report(materiality: dict[str, object] | None) -> dict[str, object]:
    return build_report(
        run_id="r",
        objective="o",
        final_status="completed",
        outcome="no_action_needed",
        stop_reason=None,
        findings=[],
        hypotheses=[],
        evidence=[],
        errors=[],
        usage={},
        synthesis_summary="",
        materiality=materiality,
    )


def test_report_carries_the_materiality_verdict_under_a_new_builder_version() -> None:
    m: dict[str, object] = {
        "verdict": "not_material",
        "reasons": ["Only 50 rows."],
        "evidence_ids": ["ev_1"],
    }

    body = _report(m)

    assert BUILDER_VERSION == "interim-report@2"
    assert body["builder_version"] == "interim-report@2"
    assert body["materiality"] == m
    assert "**Not worth optimizing**" in render_markdown(body)
    assert "Only 50 rows." in render_markdown(body)


def test_report_without_materiality_renders_no_verdict() -> None:
    body = _report(None)

    assert body["materiality"] is None
    assert "Not worth optimizing" not in render_markdown(body)
