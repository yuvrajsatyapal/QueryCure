"""Ordinary investigations under report-builder@2 / report-md@2 (REPLAY_OUTCOME_AUDIT §18.3).

Before v2 becomes the default for every new report, each ordinary (non-replay) report shape
is built with both versions from the same inputs. v2 must be v1 plus exactly three additive
fields (`schema_version`, `builder_version`, `recommendation.origin = "run"`): same outcome,
verdicts, recommendation, measurements and confidence intervals, and Markdown that differs
only in the version line. Inputs are synthetic (unit-test fixtures), not measurements.

Regenerate the frontend fixture (only for a new case):
`uv run python -m tests.unit.reports.test_ordinary_v2_compatibility`.
"""

import copy
import dataclasses
import json
import re
import uuid
from pathlib import Path
from typing import Any

import pytest

from querycure.replay.canonical import canonical_json
from querycure.reports.builders import v1, v2
from querycure.reports.inputs import ReportInputs
from querycure.reports.provenance import unlabeled_numbers
from querycure.reports.renderers import md_v1, md_v2
from tests.unit.reports.test_frontend_report_fixture import camel
from tests.unit.reports.test_report_v1 import CASES, FINAL, inputs

FRONTEND_FIXTURE = (
    Path(__file__).parents[4] / "frontend" / "src" / "test" / "fixtures" / "report-v2-ordinary.json"
)


def _no_action() -> ReportInputs:
    base = inputs(outcome="no_action_needed", with_experiment=False, status="proposed")
    plan_id = base.evidence[0].id
    conclusion = {
        **(base.conclusion or {}),
        "materiality": {
            "verdict": "immaterial",
            "reasons": ["The query took 2 ms."],
            "evidence_ids": [plan_id],
        },
        "no_action_evidence": [plan_id],
    }
    return dataclasses.replace(base, conclusion=conclusion, candidates=[], approvals=[])


def _failed() -> ReportInputs:
    base = inputs(outcome=None, final_status="failed", stop_reason="dead_letter")
    exp = {**base.experiments[0], "status": "failed", "result": None, "result_sha256": None}
    exp["error"] = {"code": "SANDBOX_UNAVAILABLE", "message": "sandbox did not answer"}
    conclusion = {
        **(base.conclusion or {}),
        "error": {"code": "DEAD_LETTER", "message": "the job failed 3 times"},
    }
    return dataclasses.replace(base, experiments=[exp], verifications=[], conclusion=conclusion)


def _missing_evidence() -> ReportInputs:
    base = inputs(outcome=None, final_status="cancelled", stop_reason="cancelled")
    return dataclasses.replace(
        base,
        conclusion=None,
        query_sql=None,
        query_sha256=None,
        param_sets=None,
        hypotheses=[],
        findings=[],
        candidates=[],
        approvals=[],
        experiments=[],
        verifications=[],
        llm_calls=[],
    )


def _replicated() -> ReportInputs:
    """Three replicates of one experiment, two parameter sets each (the noise-warning path)."""
    base = inputs(verdict_override="verified_with_noise_warning")
    first = base.experiments[0]
    assert len(first["config"]["param_sets"]) >= 2
    run = uuid.UUID(base.run["id"])
    arm = base.candidates[0].key
    others = [
        {**copy.deepcopy(first), "id": str(uuid.uuid5(run, f"replicate-{i}")), "replicate": i}
        for i in (1, 2)
    ]
    ids = [first["id"]] + [o["id"] for o in others]
    replication = {
        "schema_version": 1,
        "engine_version": first["engine_version"],
        "source_experiment_id": first["id"],
        "replicates_required": 3,
        "verdicts": [
            {
                "arm": arm,
                "verdict": "verified_with_noise_warning",
                "reasons": [],
                "experiment_ids": ids,
                "primary_param_set": first["config"]["param_sets"][0]["name"],
                "ci_low": 1.4,
                "ci_high": 3.1,
                "max_robust_cv": 0.21,
            }
        ],
        "winner": arm,
    }
    return dataclasses.replace(base, experiments=[{**first, "replication": replication}, *others])


def _no_optional_provenance() -> ReportInputs:
    base = inputs()
    exp = {**base.experiments[0], "environment": None, "environment_digest": None}
    conclusion = {k: v for k, v in (base.conclusion or {}).items() if k != "usage"}
    return dataclasses.replace(base, experiments=[exp], llm_calls=[], conclusion=conclusion)


MATRIX: dict[str, ReportInputs] = {
    **{name: inputs(**kw) for name, kw in CASES.items()},  # type: ignore[arg-type]
    "no_action_needed": _no_action(),
    "failed_execution": _failed(),
    "missing_evidence": _missing_evidence(),
    "multiple_experiments": _replicated(),
    "no_optional_provenance": _no_optional_provenance(),
}
# The rows the request names, mapped to the matrix (every one must exist).
REQUIRED = {
    "verified recommendation": "verified",
    "no action needed": "no_action_needed",
    "inconclusive": "inconclusive",
    "rejected candidate": "rejected",
    "correctness failure": "mismatch",
    "missing evidence": "missing_evidence",
    "noise warning": "noise_warning",
    "failed execution": "failed_execution",
    "cancelled execution": "cancelled",
    "multiple experiments and parameter sets": "multiple_experiments",
    "missing optional provenance": "no_optional_provenance",
}
ADDITIVE = {("schema_version",), ("builder_version",), ("recommendation", "origin")}


