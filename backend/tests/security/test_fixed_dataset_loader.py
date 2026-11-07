"""The fixed-dataset loader against a real PostgreSQL (Part B, M4/M8).

Needs only a plain PostgreSQL server (the compose `metadata-db` is enough; the sandbox is not):
each test loads into its own throwaway database. Proves on a real server what
tests/unit/workloads/test_fixed_loader.py proves with a fake connection: a refused file creates
nothing, and a failed load leaves nothing behind.

The tests marked `real data` need the actual CSV at `$QC_DATASETS_DIR/online-retail-ii/` (default
`~/Datasets/QueryCure/online-retail-ii/online_retail_ii.csv`) and are skipped, with the exact file
named, when it is absent. Nothing here downloads anything.
"""

import os
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest

from querycure.workloads.loader import (
    FixedDatasetError,
    default_csv_path,
    load_fixed_dataset,
)
from querycure.workloads.registry import WORKLOADS, WorkloadRef
from tests.integration.conftest import ADMIN_URL
from tests.integration.fixed_dataset_fixtures import CSV, HEADER, dataset, ref

pytestmark = pytest.mark.integration

Conn = psycopg.Connection[Any]


@pytest.fixture
def scratch() -> Iterator[Conn]:
    try:
        admin = psycopg.connect(ADMIN_URL, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        reason = f"metadata DB not reachable ({exc.__class__.__name__}); run docker compose up"
        if os.environ.get("QC_REQUIRE_DB") == "1":
            pytest.fail(reason)
        pytest.skip(reason)
    name = f"qc_test_{uuid.uuid4().hex[:12]}"
    base, _, _ = ADMIN_URL.rpartition("/")
    with admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    conn = psycopg.connect(f"{base}/{name}", autocommit=True)
    try:
        yield conn
    finally:
        conn.close()
        with psycopg.connect(ADMIN_URL, autocommit=True) as cleanup:
            cleanup.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def user_tables(conn: Conn) -> list[str]:
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    ).fetchall()
    return sorted(r[0] for r in rows)


@pytest.fixture
def data_file(tmp_path: Path) -> Path:
    path = tmp_path / "online_retail_ii.csv"
    path.write_bytes(CSV)
    return path


# --- refusals leave the database exactly as it was ----------------------------------------------


def test_a_missing_file_creates_nothing(scratch: Conn, tmp_path: Path) -> None:
    ds = dataset()
    with pytest.raises(FixedDatasetError, match="does not exist"):
        load_fixed_dataset(scratch, ref(ds), tmp_path / "absent.csv", dataset=ds)

    assert user_tables(scratch) == []


def test_a_symlink_creates_nothing(
    scratch: Conn,
    data_file: Path,
    tmp_path: Path,
) -> None:
    link = tmp_path / "link.csv"
    link.symlink_to(data_file)
    ds = dataset()

    with pytest.raises(FixedDatasetError, match="symbolic link"):
        load_fixed_dataset(scratch, ref(ds), link, dataset=ds)

    assert user_tables(scratch) == []


def test_an_oversized_file_creates_nothing(scratch: Conn, data_file: Path) -> None:
    ds = dataset()
    data_file.write_bytes(CSV + b"extra")

    with pytest.raises(FixedDatasetError, match="pinned dataset has"):
        load_fixed_dataset(scratch, ref(ds), data_file, dataset=ds)

    assert user_tables(scratch) == []


def test_a_hash_mismatch_creates_nothing(scratch: Conn, data_file: Path) -> None:
    ds = dataset()
    changed = bytearray(CSV)
    changed[40] ^= 0x01
    data_file.write_bytes(bytes(changed))

    with pytest.raises(FixedDatasetError, match="SHA-256"):
        load_fixed_dataset(scratch, ref(ds), data_file, dataset=ds)

    assert user_tables(scratch) == []


# --- a failed load rolls the table back too -------------------------------------------------------


def test_a_reconciliation_difference_leaves_no_table(scratch: Conn, data_file: Path) -> None:
    ds = dataset(sum_quantity=23)

    with pytest.raises(FixedDatasetError, match="sum_quantity: expected 23, got 22"):
        load_fixed_dataset(scratch, ref(ds), data_file, dataset=ds)

    assert user_tables(scratch) == []


def test_malformed_csv_with_the_right_digest_leaves_no_table(scratch: Conn, tmp_path: Path) -> None:
    bad = HEADER + b'"1","1","2","489434"\n'  # too few columns, but it is the pinned content
    path = tmp_path / "bad.csv"
    path.write_bytes(bad)
    ds = dataset(bad)

    with pytest.raises(psycopg.Error):
        load_fixed_dataset(scratch, ref(ds), path, dataset=ds)

    assert user_tables(scratch) == []


# --- a verified file loads as published ------------------------------------------


