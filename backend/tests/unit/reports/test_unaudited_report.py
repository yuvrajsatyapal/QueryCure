"""What a sealed report says about a result whose audit never ran (audit-completeness invariant).

Built with the current, frozen report-builder@2 / report-md@2 from the records `write_report`
leaves behind. Nothing in the builders or renderers changes for this: the records are what
carry the message (a downgraded candidate with its own reason code, the stop reason, and the
`AUDIT_NOT_COMPLETED` error event). Inputs are synthetic unit-test fixtures, not measurements.
"""

import dataclasses
from typing import Any, cast

from querycure.reports.builders import v2
from querycure.reports.inputs import ReportInputs
from querycure.reports.renderers import md_v2
from tests.unit.reports.test_report_v1 import FINAL, inputs

STOP = "budget_exhausted"
DETAIL = (
    "Unaudited: the engine verdict `verified` was not audited (stop reason: budget_exhausted); "
    "the required Benchmark Auditor checks did not run, so it is not reported as verified."
)
ERROR = {
    "node": "write_report",
    "code": "AUDIT_NOT_COMPLETED",
    "message": "1 verified result was not audited and is not reported as verified: "
    "oc_0000000000a3 (stop reason: budget_exhausted).",
    "recoverable": False,
}


def seal(i: ReportInputs) -> tuple[dict[str, Any], str]:
    report = v2.build_report(
        i,
        finalized_at=cast(str, FINAL["finalized_at"]),
        cutoff_seq=cast(int, FINAL["cutoff_seq"]),
        events_digest=cast(str, FINAL["events_digest"]),
    )
    return report, md_v2.render_markdown(report)


def skipped_auditor() -> ReportInputs:
    """Engine verdict verified, auditor skipped: the records AFTER write_report enforces the
    invariant. The outcome is inconclusive and the candidate carries the unaudited reason."""
    base = inputs(outcome="inconclusive", stop_reason=STOP, status="inconclusive")
    candidate = base.candidates[0].model_copy(
        update={"verdict_reasons": [{"code": "audit_not_completed", "detail": DETAIL}]}
    )
    return dataclasses.replace(
        base, verifications=[], candidates=[candidate], errors=[*base.errors, ERROR]
    )


def test_a_result_whose_audit_never_ran_is_not_presented_as_verified() -> None:
    report, markdown = seal(skipped_auditor())

    assert report["recommendation"]["status"] != "verified"
    assert report["recommendation"]["candidate_key"] is None
    assert "Verified recommendation" not in markdown
    assert "verified in the sandbox" not in markdown
    assert "outcome `verified_recommendation`" not in markdown


def test_the_report_says_the_audit_did_not_complete_and_why() -> None:
    report, markdown = seal(skipped_auditor())

    assert report["partial"] is True
    assert report["stop_reason"] == STOP
    assert "**Partial report**" in markdown
    assert "`audit_not_completed`" in markdown
    assert "AUDIT_NOT_COMPLETED" in markdown
    assert "not audited" in markdown
    assert any(e["code"] == "AUDIT_NOT_COMPLETED" for e in report["errors"])


def test_the_report_does_not_claim_the_auditor_found_a_problem() -> None:
    # `audit_downgrade` renders as "the Benchmark Auditor found a reason to doubt the result".
    _, markdown = seal(skipped_auditor())

    assert "found a reason to doubt" not in markdown


def test_the_old_shape_is_what_the_invariant_prevents() -> None:
    """Characterization of the bug: engine winner kept, no audit rows, budget stop. The sealed
    report reads as a verified recommendation, with only the generic 'partial' note."""
    base = inputs()
    unaudited = dataclasses.replace(
        base,
        verifications=[],
        conclusion={**(base.conclusion or {}), "stop_reason": STOP},
    )

    report, markdown = seal(unaudited)

    assert report["recommendation"]["status"] == "verified"
    assert "Verified recommendation" in markdown
    assert "audit_not_completed" not in markdown


def test_an_audited_verified_result_still_reads_as_verified() -> None:
    report, markdown = seal(inputs())

    assert report["recommendation"]["status"] == "verified"
    assert "Verified recommendation" in markdown
    assert "AUDIT_NOT_COMPLETED" not in markdown