def both(name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    inp = MATRIX[name]
    return v1.build_report(inp, **FINAL), v2.build_report(inp, **FINAL)  # type: ignore[arg-type]


def diff_paths(a: Any, b: Any, path: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    if isinstance(a, dict) and isinstance(b, dict):
        out: set[tuple[str, ...]] = set()
        for k in a.keys() | b.keys():
            if k not in a or k not in b:
                out.add((*path, k))
            else:
                out |= diff_paths(a[k], b[k], (*path, k))
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return set().union(*(diff_paths(x, y, (*path, "[]")) for x, y in zip(a, b, strict=True)))
    return set() if a == b else {path}


def test_the_matrix_covers_every_requested_shape() -> None:
    assert set(REQUIRED.values()) <= set(MATRIX)
    assert all(MATRIX[n].run["kind"] != v2.REPLAY for n in MATRIX)


@pytest.mark.parametrize("name", MATRIX)
def test_v2_adds_exactly_three_fields_and_changes_nothing_else(name: str) -> None:
    one, two = both(name)
    assert diff_paths(one, two) == {("schema_version",), ("builder_version",)} | (
        {("recommendation", "origin")} if "origin" not in one["recommendation"] else set()
    )
    assert diff_paths(one, two) <= ADDITIVE
    assert (two["schema_version"], two["builder_version"]) == (2, "report-builder@2")
    assert two["recommendation"]["origin"] == "run"
    assert "replay_result" not in two


@pytest.mark.parametrize("name", MATRIX)
def test_outcome_verification_and_recommendation_semantics_are_unchanged(name: str) -> None:
    one, two = both(name)
    for key in ("final_status", "outcome", "stop_reason", "partial", "headline", "next_steps"):
        assert two[key] == one[key], key
    # Candidate verdicts, auditor downgrades, measurements and confidence intervals.
    assert two["rounds"] == one["rounds"]
    assert two["evidence"] == one["evidence"]
    assert two["limitations"] == one["limitations"]
    assert two["missing"] == one["missing"]
    rec_two = {k: v for k, v in two["recommendation"].items() if k != "origin"}
    assert rec_two == one["recommendation"]
    # No recommendation is invented: a recommended candidate is one the run itself verified.
    key = two["recommendation"]["candidate_key"]
    verified = {
        c["key"]
        for rnd in two["rounds"]
        for c in rnd["candidates"]
        if c["status"] in ("verified", "verified_with_noise_warning")
    }
    assert key is None or key in verified
    if key is None:
        assert two["outcome"] != "verified_recommendation"


@pytest.mark.parametrize("name", MATRIX)
def test_markdown_differs_only_in_the_version_line_and_stays_labeled(name: str) -> None:
    one, two = both(name)
    md_one, md_two = md_v1.render_markdown(one), md_v2.render_markdown(two)
    lines = list(zip(md_one.splitlines(), md_two.splitlines(), strict=True))
    changed = [b for a, b in lines if a != b]
    assert len(changed) == 1
    assert "`report-builder@2`, rendered by `report-md@2`, report schema 2" in changed[0]
    assert unlabeled_numbers(md_two) == []
    # JSON and Markdown agree on the conclusion.
    assert two["headline"] in md_two
    if two["recommendation"]["candidate_key"]:
        assert two["recommendation"]["candidate_key"] in md_two


@pytest.mark.parametrize("name", MATRIX)
def test_v2_builds_and_renders_deterministically(name: str) -> None:
    a, b = both(name)[1], both(name)[1]
    assert canonical_json(a) == canonical_json(b)
    assert md_v2.render_markdown(a) == md_v2.render_markdown(b)


def test_export_wrapper_fields_survive_snake_to_camel_conversion() -> None:
    """The frontend reads `schemaVersion`, `builderVersion`, `recommendation.origin`."""
    two = camel(both("verified")[1])
    assert (two["schemaVersion"], two["builderVersion"]) == (2, "report-builder@2")
    assert two["recommendation"]["origin"] == "run"


def frontend_fixtures() -> dict[str, Any]:
    return {
        "_note": "report-builder@2 output for ordinary investigations; synthetic unit-test "
        "inputs, not measurements.",
        **{name: camel(both(name)[1]) for name in REQUIRED.values()},
    }


def test_frontend_ordinary_fixture_is_current_builder_output() -> None:
    assert json.loads(FRONTEND_FIXTURE.read_text()) == json.loads(json.dumps(frontend_fixtures()))


def test_no_frontend_report_key_is_snake_case() -> None:
    """Case names are snake_case; the reports inside are camelCase, as the client sees them."""
    for name, body in json.loads(FRONTEND_FIXTURE.read_text()).items():
        if name != "_note":
            assert not re.search(r'"[a-z]+_[a-z0-9_]+":', json.dumps(body)), name


if __name__ == "__main__":
    FRONTEND_FIXTURE.write_text(json.dumps(frontend_fixtures(), indent=1, sort_keys=True) + "\n")