def test_the_table_has_the_decided_column_types(scratch: Conn, data_file: Path) -> None:
    ds = dataset()
    load_fixed_dataset(scratch, ref(ds), data_file, dataset=ds)

    types = {
        r[0]: (r[1], r[2], r[3])
        for r in scratch.execute(
            "SELECT column_name, data_type, numeric_precision, numeric_scale "
            "FROM information_schema.columns WHERE table_name = 'retail_lines'"
        )
    }
    assert types["unit_price"] == ("numeric", 12, 3)
    assert types["invoice_date"][0] == "timestamp without time zone"
    assert types["line_id"][0] == "bigint"
    assert types["source_sheet"][0] == "smallint"
    assert types["customer_id"][0] == "integer"


def test_rows_are_kept_exactly_as_published(scratch: Conn, data_file: Path) -> None:
    ds = dataset()
    report = load_fixed_dataset(scratch, ref(ds), data_file, dataset=ds)

    assert report.rows == 4
    rows = scratch.execute(
        "SELECT line_id, description, quantity, invoice_date, unit_price, customer_id "
        "FROM retail_lines ORDER BY line_id"
    ).fetchall()
    assert [r[0] for r in rows] == [1, 2, 3, 4]
    assert (
        rows[0][1:]
        == rows[1][1:]
        == (
            "15CM CHRISTMAS GLASS BALL 20 LIGHTS",
            12,
            rows[0][3],
            Decimal("6.950"),
            13085,
        )
    )  # the duplicate is kept
    assert rows[2][1] is None  # unquoted empty is NULL ...
    assert rows[3][1] == ""  # ... quoted "" is an empty string
    assert rows[2][2] == -3  # negative quantity kept
    assert rows[2][4] == Decimal("0.001")  # a three-decimal price is not rounded
    assert rows[2][5] is None  # NULL customer kept
    assert str(rows[0][3]) == "2009-12-01 07:45:00"  # naive timestamp, no zone invented
    assert rows[3][4] == Decimal("0.000")


def test_the_table_is_analyzed_and_has_only_the_primary_key(scratch: Conn, data_file: Path) -> None:
    ds = dataset()
    load_fixed_dataset(scratch, ref(ds), data_file, dataset=ds)

    statistics = scratch.execute(
        "SELECT count(*) FROM pg_stats WHERE schemaname = 'public' AND tablename = 'retail_lines'"
    ).fetchone()
    assert statistics is not None
    assert statistics[0] > 0
    indexes = scratch.execute(
        "SELECT indexname FROM pg_indexes WHERE tablename = 'retail_lines'"
    ).fetchall()
    assert [r[0] for r in indexes] == ["retail_lines_pkey"]


def test_a_second_load_into_the_same_database_fails_without_changing_it(
    scratch: Conn, data_file: Path
) -> None:
    ds = dataset()
    load_fixed_dataset(scratch, ref(ds), data_file, dataset=ds)

    with pytest.raises(psycopg.errors.DuplicateTable):
        load_fixed_dataset(scratch, ref(ds), data_file, dataset=ds)

    count = scratch.execute("SELECT count(*) FROM retail_lines").fetchone()
    assert count == (4,)


# --- the real file ---------------------------------------------------------------


def real_csv() -> Path:
    spec = WORKLOADS["online_retail_ii"].fixed
    assert spec is not None
    path = default_csv_path(spec)
    if not path.is_file():
        pytest.skip(
            f"real data: the pinned CSV is not at {path} (set QC_DATASETS_DIR). Prepare it with "
            "`python -m querycure.workloads.retail_prep online_retail_II.xlsx <that path>`; "
            f"expected SHA-256 {spec.csv_sha256}."
        )
    return path


def test_real_data_loads_and_reconciles_to_the_pinned_values(scratch: Conn) -> None:
    path = real_csv()
    live = WorkloadRef.parse("online_retail_ii@v1:data=b3471c34b273")

    report = load_fixed_dataset(scratch, live, path)  # reconciles inside, or raises

    assert report.rows == 1_067_371
    row = scratch.execute(
        "SELECT count(*), sum(quantity), sum(quantity * unit_price), "
        "count(*) FILTER (WHERE customer_id IS NULL), "
        "count(*) FILTER (WHERE description IS NULL), "
        "count(*) FILTER (WHERE unit_price = 0.001), "
        "count(*) FILTER (WHERE unit_price < 0), count(DISTINCT customer_id), "
        "min(invoice_date)::text, max(invoice_date)::text FROM retail_lines"
    ).fetchone()
    assert row == (
        1_067_371,
        10_608_492,
        Decimal("19287250.568"),
        243_007,
        4_382,
        18,
        5,
        5_942,
        "2009-12-01 07:45:00",
        "2011-12-09 12:50:00",
    )
