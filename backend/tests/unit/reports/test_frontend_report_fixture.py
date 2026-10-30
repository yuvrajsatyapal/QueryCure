"""The frontend's schema-2 report fixtures are real builder output (cross-stack contract).

`frontend/src/test/fixtures/report-v2.json` holds report-builder@2 / report-builder@1 output
for synthetic unit-test inputs (no measurement is real), converted to camelCase exactly as the
frontend API client does. If builder output and fixture ever differ, this test fails.
Regenerate (only for a new case):
`uv run python -m tests.unit.reports.test_frontend_report_fixture`.
"""

import dataclasses
import json
import re
from pathlib import Path
from typing import Any

from querycure.reports.builders import v1
from tests.unit.reports.test_report_v1 import FINAL
from tests.unit.reports.test_report_v2 import SCENARIOS, scenario, scenario_inputs

FIXTURE = Path(__file__).parents[4] / "frontend" / "src" / "test" / "fixtures" / "report-v2.json"
CASES = (
    "1_reproduced_original",
    "2_performance_drift",
    "3_not_reproduced_rows",
    "3_not_reproduced_verdict",
    "4_inconclusive_comparison",
    "5_cross_environment",
    "6_noise_warning_source",
    "7_other_experiment",
    "8_inconclusive_source_with_replay_winner",
    "11_source_is_replay",
    "14_not_replayable",
    "14_snapshot_missing",
    "15_execution_failed",
)


def camel(value: Any) -> Any:
    if isinstance(value, list):
        return [camel(v) for v in value]
    if isinstance(value, dict):
        return {
            re.sub(r"_([a-z0-9])", lambda m: m[1].upper(), k): camel(v) for k, v in value.items()
        }
    return value


def fixtures() -> dict[str, Any]:
    assert set(CASES) <= set(SCENARIOS)
    legacy_inputs = scenario_inputs("8_inconclusive_source_with_replay_winner")
    conclusion = {k: v for k, v in (legacy_inputs.conclusion or {}).items() if k != "replay_basis"}
    legacy = v1.build_report(
        dataclasses.replace(
            legacy_inputs, conclusion={**conclusion, "outcome": "verified_recommendation"}
        ),
        **FINAL,  # type: ignore[arg-type]
    )
    return {
        "_note": "Synthetic inputs from backend unit tests; not measurements.",
        **{case: camel(scenario(case)) for case in CASES},
        "legacy_v1_replay": camel(legacy),
    }


def test_frontend_fixture_is_current_builder_output() -> None:
    assert json.loads(FIXTURE.read_text()) == json.loads(json.dumps(fixtures()))


if __name__ == "__main__":
    FIXTURE.write_text(json.dumps(fixtures(), indent=1, sort_keys=True) + "\n")
