"""Source snapshot of an experiment replay, derived from the source's sealed records
(REPLAY_OUTCOME_AUDIT §12.4, §13). Pure part: `snapshot_from_sealed`."""

import copy
from typing import Any

import pytest

from querycure.domain.runs import RunKind, RunOutcome
from querycure.replay.canonical import canonical_json, to_canonical
from querycure.replay.source_snapshot import (
    ReplaySourceSnapshot,
    SourceSnapshotError,
    parse_marker,
    snapshot_from_sealed,
    snapshot_marker,
)

RUN = "00000000-0000-4000-8000-000000000001"
EXP = "00000000-0000-4000-8000-0000000000e1"
EXP2 = "00000000-0000-4000-8000-0000000000e2"
MANIFEST_SHA = "1" * 64
REPORT_SHA = "2" * 64
RESULT = "a" * 64
RESULT2 = "b" * 64
ENV = "sha256:" + "e" * 64


def manifest(**over: Any) -> dict[str, Any]:
    m: dict[str, Any] = {
        "schema_version": 1,
        "run_id": RUN,
        "run_kind": "initial",
        "final_status": "completed",
        "outcome": "verified_recommendation",
        "report": {
            "json": f"sha256:{REPORT_SHA}",
            "markdown": "sha256:" + "3" * 64,
            "report_schema_version": 1,
            "builder_version": "report-builder@1",
            "md_renderer_version": "report-md@1",
        },
        "experiments": [
            {"id": EXP, "result": f"sha256:{RESULT}", "environment": ENV},
            {"id": EXP2, "result": f"sha256:{RESULT2}", "environment": ENV},
        ],
        "artifacts": [],
    }
    m.update(over)
    return m


def recommendation(**over: Any) -> dict[str, Any]:
    r: dict[str, Any] = {
        "status": "verified",
        "candidate_key": "c1",
        "kind": "create_index",
        "ddl": ["CREATE INDEX i ON orders (customer_id)"],
        "query_sql": None,
        "primary_measurement": {
            "arm": "c1",
            "param_set": "default",
            "speedup": 3.0,
            "ci_low": 2.5,
            "ci_high": 3.5,
            "provenance": "measured",
            "evidence_id": "ev_1",
            "source": {"artifact_sha256": RESULT, "pointer": "/stats/0"},
        },
        "scope": "sandbox",
    }
    r.update(over)
    return r


def report(**over: Any) -> dict[str, Any]:
    r: dict[str, Any] = {
        "schema_version": 1,
        "builder_version": "report-builder@1",
        "run": {"id": RUN, "kind": "initial"},
        "final_status": "completed",
        "outcome": "verified_recommendation",
        "recommendation": recommendation(),
        "hypotheses": [{"statement": "not copied"}],
        "evidence": [{"id": "ev_1"}],
        "summary": "LLM text that must not be copied",
    }
    r.update(over)
    return r


def build(
    m: dict[str, Any] | None = None,
    r: dict[str, Any] | None = None,
    *,
    experiment: str = EXP,
    result: str = RESULT,
    arms: tuple[str, ...] = ("c1",),
) -> ReplaySourceSnapshot:
    return snapshot_from_sealed(
        manifest=manifest() if m is None else m,
        report=report() if r is None else r,
        manifest_sha256=MANIFEST_SHA,
        report_json_sha256=REPORT_SHA,
        source_run_id=RUN,
        source_experiment_id=experiment,
        source_experiment_result_sha256=result,
        source_arms=arms,
    )


def test_valid_source_copies_exactly_the_snapshot_fields() -> None:
    s = build()
    assert s.model_dump(mode="json") == {
        "schema_version": 1,
        "source_run_id": RUN,
        "source_run_kind": "initial",
        "source_experiment_id": EXP,
        "source_experiment_result_sha256": RESULT,
        "source_experiment_environment_digest": ENV,
        "source_manifest_sha256": MANIFEST_SHA,
        "source_report_json_sha256": REPORT_SHA,
        "source_builder_version": "report-builder@1",
        "source_final_status": "completed",
        "source_outcome": "verified_recommendation",
        "source_recommendation": recommendation(),
    }
    assert s.source_outcome is RunOutcome.VERIFIED_RECOMMENDATION
    assert s.source_recommendation is not None
    assert s.source_recommendation.measured_result_sha256 == RESULT


