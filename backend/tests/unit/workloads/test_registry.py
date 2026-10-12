import pytest

from querycure.core.errors import ValidationFailedError
from querycure.workloads.registry import WORKLOADS, WorkloadRef, build_statements


def test_workload_ref_round_trip() -> None:
    ref = WorkloadRef.parse("orders_ecommerce@v1:sf=0.1:seed=42")

    assert (ref.name, ref.version, ref.scale_factor, ref.seed) == ("orders_ecommerce", 1, 0.1, 42)
    assert str(ref) == "orders_ecommerce@v1:sf=0.1:seed=42"


@pytest.mark.parametrize(
    "bad",
    [
        "orders_ecommerce",
        "orders_ecommerce@v9:sf=1:seed=42",
        "nope@v1:sf=1:seed=42",
        "orders_ecommerce@v1:sf=0:seed=42",
        "orders_ecommerce@v1:sf=11:seed=42",
        "orders_ecommerce@v1:sf=1:seed=-1",
        "orders_ecommerce@v1:sf=1;DROP:seed=1",
    ],
)
def test_invalid_refs_are_rejected(bad: str) -> None:
    with pytest.raises(ValidationFailedError):
        WorkloadRef.parse(bad)


def test_phase1_workloads_are_registered() -> None:
    assert {"orders_ecommerce", "rewrite_trap", "no_benefit"} <= set(WORKLOADS)


def sql_text(ref: WorkloadRef) -> str:
    return "\n".join(s.as_string(None) for s in build_statements(ref))


def test_generated_sql_is_deterministic_and_seeded() -> None:
    a = sql_text(WorkloadRef.parse("orders_ecommerce@v1:sf=0.1:seed=42"))
    b = sql_text(WorkloadRef.parse("orders_ecommerce@v1:sf=0.1:seed=42"))
    c = sql_text(WorkloadRef.parse("orders_ecommerce@v1:sf=0.1:seed=7"))

    assert a == b
    assert a != c


def test_generated_sql_uses_no_nondeterministic_functions() -> None:
    for name, spec in WORKLOADS.items():
        sql = sql_text(WorkloadRef(name=name, version=spec.version, scale_factor=1, seed=1))
        for forbidden in ("random(", "now(", "clock_timestamp", "hashtext", "gen_random_uuid"):
            assert forbidden not in sql.lower(), (name, forbidden)


def test_every_example_query_passes_the_validator() -> None:
    from querycure.sql.validator import validate_select

    for spec in WORKLOADS.values():
        for query in spec.example_queries:
            validate_select(query.sql)


def test_phase3_workloads_are_registered() -> None:
    assert {"join_fanout", "stale_stats", "index_regression"} <= set(WORKLOADS)
