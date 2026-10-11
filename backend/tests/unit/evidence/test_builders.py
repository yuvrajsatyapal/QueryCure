"""Deterministic evidence (T2.6): stable IDs, summaries from data, no LLM involved."""

import json
import uuid
from pathlib import Path

from querycure.connectors.models import ColumnStats, IndexInfo, SchemaSnapshot, TableStats
from querycure.evidence.builders import (
    context_summary,
    declared_schema_evidence,
    plan_evidence,
    query_evidence,
    schema_evidence,
)
from querycure.evidence.ids import evidence_id
from querycure.plans.metrics import compute_metrics
from querycure.plans.parser import parse_plan
from querycure.sql.ddl import parse_ddl
from querycure.sql.validator import validate_select

PLANS = Path(__file__).parents[2] / "fixtures" / "plans"
RUN = uuid.UUID("00000000-0000-4000-8000-000000000001")
SQL = "SELECT * FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 20"


def hot_plan_evidence() -> list:  # type: ignore[type-arg]
    tree = parse_plan(json.loads((PLANS / "pg17_canonical_hot_analyze.json").read_text()))
    return plan_evidence(RUN, "a" * 64, tree, compute_metrics(tree), provenance="imported")


def test_ids_are_deterministic_and_scoped_to_the_run() -> None:
    a = evidence_id(RUN, "plan_node", "a" * 64, "/0/Plan")
    b = evidence_id(RUN, "plan_node", "a" * 64, "/0/Plan")
    other_run = evidence_id(uuid.uuid4(), "plan_node", "a" * 64, "/0/Plan")
    other_locator = evidence_id(RUN, "plan_node", "a" * 64, "/0/Plan/Plans/0")

    assert a == b
    assert len({a, other_run, other_locator}) == 3
    assert a.startswith("ev_")
    assert len(a) == 15


def test_plan_evidence_has_a_summary_and_one_item_per_node() -> None:
    items = hot_plan_evidence()

    kinds = [e.kind for e in items]
    assert kinds.count("plan_summary") == 1
    assert kinds.count("plan_node") == 4
    assert len({e.id for e in items}) == len(items)


def test_hot_seq_scan_is_described_from_measured_numbers() -> None:
    scan = next(e for e in hot_plan_evidence() if e.data.get("node_type") == "Seq Scan")

    assert scan.data["relation"] == "orders"
    assert scan.data["hottest"] is True
    assert round(scan.data["self_time_ms"], 1) == 62.6  # type: ignore[arg-type]
    assert "Seq Scan on orders" in scan.summary
    assert "62.6 ms self (91.1% of runtime)" in scan.summary
    assert "hottest node" in scan.summary
    assert scan.locator.startswith("/0/Plan")
    assert scan.artifact_sha256 == "a" * 64
    assert scan.provenance == "imported"


def test_sort_node_reports_method_and_keys() -> None:
    sort = next(e for e in hot_plan_evidence() if e.data.get("node_type") == "Sort")

    assert "created_at" in str(sort.data["sort_key"])
    assert sort.data["sort_spilled"] is False
    assert "Sort" in sort.summary


def test_plain_explain_evidence_carries_estimates_only() -> None:
    tree = parse_plan(json.loads((PLANS / "pg17_canonical_plain.json").read_text()))

    items = plan_evidence(RUN, "b" * 64, tree, compute_metrics(tree), provenance="measured")

    summary = next(e for e in items if e.kind == "plan_summary")
    assert summary.data["analyzed"] is False
    assert "estimates only" in summary.summary
    nodes = [e for e in items if e.kind == "plan_node"]
    assert all(e.data.get("self_time_ms") is None for e in nodes)


def test_query_evidence_states_order_by_limit_and_predicates() -> None:
    validated = validate_select(SQL)

    items = query_evidence(RUN, "c" * 64, validated)

    by_locator = {e.locator: e for e in items}
    assert by_locator["#order_by"].data["value"] == "created_at DESC"
    assert by_locator["#limit"].data["value"] == 20
    assert "customer_id" in str(by_locator["#columns"].data["value"])
    assert by_locator["#tables"].data["value"] == "orders"
    assert all(e.kind == "query_fact" for e in items)


def test_schema_evidence_uses_numeric_statistics_only() -> None:
    snapshot = SchemaSnapshot(
        tables=[
            TableStats(
                schema_name="public",
                name="orders",
                kind="r",
                estimated_rows=1_000_000,
                pages=10_000,
                total_bytes=90_000_000,
                n_live_tup=1_000_000,
                n_dead_tup=0,
                n_mod_since_analyze=0,
                seq_scan=12,
                idx_scan=3,
                last_analyze=None,
                last_autoanalyze=None,
            )
        ],
        columns=[
            ColumnStats(
                schema_name="public",
                table_name="orders",
                name="customer_id",
                data_type="integer",
                not_null=True,
                position=2,
                null_frac=0.0,
                n_distinct=50_000.0,
                avg_width=4,
                correlation=0.01,
            )
        ],
        indexes=[
            IndexInfo(
                schema_name="public",
                table_name="orders",
                name="orders_pkey",
                definition="CREATE UNIQUE INDEX orders_pkey ON public.orders USING btree (id)",
                is_unique=True,
                is_primary=True,
                is_valid=True,
                size_bytes=22_000_000,
                idx_scan=3,
            )
        ],
        unresolved=[],
    )

    items = schema_evidence(RUN, "d" * 64, snapshot)

    kinds = {e.kind for e in items}
    assert kinds == {"table_stat", "column_stat", "index_def"}
    column = next(e for e in items if e.kind == "column_stat")
    assert column.data["n_distinct"] == 50_000.0
    index = next(e for e in items if e.kind == "index_def")
    assert "btree (id)" in index.summary
    assert all(e.provenance == "measured" for e in items)


def test_declared_schema_evidence_from_uploaded_ddl() -> None:
    declared = parse_ddl(
        "CREATE TABLE orders (id bigint PRIMARY KEY, customer_id int NOT NULL, "
        "created_at timestamptz NOT NULL);\n"
        "CREATE INDEX orders_customer_idx ON orders (customer_id);"
    )

    items = declared_schema_evidence(RUN, "e" * 64, declared)

    assert {e.kind for e in items} == {"schema_fact", "index_def"}
    index = next(e for e in items if e.kind == "index_def")
    assert index.data["columns"] == "customer_id"
    assert all(e.provenance == "imported" for e in items)


def test_context_summary_lists_every_cited_id_and_is_deterministic() -> None:
    items = hot_plan_evidence() + query_evidence(RUN, "c" * 64, validate_select(SQL))

    first = context_summary(items)
    second = context_summary(list(reversed(items)))

    assert first == second
    for e in items:
        assert e.id in first


def test_context_summary_is_bounded() -> None:
    items = hot_plan_evidence() * 200

    assert len(context_summary(items, max_chars=4000)) <= 4000


def test_long_values_never_break_the_summary_limit() -> None:
    tree = parse_plan(json.loads((PLANS / "pg17_join_aggregate_analyze.json").read_text()))

    for e in plan_evidence(RUN, "f" * 64, tree, compute_metrics(tree), provenance="imported"):
        assert len(e.summary) <= 300