def test_no_evidence_lists_llm_text_or_credentials_are_copied() -> None:
    dumped = canonical_json(to_canonical(build().model_dump(mode="json"))).decode()
    for absent in ("hypotheses", "LLM text", "summary", "password", '"evidence"'):
        assert absent not in dumped


def test_serialization_is_deterministic_and_round_trips() -> None:
    a, b = build(), build(copy.deepcopy(manifest()), copy.deepcopy(report()))
    assert a == b
    bytes_a = canonical_json(to_canonical(a.model_dump(mode="json")))
    assert bytes_a == canonical_json(to_canonical(b.model_dump(mode="json")))
    assert ReplaySourceSnapshot.model_validate_json(bytes_a) == a


def test_later_changes_to_the_inputs_cannot_reach_a_snapshot() -> None:
    m, r = manifest(), report()
    before = (copy.deepcopy(m), copy.deepcopy(r))
    snap = build(m, r)
    assert (m, r) == before
    r["recommendation"]["candidate_key"] = "changed"
    r["recommendation"]["primary_measurement"]["speedup"] = 99.0
    m["outcome"] = "inconclusive"
    assert snap.source_recommendation is not None
    assert snap.source_recommendation.candidate_key == "c1"
    assert snap.source_recommendation.primary_measurement is not None
    assert snap.source_recommendation.primary_measurement["speedup"] == 3.0
    assert snap.source_outcome is RunOutcome.VERIFIED_RECOMMENDATION


def test_other_experiment_of_the_source_is_kept_as_measured() -> None:
    """D11 is the classifier's call: a recommendation measured by another experiment of the
    same source is consistent, so the snapshot records it as it is."""
    s = build(experiment=EXP2, result=RESULT2)
    assert s.source_experiment_result_sha256 == RESULT2
    assert s.source_recommendation is not None
    assert s.source_recommendation.measured_result_sha256 == RESULT


NONE_REC = recommendation(
    status="none", candidate_key=None, kind=None, ddl=[], primary_measurement=None
)


def test_inconclusive_source_without_recommendation() -> None:
    s = build(
        manifest(outcome="inconclusive"), report(outcome="inconclusive", recommendation=NONE_REC)
    )
    assert s.source_outcome is RunOutcome.INCONCLUSIVE
    assert s.source_recommendation is not None
    assert s.source_recommendation.status == "none"


def test_failed_source_has_no_outcome() -> None:
    s = build(
        manifest(final_status="failed", outcome=None),
        report(final_status="failed", outcome=None),
    )
    assert s.source_outcome is None
    assert s.source_final_status == "failed"


def test_replay_source_keeps_its_inconsistent_v1_recommendation() -> None:
    """Upgraded report-builder@1 replays seal `verified_recommendation` over an empty
    recommendation. They stay replayable; the classifier never passes their outcome on."""
    s = build(
        manifest(run_kind="experiment_replay"),
        report(run={"id": RUN, "kind": "experiment_replay"}, recommendation=NONE_REC),
    )
    assert s.source_run_kind is RunKind.EXPERIMENT_REPLAY
    assert s.source_outcome is RunOutcome.VERIFIED_RECOMMENDATION


