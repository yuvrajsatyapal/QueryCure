"""Optimization materiality gate: deterministic, multi-signal, never a single latency cutoff."""

import json
import uuid
from pathlib import Path

import pytest

from querycure.domain.investigation import Evidence, Hypothesis, JsonScalar
from querycure.evidence.builders import plan_evidence
from querycure.evidence.ids import evidence_id
from querycure.evidence.materiality import (
    SMALL_WORK_ROWS,
    assess_materiality,
    gate_hypotheses,
)
from querycure.plans.metrics import compute_metrics
from querycure.plans.parser import parse_plan
from querycure.sql.fingerprint import match_key

BACKEND = Path(__file__).parents[3]
RUN = uuid.UUID("00000000-0000-4000-8000-000000000002")
PK_SQL = "SELECT value FROM app_settings WHERE key = 'feature_17'"


def plan(name: str, **edits: float) -> list[Evidence]:
    raw = json.loads((BACKEND / "evals" / "fixtures" / "plans" / name).read_text())
    for key, value in edits.items():
        raw[0][key] = value
    tree = parse_plan(raw)
    return plan_evidence(RUN, "b" * 64, tree, compute_metrics(tree), provenance="imported")


def pk_plan(**edits: float) -> list[Evidence]:
    return plan("pg17_no_benefit_pk_lookup_analyze.json", **edits)


def ev(kind: str, locator: str, data: dict[str, JsonScalar]) -> Evidence:
    return Evidence(
        id=evidence_id(RUN, kind, "c" * 64, locator),
        kind=kind,  # type: ignore[arg-type]
        artifact_sha256="c" * 64,
        locator=locator,
        summary=f"{kind} {locator}",
        data=data,
        provenance="measured",
    )


def statement(i: int, query: str, calls: int, total_ms: float) -> Evidence:
    return ev(
        "workload_stat",
        f"/statement_stats/{i}",
        {"queryid": i, "calls": calls, "total_exec_time_ms": total_ms, "query": query},
    )


def test_tiny_fast_lookup_is_not_worth_optimizing() -> None:
    evidence = pk_plan()

    m = assess_materiality(evidence)

    assert m.verdict == "not_material"
    assert (m.execution_time_ms, m.planning_time_ms, m.rows_examined) == (0.039, 0.358, 50)
    summary, scan = evidence[0], evidence[1]
    assert {summary.id, scan.id} <= set(m.evidence_ids)
    assert any("50 rows" in r for r in m.reasons)
    assert any("planning" in r for r in m.reasons)


def test_large_scan_is_material() -> None:
    m = assess_materiality(plan("pg17_canonical_hot_analyze.json"))

    assert m.verdict == "material"
    assert (m.rows_examined or 0) > 100 * SMALL_WORK_ROWS


def test_plain_explain_has_no_measured_latency_so_the_gate_stays_out() -> None:
    m = assess_materiality(plan("pg17_canonical_plain.json"))

    assert m.verdict == "undetermined"
    assert m.execution_time_ms is None


def test_same_tiny_plan_is_undetermined_when_execution_outweighs_planning() -> None:
    # Not a latency cutoff: a 0.5 ms run over 50 rows is still sub-millisecond, but execution
    # now dominates fixed overhead (cold cache?), so the gate does not call it immaterial.
    m = assess_materiality(pk_plan(**{"Execution Time": 0.5}))

    assert m.verdict == "undetermined"


def test_tiny_scan_of_a_large_table_is_not_dismissed() -> None:
    # The plan saw 50 rows, but the catalog says the scanned table is large: a Seq Scan's
    # cost grows with the table, so this is not "too small to matter".
    big = ev("table_stat", "/tables/0", {"table": "app_settings", "estimated_rows": 2_000_000})

    m = assess_materiality([*pk_plan(), big])

    assert m.verdict == "undetermined"
    assert m.largest_seq_scanned_rows == 2_000_000


def test_frequent_query_is_material_even_when_each_call_is_fast() -> None:
    evidence = [
        *pk_plan(),
        statement(0, "SELECT value FROM app_settings WHERE key = $1", 9_000_000, 400_000.0),
        statement(1, "SELECT * FROM orders WHERE id = $1", 10_000, 600_000.0),
    ]

    m = assess_materiality(evidence, query_key=match_key(PK_SQL))

    assert m.verdict == "material"
    assert m.workload_calls == 9_000_000
    assert m.workload_time_share == pytest.approx(0.4)
    assert evidence[-2].id in m.evidence_ids


def test_rare_tiny_query_stays_immaterial_and_cites_the_workload() -> None:
    evidence = [
        *pk_plan(),
        statement(0, "SELECT value FROM app_settings WHERE key = $1", 12, 0.6),
        statement(1, "SELECT * FROM orders WHERE customer_id = $1", 50_000, 900_000.0),
    ]

    m = assess_materiality(evidence, query_key=match_key(PK_SQL))

    assert m.verdict == "not_material"
    assert m.workload_calls == 12
    assert evidence[-2].id in m.evidence_ids


def test_unmatched_workload_statements_are_ignored() -> None:
    evidence = [*pk_plan(), statement(0, "SELECT 1", 9_000_000, 900_000.0)]

    assert assess_materiality(evidence, query_key=match_key(PK_SQL)).verdict == "not_material"


def test_match_key_treats_literals_and_parameters_alike() -> None:
    assert match_key(PK_SQL) == match_key("select value from app_settings where key = $1")
    assert match_key("not sql at all (") is None


def hypothesis(confidence: str = "high") -> Hypothesis:
    return Hypothesis(
        key="hy_000000000001",
        rank=1,
        statement="Add an index on app_settings(key).",
        category="missing_index",
        supporting_evidence=["ev_000000000001"],
        confidence=confidence,  # type: ignore[arg-type]
        uncertainty_notes="Seq Scan filters rows.",
        verification_method="benchmark",
        proposed_by=["index_strategist"],
    )


def test_gate_caps_confidence_and_explains_why_when_not_material() -> None:
    m = assess_materiality(pk_plan())

    [gated] = gate_hypotheses([hypothesis("high")], m)

    assert gated.confidence == "low"
    assert gated.uncertainty_notes.startswith("Seq Scan filters rows. Not worth optimizing")
    assert "capped from high" in gated.uncertainty_notes
    assert set(m.evidence_ids) <= set(gated.contradicting_evidence)
    assert (gated.key, gated.category, gated.rank) == ("hy_000000000001", "missing_index", 1)


@pytest.mark.parametrize("name", ["pg17_canonical_hot_analyze.json", "pg17_canonical_plain.json"])
def test_gate_leaves_material_or_unknown_cases_alone(name: str) -> None:
    h = hypothesis("high")

    assert gate_hypotheses([h], assess_materiality(plan(name))) == [h]


def test_gate_is_deterministic() -> None:
    a = gate_hypotheses([hypothesis()], assess_materiality(pk_plan()))
    b = gate_hypotheses([hypothesis()], assess_materiality(pk_plan()))

    assert a == b
