"""qc-row-v1 over the Online Retail II column types (Part B, M4/M8 prerequisite).

The hashes below were derived with an independent encoder written from the profile's table
(REPLAY_ENGINE §2.2), not by calling `row_hash`, so they fail if either the profile or the
column-kind mapping drifts. Rows are real lines of the published file, plus a NULL/negative line
and a zero-price/empty-description line shaped like the file's irregular rows.
"""

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest
from psycopg.postgres import types

from querycure.benchmark.correctness import kinds_for_oids
from querycure.replay.canonical.row_v1 import row_hash

# retail_lines column order: bigint, smallint, integer, text x3, integer, timestamp,
# numeric(12,3), integer, text
COLUMN_TYPES = [
    "int8",
    "int2",
    "int4",
    "text",
    "text",
    "text",
    "int4",
    "timestamp",
    "numeric",
    "int4",
    "text",
]

GOLDEN: dict[str, tuple[tuple[Any, ...], str]] = {
    "first_line": (
        (1, 1, 2, "489434", "85048", "15CM CHRISTMAS GLASS BALL 20 LIGHTS", 12,
         dt.datetime(2009, 12, 1, 7, 45), Decimal("6.950"), 13085, "United Kingdom"),
        "32d694fc830f6db91fdb391d3d3e600dfc07aa5fa7fa62821e388730c63d02cf",
    ),
    "null_description_null_customer_negative_and_three_decimals": (
        (2, 1, 3, "C489449", "79323P", None, -3,
         dt.datetime(2009, 12, 1, 7, 46), Decimal("0.001"), None, "EIRE"),
        "89a7e1f422d57a76f203e17164b829aa0c774bc9526962a3ad9708a9108d8dad",
    ),
    "zero_price_empty_description": (
        (3, 2, 2, "537434", "M", "", 80995,
         dt.datetime(2011, 12, 9, 12, 50), Decimal("0.000"), 12346, "United Kingdom"),
        "2f79c6927e2b23355ee9c712bfe2851404d555f977eb2a3f3d32899ec9d5bc55",
    ),
}  # fmt: skip


def kinds() -> list[str]:
    return kinds_for_oids(types[name].oid for name in COLUMN_TYPES)


def test_every_retail_column_type_is_a_typed_kind_not_other() -> None:
    assert kinds() == [
        "int",
        "int",
        "int",
        "text",
        "text",
        "text",
        "int",
        "timestamp",
        "numeric",
        "int",
        "text",
    ]


@pytest.mark.parametrize("name", list(GOLDEN))
def test_row_hashes_match_the_independently_derived_goldens(name: str) -> None:
    row, expected = GOLDEN[name]

    assert row_hash(kinds(), row).hex() == expected


def test_null_and_empty_string_hash_differently() -> None:
    base = list(GOLDEN["zero_price_empty_description"][0])
    with_null = base.copy()
    with_null[5] = None

    assert row_hash(kinds(), base) != row_hash(kinds(), with_null)


def test_numeric_scale_does_not_change_the_hash() -> None:
    # numeric(12,3) returns 6.950; the profile hashes the canonical decimal 6.95.
    row = list(GOLDEN["first_line"][0])
    other = row.copy()
    other[8] = Decimal("6.95")

    assert row_hash(kinds(), row) == row_hash(kinds(), other)