OTHER_SOURCE = {
    **recommendation()["primary_measurement"],
    "source": {"artifact_sha256": "c" * 64, "pointer": "/stats/0"},
}
REJECTED: list[tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]] = [
    ("manifest of another run", manifest(run_id=EXP), report(), {}),
    ("report of another run", manifest(), report(run={"id": EXP, "kind": "initial"}), {}),
    (
        "manifest names another report",
        manifest(report={**manifest()["report"], "json": "sha256:" + "9" * 64}),
        report(),
        {},
    ),
    ("outcome differs between manifest and report", manifest(), report(outcome="inconclusive"), {}),
    ("final status differs", manifest(), report(final_status="failed"), {}),
    (
        "final status is not terminal (never sealed)",
        manifest(final_status="running", outcome=None),
        report(final_status="running", outcome=None),
        {},
    ),
    (
        "unknown final status",
        manifest(final_status="done"),
        report(final_status="done"),
        {},
    ),
    ("unknown run kind", manifest(run_kind="mystery"), report(), {}),
    ("unknown outcome", manifest(outcome="great"), report(outcome="great"), {}),
    ("unsupported manifest schema", manifest(schema_version=2), report(), {}),
    ("report without a recommendation", manifest(), {**report(), "recommendation": None}, {}),
    (
        "recommendation with a missing field",
        manifest(),
        report(recommendation={k: v for k, v in recommendation().items() if k != "ddl"}),
        {},
    ),
    (
        "source experiment not in the manifest",
        manifest(experiments=[manifest()["experiments"][1]]),
        report(),
        {},
    ),
    (
        "experiment result hash differs from the stored result",
        manifest(),
        report(),
        {"result": "f" * 64},
    ),
    (
        "verified outcome without recommendation evidence",
        manifest(),
        report(recommendation=NONE_REC),
        {},
    ),
    (
        "verified outcome, recommendation without a measured source",
        manifest(),
        report(recommendation=recommendation(primary_measurement=None)),
        {},
    ),
    (
        "verified outcome, measured result is not an experiment of the source",
        manifest(),
        report(recommendation=recommendation(primary_measurement=OTHER_SOURCE)),
        {},
    ),
    (
        "verified outcome, candidate is not an arm of the replayed experiment",
        manifest(),
        report(recommendation=recommendation(candidate_key="c9")),
        {},
    ),
]


@pytest.mark.parametrize(("m", "r", "kw"), [x[1:] for x in REJECTED], ids=[x[0] for x in REJECTED])
def test_inconsistent_or_unverifiable_sources_are_rejected(
    m: dict[str, Any], r: dict[str, Any], kw: dict[str, Any]
) -> None:
    with pytest.raises(SourceSnapshotError):
        build(m, r, **kw)


# --- Creation-time marker (Workstream 5, Phase 1) -----------------------------------------


def test_marker_names_the_schema_and_both_linked_digests() -> None:
    marker = snapshot_marker(build())

    assert marker == {
        "schema_version": 1,
        "manifest": f"sha256:{MANIFEST_SHA}",
        "report_json": f"sha256:{REPORT_SHA}",
    }
    assert parse_marker(marker) == (MANIFEST_SHA, REPORT_SHA)


@pytest.mark.parametrize(
    "marker",
    [
        None,
        "yes",
        1,
        [],
        {},
        {"schema_version": 2, "manifest": f"sha256:{MANIFEST_SHA}", "report_json": "sha256:x"},
        {"schema_version": 1, "manifest": f"sha256:{MANIFEST_SHA}"},
        {"schema_version": 1, "manifest": MANIFEST_SHA, "report_json": REPORT_SHA},
        {"schema_version": 1, "manifest": "sha256:", "report_json": f"sha256:{REPORT_SHA}"},
        {"schema_version": 1, "manifest": "sha256:XYZ", "report_json": f"sha256:{REPORT_SHA}"},
        {
            "schema_version": 1,
            "manifest": f"sha256:{MANIFEST_SHA}",
            "report_json": f"sha256:{REPORT_SHA}",
            "extra": True,
        },
        {"schema_version": True, "manifest": f"sha256:{MANIFEST_SHA}", "report_json": "x"},
    ],
    ids=[
        "null",
        "string",
        "int",
        "list",
        "empty",
        "schema",
        "one-digest",
        "bare-digests",
        "empty-digest",
        "not-hex",
        "extra-key",
        "bool-schema",
    ],
)
def test_a_malformed_marker_fails_closed(marker: Any) -> None:
    with pytest.raises(SourceSnapshotError, match="marker"):
        parse_marker(marker)
