import errno
import hashlib
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, BinaryIO, Final, LiteralString

import psycopg
from psycopg import sql

from querycure.workloads.registry import WORKLOADS, FixedDataset, WorkloadRef, build_statements

CHUNK_BYTES: Final = 1024 * 1024
DATASETS_DIR_ENV: Final = "QC_DATASETS_DIR"
DEFAULT_DATASETS_DIR: Final = "~/Datasets/QueryCure"

# One CREATE TABLE per fixed dataset table. The layout is part of the pin: a change here is a
# different template (bump `FIXED_TEMPLATE_BUILDER` in sandbox/provisioner.py).
DDL: Final[dict[str, LiteralString]] = {
    "retail_lines": """
        CREATE TABLE retail_lines (
            line_id bigint PRIMARY KEY,
            source_sheet smallint NOT NULL,
            source_row integer NOT NULL,
            invoice_no text NOT NULL,
            stock_code text NOT NULL,
            description text,
            quantity integer NOT NULL,
            invoice_date timestamp NOT NULL,
            unit_price numeric(12,3) NOT NULL,
            customer_id integer,
            country text NOT NULL
        )
    """,
}


class FixedDatasetError(Exception):
    """A fixed dataset cannot be loaded. `code` is stable; the message never echoes file content."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class LoadReport:
    rows: int
    csv_sha256: str
    csv_bytes: int


def default_csv_path(dataset: FixedDataset) -> Path:
    """Where the operator keeps the file: `$QC_DATASETS_DIR` (default `~/Datasets/QueryCure`),
    then the dataset's folder and file name. Never inside the repository."""
    root = Path(os.environ.get(DATASETS_DIR_ENV) or DEFAULT_DATASETS_DIR).expanduser()
    return root / dataset.folder / dataset.filename


def load_workload(conn: psycopg.Connection[Any], ref: WorkloadRef) -> None:
    """Create and fill the workload's tables in one transaction on an empty database."""
    with conn.transaction():
        for statement in build_statements(ref):
            conn.execute(statement)  # composed with psycopg.sql: literals and identifiers only


@contextmanager
def verified_source(path: Path, dataset: FixedDataset) -> Iterator[BinaryIO]:
    """Open the data file only if it is the pinned one, and yield it rewound.

    Checked before the caller touches any database, on one file descriptor, so the bytes that were
    verified are the bytes that are read:
    the final path component must not be a symlink (`O_NOFOLLOW`); it must be a regular file (a
    named pipe is opened non-blocking and refused, never read); its size must equal the pinned
    size, so an oversized file is refused before it is read; and its SHA-256 must equal the pinned
    digest.
    """
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        raise FixedDatasetError(
            "DATA_FILE_MISSING", f"The data file does not exist: {path}"
        ) from None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise FixedDatasetError(
                "DATA_FILE_NOT_REGULAR", f"The data file is a symbolic link: {path}"
            ) from None
        raise FixedDatasetError(
            "DATA_FILE_UNREADABLE", f"The data file cannot be opened ({exc.strerror}): {path}"
        ) from None
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        os.close(fd)
        raise FixedDatasetError(
            "DATA_FILE_NOT_REGULAR", f"The data path is not a regular file: {path}"
        )
    with os.fdopen(fd, "rb") as handle:
        if info.st_size != dataset.csv_bytes:
            raise FixedDatasetError(
                "DATA_FILE_SIZE",
                f"The data file has {info.st_size} bytes; "
                f"the pinned dataset has {dataset.csv_bytes}.",
            )
        digest, size = hashlib.sha256(), 0
        while chunk := handle.read(CHUNK_BYTES):
            digest.update(chunk)
            size += len(chunk)
        if size != dataset.csv_bytes:
            raise FixedDatasetError("DATA_FILE_SIZE", "The data file changed while it was read.")
        if digest.hexdigest() != dataset.csv_sha256:
            raise FixedDatasetError(
                "DATA_FILE_HASH", "The data file's SHA-256 does not match the pinned dataset."
            )
        handle.seek(0)
        yield handle


