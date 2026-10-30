"""The cross-layer replay matrix against report-builder@2 / report-md@2 (Workstream 5, Phase 3).

`frontend/src/test/fixtures/replay-consistency.json` is the single list of expected values per
scenario. The deterministic end-to-end tests check it on real sealed reports, the frontend
tests on the report view, result summary and run selector, and this module on the builder and
renderer for the synthetic scenario that represents each row (`unit_scenario`). The historical
row is built by the frozen v1 builder, exactly as a pre-activation replay seals today.
"""

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from querycure.reports.builders import v1
from querycure.reports.renderers import md_v1
from tests.unit.reports.test_report_v1 import FINAL
from tests.unit.reports.test_report_v2 import SCENARIOS, render, scenario, scenario_inputs

MATRIX_FILE = (
    Path(__file__).parents[4] / "frontend" / "src" / "test" / "fixtures" / "replay-consistency.json"
)
MATRIX: dict[str, dict[str, Any]] = {
    k: v for k, v in json.loads(MATRIX_FILE.read_text()).items() if not k.startswith("_")
}
V2_ROWS = [name for name, row in MATRIX.items() if not row["legacy"]]

# The ten approved scenarios; the matrix may not silently lose one.
REQUIRED = {
    "reproduced",
    "performance_drift",
    "not_reproduced",
    "inconclusive_comparison",
    "cross_environment",
    "noise_warning_original",
    "replay_of_replay",
    "mismatched_experiment",
    "snapshot_missing",
    "historical_v1",
}


def test_matrix_covers_every_scenario_and_maps_to_a_builder_case() -> None:
    assert set(MATRIX) == REQUIRED
    for name in V2_ROWS:
        assert MATRIX[name]["unit_scenario"] in SCENARIOS, name
    assert MATRIX["historical_v1"]["unit_scenario"] is None


@pytest.mark.parametrize("name", V2_ROWS)
def test_builder_and_markdown_agree_with_the_matrix(name: str) -> None:
    want = MATRIX[name]
    report = scenario(want["unit_scenario"])
    rr = report["replay_result"]
    md = render(report)

    assert (report["schema_version"], report["builder_version"]) == (
        want["schema_version"],
        want["builder_version"],
    )
    assert (report["final_status"], report["outcome"]) == (want["run_status"], want["outcome"])
    assert rr["basis"]["code"] == want["basis"]
    assert (rr["basis"]["comparison_status"], rr["basis"]["comparison_mode"]) == (
        want["comparison_status"],
        want["comparison_mode"],
    )
    assert (rr["result"], rr["title"]) == (want["result"], want["title"])
    assert rr["claims_reproduction"] is want["claims_reproduction"]
    assert rr["original_reproduced"] is want["original_reproduced"]
    assert (report["recommendation"]["status"], report["recommendation"]["origin"]) == (
        want["recommendation_status"],
        want["recommendation_origin"],
    )
    for key in ("material_drift", "correctness_reproduced"):
        if key in want:
            assert rr[key] is want[key], key
    # one headline, led by the title; the selector shows the same title
    assert report["headline"].startswith(want["title"])
    assert want["selector_label"] == want["title"]
    # Markdown: same title and recommendation provenance, never a verification badge
    assert f"> **{want['title']}.**" in md
    assert "Verified recommendation" not in md
    assert ("## Original recommendation" in md) is (want["recommendation_origin"] == "source_run")
    # the replay's own winner is never presented as a recommendation
    winner = rr["replay_measurement"]["engine_winner"]
    if winner and want["recommendation_origin"] != "source_run":
        assert report["recommendation"]["candidate_key"] is None


def test_historical_row_is_the_frozen_v1_contract() -> None:
    """A pre-activation replay: v1 seals the replay's own winner as the outcome. The row records
    that stored outcome; the frontend adds the legacy notice beside it."""
    want = MATRIX["historical_v1"]
    inputs = scenario_inputs("8_inconclusive_source_with_replay_winner")
    conclusion = {k: v for k, v in (inputs.conclusion or {}).items() if k != "replay_basis"}
    report = v1.build_report(
        dataclasses.replace(
            inputs, conclusion={**conclusion, "outcome": "verified_recommendation"}
        ),
        **FINAL,  # type: ignore[arg-type]
    )
    md = md_v1.render_markdown(report)

    assert (report["schema_version"], report["builder_version"]) == (
        want["schema_version"],
        want["builder_version"],
    )
    assert report["outcome"] == want["outcome"]
    assert report["recommendation"]["status"] == want["recommendation_status"]
    assert "origin" not in report["recommendation"]
    assert "replay_result" not in report
    assert want["selector_label"] == report["outcome"].replace("_", " ")
    assert "## Experiment Replay Result" not in md
