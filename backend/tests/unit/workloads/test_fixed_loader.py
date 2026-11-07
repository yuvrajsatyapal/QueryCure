"""The fixed-dataset loader (Part B, M4), against a fake connection.

Refusals must happen before ANY database call: `ExplodingConn` fails the test on first touch, so
"no write" is proven by the absence of every call, not by inspecting an empty database. The
database-backed twins live in tests/security/test_fixed_dataset_loader.py.
"""

import hashlib
import os
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from psycopg import sql

from querycure.workloads.loader import (
    DDL,
    FixedDatasetError,
    load_fixed_dataset,
    verified_source,
)
from querycure.workloads.registry import (
    FixedDataset,
    Reconciliation,
    WorkloadRef,
)

CSV = (
    b'"line_id","source_sheet","source_row","invoice_no","stock_code","description","quantity",'
    b'"invoice_date","unit_price","customer_id","country"\n'
    b'"1","1","2","489434","79323P","PINK CHERRY LIGHTS","12","2009-12-01 07:45:00","6.75",'
    b'"13085","United Kingdom"\n'
    b'"2","1","3","489435","85048",,"-3","2009-12-01 07:46:00","0.001",,"United Kingdom"\n'
)
GOOD_ROW = (2, 9, Decimal("71.998"), 1, 1)  # rows, sum(qty), sum(qty*price), null cust, null desc


def small_dataset(content: bytes = CSV) -> FixedDataset:
    return FixedDataset(
        csv_sha256=hashlib.sha256(content).hexdigest(),
        csv_bytes=len(content),
        folder="online-retail-ii",
        filename="online_retail_ii.csv",
        table="retail_lines",
        columns=[
            "line_id",
            "source_sheet",
            "source_row",
            "invoice_no",
            "stock_code",
            "description",
            "quantity",
            "invoice_date",
            "unit_price",
            "customer_id",
            "country",
        ],
        reconciliation=Reconciliation(
            rows=2,
            sum_quantity=9,
            sum_quantity_times_price="71.998",
            null_customers=1,
            null_descriptions=1,
        ),
        source_url="https://example.invalid/data",
        licence="test",
        citation="test",
    )


def ref_for(dataset: FixedDataset) -> WorkloadRef:
    return WorkloadRef(name="online_retail_ii", version=1, data_id=dataset.data_id)


