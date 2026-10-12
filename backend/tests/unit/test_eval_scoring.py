"""Eval scoring of the deterministic materiality verdict (decision-level, no LLM judge)."""

import pytest

from querycure.evals.cases import EvalCase
from querycure.evals.scoring import Observed, score


def observed(materiality: str | None) -> Observed:
    return Observed(
        status="completed",
        outcome="no_action_needed",
        stop_reason=None,
        partial=False,
        hypotheses=[],
        findings=[],
        evidence={},
        tools=[],
        llm_calls=1,
        input_tokens=1,
        output_tokens=1,
        served_models=[],
        claims_dropped=0,
        errors=[],
        materiality=materiality,
    )


CASE = EvalCase.model_validate(
    {"id": "c", "description": "d", "query": "SELECT 1", "expect": {"materiality": "not_material"}}
)


@pytest.mark.parametrize(
    ("seen", "passed"), [("not_material", True), ("material", False), (None, False)]
)
def test_materiality_verdict_is_scored(seen: str | None, passed: bool) -> None:
    result = score(CASE, observed(seen), other_tools={})

    [check] = [c for c in result.checks if c.name == "materiality"]
    assert check.passed is passed
    assert result.metrics["materiality"] == seen


def test_cases_without_a_materiality_expectation_skip_the_check() -> None:
    case = CASE.model_copy(update={"expect": CASE.expect.model_copy(update={"materiality": None})})

    result = score(case, observed("material"), other_tools={})

    assert "materiality" not in {c.name for c in result.checks}
