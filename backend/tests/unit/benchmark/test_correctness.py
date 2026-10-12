from decimal import Decimal

import pytest

from querycure.benchmark.correctness import (
    Fingerprinter,
    compare_results,
    kinds_for_oids,
    order_is_total,
)

KINDS = ["int", "text"]


def _fp(rows: list[tuple[object, ...]], cap: int = 100):  # type: ignore[no-untyped-def]
    f = Fingerprinter(KINDS, cap=cap)
    for row in rows:
        f.add(row)
    return f.result()


def test_multiset_ignores_order_but_ordered_does_not() -> None:
    a = _fp([(1, "x"), (2, "y")])
    b = _fp([(2, "y"), (1, "x")])

    assert a.rows == b.rows == 2
    assert a.multiset == b.multiset
    assert a.ordered != b.ordered


def test_duplicates_count_in_the_multiset() -> None:
    assert _fp([(1, "x"), (1, "x")]).multiset != _fp([(1, "x")]).multiset


def test_rows_beyond_the_cap_mark_truncation_but_are_counted() -> None:
    f = _fp([(i, "r") for i in range(5)], cap=3)

    assert (f.rows, f.truncated) == (5, True)


def test_identical_results_match() -> None:
    rows = [(1, "x"), (2, "y")]
    outcome = compare_results(_fp(rows), _fp(rows), has_order=False, has_limit=False, total=False)

    assert outcome.status == "match"


def test_different_rows_are_a_mismatch() -> None:
    outcome = compare_results(
        _fp([(1, "x")]), _fp([(1, "x"), (2, "y")]), has_order=False, has_limit=False, total=False
    )

    assert (outcome.status, outcome.reason) == ("mismatch", "result_mismatch")


def test_reordered_ties_without_total_order_still_match() -> None:
    outcome = compare_results(
        _fp([(1, "x"), (2, "x")]),
        _fp([(2, "x"), (1, "x")]),
        has_order=True,
        has_limit=False,
        total=False,
    )

    assert outcome.status == "match"


def test_reordering_under_a_total_order_is_a_mismatch() -> None:
    outcome = compare_results(
        _fp([(1, "x"), (2, "y")]),
        _fp([(2, "y"), (1, "x")]),
        has_order=True,
        has_limit=False,
        total=True,
    )

    assert (outcome.status, outcome.reason) == ("mismatch", "result_mismatch")


def test_limit_with_ties_and_different_rows_is_nondeterministic() -> None:
    outcome = compare_results(
        _fp([(1, "x")]), _fp([(2, "x")]), has_order=True, has_limit=True, total=False
    )

    assert (outcome.status, outcome.reason) == ("inconclusive", "nondeterministic_order")


def test_limit_with_total_order_and_different_rows_is_a_mismatch() -> None:
    outcome = compare_results(
        _fp([(1, "x")]), _fp([(2, "x")]), has_order=True, has_limit=True, total=True
    )

    assert outcome.status == "mismatch"


def test_truncated_results_are_inconclusive() -> None:
    big = _fp([(i, "r") for i in range(5)], cap=3)

    outcome = compare_results(big, big, has_order=False, has_limit=False, total=False)

    assert (outcome.status, outcome.reason) == ("inconclusive", "result_too_large")


UNIQUE = {"orders": [["id"]], "customers": [["id"], ["email"]]}


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("SELECT * FROM orders ORDER BY created_at DESC LIMIT 20", False),
        ("SELECT * FROM orders ORDER BY created_at DESC, id DESC LIMIT 20", True),
        ("SELECT * FROM orders o ORDER BY o.created_at, o.id", True),
        ("SELECT * FROM customers ORDER BY email", True),
        ("SELECT * FROM orders ORDER BY lower(status), id", True),
        ("SELECT * FROM orders ORDER BY lower(status)", False),
        ("SELECT * FROM orders JOIN customers c ON c.id = customer_id ORDER BY orders.id", False),
        ("SELECT * FROM orders", False),
        ("SELECT * FROM unknown ORDER BY id", False),
    ],
)
def test_order_totality_is_proved_conservatively(sql: str, expected: bool) -> None:
    assert order_is_total(sql, UNIQUE) is expected


def test_builtin_oids_map_to_row_kinds() -> None:
    assert kinds_for_oids([20, 25, 1700, 1184, 1007, 3802, 1186]) == [
        "int",
        "text",
        "numeric",
        "timestamptz",
        "int[]",
        "json",
        "other",
    ]


def test_numeric_values_hash_by_value_not_scale() -> None:
    f = Fingerprinter(["numeric"], cap=10)
    g = Fingerprinter(["numeric"], cap=10)
    f.add((Decimal("1.50"),))
    g.add((Decimal("1.5"),))

    assert f.result().multiset == g.result().multiset