def load_fixed_dataset(
    conn: psycopg.Connection[Any],
    ref: WorkloadRef,
    csv_path: Path,
    *,
    dataset: FixedDataset | None = None,
) -> LoadReport:
    """Create the table and fill it from the verified CSV, in one transaction.

    The file is verified in full before the first statement. It is then streamed through
    `COPY … FROM STDIN` (the path never reaches the server, so no server-file privilege is
    involved) and hashed again as it goes: a file changed after verification fails the load.
    After `ANALYZE` the loaded table must reproduce the pinned reconciliation values exactly;
    any difference rolls everything back. `dataset` is for tests; the default is the registry's.

    Rows are loaded as published, duplicates, NULLs and negatives included.
    """
    if dataset is None:
        spec = WORKLOADS.get(ref.name)
        dataset = spec.fixed if spec is not None else None
        if dataset is None:
            raise FixedDatasetError("DATA_NOT_FIXED", f"{ref.name} is not a fixed dataset.")
    if ref.data_id != dataset.data_id:
        raise FixedDatasetError("DATA_ID_MISMATCH", "The ref does not name this dataset's data.")
    ddl = DDL.get(dataset.table)
    if ddl is None:
        raise FixedDatasetError("DATA_NOT_FIXED", f"No table layout for {dataset.table}.")
    table = sql.Identifier(dataset.table)
    copy = sql.SQL("COPY {} ({}) FROM STDIN WITH (FORMAT csv, HEADER true)").format(
        table, sql.SQL(", ").join(sql.Identifier(c) for c in dataset.columns)
    )
    with verified_source(csv_path, dataset) as handle:
        digest = hashlib.sha256()
        with conn.transaction():
            conn.execute(sql.SQL(ddl))
            with conn.cursor() as cursor, cursor.copy(copy) as writer:
                while chunk := handle.read(CHUNK_BYTES):
                    digest.update(chunk)
                    writer.write(chunk)
            if digest.hexdigest() != dataset.csv_sha256:
                raise FixedDatasetError(
                    "DATA_FILE_HASH", "The data file changed after it was verified."
                )
            conn.execute(sql.SQL("ANALYZE {}").format(table))
            _reconcile(conn, dataset)
    return LoadReport(
        rows=dataset.reconciliation.rows, csv_sha256=dataset.csv_sha256, csv_bytes=dataset.csv_bytes
    )


def _reconcile(conn: psycopg.Connection[Any], dataset: FixedDataset) -> None:
    row = conn.execute(
        sql.SQL(
            "SELECT count(*), sum(quantity), sum(quantity * unit_price), "
            "count(*) FILTER (WHERE customer_id IS NULL), "
            "count(*) FILTER (WHERE description IS NULL) FROM {}"
        ).format(sql.Identifier(dataset.table))
    ).fetchone()
    want = dataset.reconciliation
    checks = [
        ("rows", want.rows, row[0] if row else None),
        ("sum_quantity", want.sum_quantity, row[1] if row else None),
        (
            "sum_quantity_times_price",
            Decimal(want.sum_quantity_times_price),
            Decimal(str(row[2])) if row and row[2] is not None else None,
        ),
        ("null_customers", want.null_customers, row[3] if row else None),
        ("null_descriptions", want.null_descriptions, row[4] if row else None),
    ]
    wrong = [
        f"{name}: expected {expected}, got {actual}"
        for name, expected, actual in checks
        if actual != expected
    ]
    if wrong:
        raise FixedDatasetError(
            "DATA_RECONCILIATION",
            "The loaded table does not match the pinned dataset (" + "; ".join(wrong) + ").",
        )


def table_checksums(conn: psycopg.Connection[Any], tables: list[str]) -> dict[str, str]:
    """md5 over each table's rows in a stable order: equal checksums ⇔ identical data."""
    result: dict[str, str] = {}
    for table in tables:
        row = conn.execute(
            sql.SQL(
                "SELECT md5(coalesce(string_agg(t::text, E'\\n' ORDER BY t::text), '')) FROM {} t"
            ).format(sql.Identifier(table))
        ).fetchone()
        result[table] = str(row[0]) if row else ""
    return result
