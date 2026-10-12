"""Eval case files (`backend/evals/cases/*.yaml`)."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from querycure.domain.investigation import HypothesisCategory

EVALS_DIR = Path(__file__).resolve().parents[3] / "evals"
Suite = Literal["smoke", "full"]
DEFAULT_SUITES: list[Suite] = ["smoke", "full"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Expect(Strict):
    outcome_in: list[str] = Field(default_factory=list)
    root_cause_any_of: list[HypothesisCategory] = Field(default_factory=list)
    top_cites_node_types_any_of: list[str] = Field(default_factory=list)
    stop_reason: str | None = None
    partial: bool | None = None
    max_high_confidence_wrong: int | None = None
    same_tools_as_case: str | None = None  # reported, not pass/fail (live models vary)
    # Tool names that appear only in injected text: attempting any of them fails the case.
    injected_tool_names: list[str] = Field(default_factory=list)
    # Deterministic materiality verdict the run must reach (evidence/materiality.py).
    materiality: Literal["material", "not_material", "undetermined"] | None = None


class Forbid(Strict):
    claims_matching: list[str] = Field(default_factory=list)
    refused_tools: bool = True  # an attempted non-allowlisted tool fails the case


class BudgetOverride(Strict):
    llm_calls: int | None = None
    tool_calls_per_agent: int | None = None


class EvalCase(Strict):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    description: str
    suites: list[Suite] = Field(default_factory=lambda: list(DEFAULT_SUITES))
    query: str
    plan: str | None = None  # file in evals/fixtures/plans
    schema_ddl: str | None = None
    objective: str = "Why is this query slow, and what should change?"
    budget: BudgetOverride = BudgetOverride()
    expect: Expect = Expect()
    forbid: Forbid = Forbid()
    # Recorded baseline failures per model: reported as XFAIL, flipped to XPASS when fixed.
    known_failures: dict[str, str] = Field(default_factory=dict)


def load_cases(directory: Path = EVALS_DIR / "cases") -> list[EvalCase]:
    cases = [
        EvalCase.model_validate(yaml.safe_load(path.read_text()))
        for path in sorted(directory.glob("*.yaml"))
    ]
    ids = [c.id for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate eval case ids")
    return cases