class ExplodingConn:
    """Any use is a failure: a refused load must not reach the database at all."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the database was touched ({name}) before the file was verified")


class FakeCopy:
    def __init__(self, conn: "FakeConn") -> None:
        self.conn = conn

    def __enter__(self) -> "FakeCopy":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def write(self, data: bytes) -> None:
        self.conn.copied.append(bytes(data))


class FakeCursor:
    def __init__(self, conn: "FakeConn") -> None:
        self.conn = conn

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def copy(self, query: sql.Composable) -> FakeCopy:
        self.conn.log.append(("copy", query.as_string(None)))
        if self.conn.fail_copy:
            raise RuntimeError("COPY failed")
        return FakeCopy(self.conn)


class FakeResult:
    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self.row = row

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.row


class FakeConn:
    def __init__(
        self,
        reconciliation: tuple[Any, ...] = GOOD_ROW,
        on_begin: Callable[[], None] | None = None,
        fail_copy: bool = False,
    ) -> None:
        self.log: list[tuple[str, str]] = []
        self.copied: list[bytes] = []
        self.reconciliation = reconciliation
        self.on_begin = on_begin
        self.fail_copy = fail_copy

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.log.append(("begin", ""))
        if self.on_begin is not None:
            self.on_begin()
        try:
            yield
        except BaseException:
            self.log.append(("rollback", ""))
            raise
        self.log.append(("commit", ""))

    def execute(self, query: sql.Composable) -> FakeResult:
        text = query.as_string(None)
        self.log.append(("execute", text))
        return FakeResult(self.reconciliation if "count(*)" in text else None)

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def statements(self) -> list[str]:
        return [text for kind, text in self.log if kind in ("execute", "copy")]

    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.log]


@pytest.fixture
def data_file(tmp_path: Path) -> Path:
    path = tmp_path / "online_retail_ii.csv"
    path.write_bytes(CSV)
    return path


# --- refusals: nothing reaches the database ---------------------------------------------------


def refuse(path: Path, code: str, dataset: FixedDataset | None = None) -> None:
    dataset = dataset or small_dataset()
    with pytest.raises(FixedDatasetError) as raised:
        load_fixed_dataset(ExplodingConn(), ref_for(dataset), path, dataset=dataset)  # type: ignore[arg-type]
    assert raised.value.code == code


def test_a_missing_file_is_refused(tmp_path: Path) -> None:
    refuse(tmp_path / "absent.csv", "DATA_FILE_MISSING")


def test_a_symlink_is_refused_even_when_it_points_at_the_right_bytes(
    data_file: Path, tmp_path: Path
) -> None:
    link = tmp_path / "link.csv"
    link.symlink_to(data_file)

    refuse(link, "DATA_FILE_NOT_REGULAR")


def test_a_dangling_symlink_is_refused(tmp_path: Path) -> None:
    link = tmp_path / "dangling.csv"
    link.symlink_to(tmp_path / "nowhere.csv")

    refuse(link, "DATA_FILE_NOT_REGULAR")


def test_a_directory_is_refused(tmp_path: Path) -> None:
    refuse(tmp_path, "DATA_FILE_NOT_REGULAR")


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs named pipes")
def test_a_named_pipe_is_refused_without_blocking(tmp_path: Path) -> None:
    pipe = tmp_path / "pipe.csv"
    os.mkfifo(pipe)
    assert stat.S_ISFIFO(pipe.lstat().st_mode)

    refuse(pipe, "DATA_FILE_NOT_REGULAR")


def test_an_oversized_file_is_refused_before_it_is_read(data_file: Path) -> None:
    data_file.write_bytes(CSV + b"x")

    refuse(data_file, "DATA_FILE_SIZE")


def test_a_truncated_file_is_refused(data_file: Path) -> None:
    data_file.write_bytes(CSV[:-1])

    refuse(data_file, "DATA_FILE_SIZE")


def test_an_empty_file_is_refused(data_file: Path) -> None:
    data_file.write_bytes(b"")

    refuse(data_file, "DATA_FILE_SIZE")


def test_one_changed_byte_of_the_right_size_is_refused_by_the_digest(data_file: Path) -> None:
    changed = bytearray(CSV)
    changed[10] ^= 0x01
    data_file.write_bytes(bytes(changed))

    refuse(data_file, "DATA_FILE_HASH")


def test_a_ref_for_other_data_than_the_dataset_is_refused(data_file: Path) -> None:
    dataset = small_dataset()
    other = WorkloadRef(name="online_retail_ii", version=1, data_id="0" * 12)

    with pytest.raises(FixedDatasetError) as raised:
        load_fixed_dataset(ExplodingConn(), other, data_file, dataset=dataset)  # type: ignore[arg-type]
    assert raised.value.code == "DATA_ID_MISMATCH"


def test_a_generated_workload_has_no_file_to_load(data_file: Path) -> None:
    generated = WorkloadRef.parse("orders_ecommerce@v1:sf=0.1:seed=42")

    with pytest.raises(FixedDatasetError) as raised:
        load_fixed_dataset(ExplodingConn(), generated, data_file)  # type: ignore[arg-type]
    assert raised.value.code == "DATA_NOT_FIXED"


def test_the_error_names_the_problem_but_never_echoes_file_contents(data_file: Path) -> None:
    data_file.write_bytes(b"SECRET-CONTENT" * 3)
    dataset = small_dataset()

    with pytest.raises(FixedDatasetError) as raised:
        load_fixed_dataset(ExplodingConn(), ref_for(dataset), data_file, dataset=dataset)  # type: ignore[arg-type]
    assert "SECRET" not in str(raised.value)


# --- a verified file loads exactly as one transaction -------------------------------------------


def test_a_verified_file_is_copied_unchanged_inside_one_transaction(data_file: Path) -> None:
    dataset = small_dataset()
    conn = FakeConn()

    report = load_fixed_dataset(conn, ref_for(dataset), data_file, dataset=dataset)  # type: ignore[arg-type]

    assert b"".join(conn.copied) == CSV
    assert conn.kinds() == ["begin", "execute", "copy", "execute", "execute", "commit"]
    create, copy, analyze, reconcile = conn.statements()
    assert " ".join(create.split()).startswith("CREATE TABLE retail_lines ( line_id bigint")
    assert copy.startswith('COPY "retail_lines" ("line_id", "source_sheet"')
    assert copy.endswith("FROM STDIN WITH (FORMAT csv, HEADER true)")
    assert analyze == 'ANALYZE "retail_lines"'
    assert "count(*)" in reconcile
    assert report.rows == 2
    assert report.csv_sha256 == dataset.csv_sha256


def test_the_file_path_never_reaches_the_server(data_file: Path) -> None:
    dataset = small_dataset()
    conn = FakeConn()

    load_fixed_dataset(conn, ref_for(dataset), data_file, dataset=dataset)  # type: ignore[arg-type]

    assert all(str(data_file) not in text for text in conn.statements())
    assert all(data_file.name not in text for text in conn.statements())


def test_the_column_types_are_the_decided_ones() -> None:
    ddl = " ".join(DDL["retail_lines"].split())

    assert "unit_price numeric(12,3) NOT NULL" in ddl
    assert "invoice_date timestamp NOT NULL" in ddl
    assert "timestamptz" not in ddl
    assert "line_id bigint PRIMARY KEY" in ddl
    assert "customer_id integer," in ddl  # nullable
    assert "description text," in ddl  # nullable


def test_the_table_layout_matches_the_registry_columns() -> None:
    from querycure.workloads.registry import WORKLOADS

    fixed = WORKLOADS["online_retail_ii"].fixed
    assert fixed is not None
    declared = [
        part.split()[0]
        for part in " ".join(DDL["retail_lines"].split())
        .split("(", 1)[1]
        .rsplit(")", 1)[0]
        .split(", ")
        if part and not part.startswith("PRIMARY")
    ]
    assert declared == fixed.columns


# --- failures after verification roll everything back --------------------------------------------


def test_a_file_changed_after_verification_is_caught_and_rolled_back(data_file: Path) -> None:
    dataset = small_dataset()

    def swap_a_byte() -> None:
        changed = bytearray(CSV)
        changed[10] ^= 0x01
        with data_file.open("r+b") as handle:  # same inode, same size, different content
            handle.write(bytes(changed))

    conn = FakeConn(on_begin=swap_a_byte)

    with pytest.raises(FixedDatasetError) as raised:
        load_fixed_dataset(conn, ref_for(dataset), data_file, dataset=dataset)  # type: ignore[arg-type]

    assert raised.value.code == "DATA_FILE_HASH"
    assert "rollback" in conn.kinds()
    assert "commit" not in conn.kinds()


@pytest.mark.parametrize(
    "wrong",
    [
        (3, 9, Decimal("71.998"), 1, 1),
        (2, 10, Decimal("71.998"), 1, 1),
        (2, 9, Decimal("71.99"), 1, 1),
        (2, 9, Decimal("71.998"), 2, 1),
        (2, 9, Decimal("71.998"), 1, 0),
    ],
)
def test_any_reconciliation_difference_rolls_the_load_back(
    data_file: Path, wrong: tuple[Any, ...]
) -> None:
    dataset = small_dataset()
    conn = FakeConn(reconciliation=wrong)

    with pytest.raises(FixedDatasetError) as raised:
        load_fixed_dataset(conn, ref_for(dataset), data_file, dataset=dataset)  # type: ignore[arg-type]

    assert raised.value.code == "DATA_RECONCILIATION"
    assert "rollback" in conn.kinds()
    assert "commit" not in conn.kinds()


def test_the_reconciliation_message_lists_expected_and_actual_numbers(data_file: Path) -> None:
    dataset = small_dataset()
    conn = FakeConn(reconciliation=(3, 9, Decimal("71.998"), 1, 1))

    with pytest.raises(FixedDatasetError) as raised:
        load_fixed_dataset(conn, ref_for(dataset), data_file, dataset=dataset)  # type: ignore[arg-type]

    assert "rows: expected 2, got 3" in str(raised.value)


def test_a_database_error_during_copy_rolls_back_and_propagates(data_file: Path) -> None:
    dataset = small_dataset()
    conn = FakeConn(fail_copy=True)

    with pytest.raises(RuntimeError, match="COPY failed"):
        load_fixed_dataset(conn, ref_for(dataset), data_file, dataset=dataset)  # type: ignore[arg-type]

    assert "rollback" in conn.kinds()
    assert "commit" not in conn.kinds()


def test_verification_alone_does_not_need_a_database(data_file: Path) -> None:
    dataset = small_dataset()

    with verified_source(data_file, dataset) as handle:
        assert handle.read() == CSV


# --- where the file lives -----------------------------------------------------------------------


def test_the_default_location_is_under_the_users_home_and_not_a_fixed_machine_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from querycure.workloads.loader import default_csv_path

    monkeypatch.delenv("QC_DATASETS_DIR", raising=False)

    path = default_csv_path(small_dataset())

    assert (
        path == Path.home() / "Datasets" / "QueryCure" / "online-retail-ii" / "online_retail_ii.csv"
    )


def test_the_datasets_directory_is_configurable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from querycure.workloads.loader import default_csv_path

    monkeypatch.setenv("QC_DATASETS_DIR", str(tmp_path / "elsewhere"))

    assert default_csv_path(small_dataset()) == (
        tmp_path / "elsewhere" / "online-retail-ii" / "online_retail_ii.csv"
    )


def test_a_leading_tilde_in_the_configured_directory_is_expanded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from querycure.workloads.loader import default_csv_path

    monkeypatch.setenv("QC_DATASETS_DIR", "~/data")

    assert default_csv_path(small_dataset()) == (
        Path.home() / "data" / "online-retail-ii" / "online_retail_ii.csv"
    )
