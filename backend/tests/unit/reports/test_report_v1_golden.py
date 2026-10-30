"""Byte-identity guard for the frozen report-builder@1 / report-md@1 (ADR-0015).

The digests in `tests/fixtures/reports/v1_golden.json` were generated at commit e99886d,
before report-builder@2 existed. Every later change must leave them unchanged: v1 output for
every case, with and without the inputs added for v2, is byte-identical.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from querycure.replay.canonical import canonical_json, canonical_text, to_canonical
from querycure.replay.digest import digest
from querycure.reports.builders.v1 import build_report
from querycure.reports.renderers.md_v1 import render_markdown
from tests.unit.reports.test_report_v1 import CASES, FINAL, inputs

GOLDEN = Path(__file__).parents[2] / "fixtures" / "reports" / "v1_golden.json"
REPLAY_COMPARISON: dict[str, Any] = {
    "status": "reproduced",
    "comparison_mode": "same_environment",
    "failure_code": None,
    "pairs": [
        {
            "arm": "oc_1",
            "param_set": "p1",
            "status": "reproduced",
            "code": None,
            "original_speedup": 2.0,
            "replay_speedup": 2.1,
            "drift_ci_low": 0.95,
            "drift_ci_high": 1.1,
        }
    ],
    "environment": {
        "differences": [
            {"field": "os", "class": "minor", "original": "Darwin 25", "replay": "Darwin 26"}
        ]
    },
}
GOLDEN_CASES: dict[str, dict[str, Any]] = {
    **CASES,
    "replay": {"kind": "experiment_replay", "comparison": REPLAY_COMPARISON},
    "replay_inconclusive": {
        "kind": "experiment_replay",
        "outcome": "inconclusive",
        "comparison": {**REPLAY_COMPARISON, "status": "inconclusive"},
    },
}


def digests(report: dict[str, Any]) -> dict[str, str]:
    return {
        "json": digest("qc-json-v1", canonical_json(to_canonical(report))),
        "markdown": digest("qc-text-v1", canonical_text(render_markdown(report))),
    }


def current() -> dict[str, dict[str, str]]:
    return {
        case: digests(build_report(inputs(**kw), **FINAL))  # type: ignore[arg-type]
        for case, kw in GOLDEN_CASES.items()
    }


@pytest.mark.parametrize("case", GOLDEN_CASES)
def test_v1_output_is_byte_identical_to_the_golden(case: str) -> None:
    golden = json.loads(GOLDEN.read_text())
    assert current()[case] == golden[case]


def test_golden_covers_every_case() -> None:
    assert set(json.loads(GOLDEN.read_text())) == set(GOLDEN_CASES)


if __name__ == "__main__":  # regenerate only for a new case, never to absorb a change
    GOLDEN.write_text(json.dumps(current(), indent=2, sort_keys=True) + "\n")


@pytest.mark.parametrize("case", GOLDEN_CASES)
def test_v1_ignores_the_inputs_added_for_v2(case: str) -> None:
    import dataclasses

    from tests.unit.reports.test_report_v2 import snapshot

    golden = json.loads(GOLDEN.read_text())
    changed = dataclasses.replace(
        inputs(**GOLDEN_CASES[case]),  # type: ignore[arg-type]
        replay_source=snapshot(),
        replay_source_error="ignored by v1",
    )
    assert digests(build_report(changed, **FINAL)) == golden[case]  # type: ignore[arg-type]
