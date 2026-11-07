"""Fixed-dataset workloads (Part B, M2): the reference grammar, the registry entry and the
pinned reconciliation facts. Existing references are guarded by test_ref_compatibility.py."""

import pytest
from pydantic import ValidationError

from querycure.core.errors import ValidationFailedError
from querycure.sandbox.provisioner import template_name
from querycure.sql.validator import validate_select
from querycure.workloads.registry import WORKLOADS, WorkloadRef, build_statements

REF = "online_retail_ii@v1:data=b3471c34b273"
CSV_SHA256 = "b3471c34b27325f6f68aa58184689a076669885e27d15ebde92dcb198efd9840"


def test_fixed_ref_parses_and_renders_unchanged() -> None:
    ref = WorkloadRef.parse(REF)

    assert (ref.name, ref.version, ref.data_id) == ("online_retail_ii", 1, "b3471c34b273")
    assert ref.scale_factor is None
    assert ref.seed is None
    assert str(ref) == REF
    assert WorkloadRef.parse(str(ref)) == ref


def test_fixed_ref_has_its_own_stable_template_name() -> None:
    name = template_name(WorkloadRef.parse(REF))

    assert name == template_name(WorkloadRef.parse(REF))
    assert name.startswith("qc_tpl_")
    assert name != template_name(WorkloadRef.parse("orders_ecommerce@v1:sf=0.1:seed=42"))


@pytest.mark.parametrize(
    "bad",
    [
        "online_retail_ii@v1:data=000000000000",  # well-formed but not the pinned data
        "online_retail_ii@v1:data=B3471C34B273",  # ids are lowercase hex
        "online_retail_ii@v1:data=b3471c34b27",  # 11 digits
        "online_retail_ii@v1:data=b3471c34b2733",  # 13 digits
        "online_retail_ii@v1:data=b3471c34b273\n",  # no trailing newline
        " online_retail_ii@v1:data=b3471c34b273",
        "online_retail_ii@v1:data=b3471c34b273:seed=42",
        "online_retail_ii@v1:sf=1:seed=42:data=b3471c34b273",
        "online_retail_ii@v1:data=",
        "online_retail_ii@v1:data=b3471c34b27;",
        "online_retail_ii@v2:data=b3471c34b273",
        "orders_ecommerce@v1:data=b3471c34b273",  # a generated workload has no fixed data
        "online_retail_ii@v1:sf=1:seed=42",  # a fixed workload has no scale factor or seed
        "online_retail_ii@v1",
        "nope@v1:data=b3471c34b273",
    ],
)
def test_malformed_or_mismatched_fixed_refs_are_rejected(bad: str) -> None:
    with pytest.raises(ValidationFailedError):
        WorkloadRef.parse(bad)


@pytest.mark.parametrize(
    "fields",
    [
        {"data_id": "b3471c34b273", "scale_factor": 1.0, "seed": 1},
        {"data_id": "b3471c34b273", "scale_factor": 1.0},
        {"data_id": "b3471c34b273", "seed": 1},
        {},
        {"scale_factor": 1.0},
        {"seed": 1},
    ],
)
def test_a_ref_is_either_generated_or_fixed_never_both_or_neither(
    fields: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        WorkloadRef(name="x", version=1, **fields)  # type: ignore[arg-type]


def test_the_registry_pins_the_dataset_by_its_full_digest() -> None:
    spec = WORKLOADS["online_retail_ii"]
    assert spec.fixed is not None

    assert spec.fixed.csv_sha256 == CSV_SHA256
    assert spec.fixed.data_id == "b3471c34b273"
    assert CSV_SHA256.startswith(spec.fixed.data_id)
    assert spec.fixed.csv_bytes == 132_964_983
    assert spec.tables == ["retail_lines"]
    assert spec.version == 1


def test_the_registry_pins_the_reconciliation_values() -> None:
    fixed = WORKLOADS["online_retail_ii"].fixed
    assert fixed is not None

    assert fixed.reconciliation.rows == 1_067_371
    assert fixed.reconciliation.sum_quantity == 10_608_492
    assert fixed.reconciliation.sum_quantity_times_price == "19287250.568"
    assert fixed.reconciliation.null_customers == 243_007
    assert fixed.reconciliation.null_descriptions == 4_382


def test_generated_workloads_have_no_fixed_dataset() -> None:
    for name, spec in WORKLOADS.items():
        if name != "online_retail_ii":
            assert spec.fixed is None
            assert spec.build is not None


def test_a_fixed_dataset_is_loaded_from_a_file_not_generated() -> None:
    with pytest.raises(ValueError, match="loaded from a file"):
        build_statements(WorkloadRef.parse(REF))


def test_example_queries_are_valid_selects_with_matching_param_counts() -> None:
    spec = WORKLOADS["online_retail_ii"]

    assert [q.name for q in spec.example_queries] == [
        "recent_lines_for_customer",
        "lines_of_invoice",
        "customer_totals_in_window",
    ]
    for query in spec.example_queries:
        expected = validate_select(query.sql).metadata.parameter_count
        assert query.param_sets
        for param_set in query.param_sets:
            assert len(param_set.values) == expected, (query.name, param_set.name)


def test_every_example_query_orders_totally_so_results_can_be_compared() -> None:
    q1, q2, _ = WORKLOADS["online_retail_ii"].example_queries

    assert "line_id" in q1.sql.split("ORDER BY")[1]
    assert "line_id" in q2.sql.split("ORDER BY")[1]
