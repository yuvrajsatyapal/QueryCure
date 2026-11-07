"""Prepare the Online Retail II CSV from the official XLSX (stdlib only, streaming).

    python -m querycure.workloads.retail_prep SOURCE.xlsx OUT.csv

The dataset is not in this repository (UCI, CC BY 4.0; BENCHMARK_ENGINE §11). This tool turns the
official download into the exact CSV that `online_retail_ii@v1` pins by SHA-256, so the file can be
reproduced and checked instead of trusted.

Every source row is kept as published. Added columns are provenance only: `line_id` (1-based,
sheet order then row order), `source_sheet`, `source_row` (the Excel row number). Nothing is
deduplicated, repaired or imputed. In the CSV an unquoted empty field is NULL (the cell is absent)
and a quoted `""` is an empty string, which is what `COPY … CSV` reads back.

Conversions that need care:

- Prices are stored in Excel as IEEE doubles, so `2.55` appears as `2.5499999999999998`. The
  output is the shortest decimal that round-trips the stored double (`2.55`); it is checked to
  round-trip, never rounded.
- `InvoiceDate` is an Excel serial number. It becomes a naive `YYYY-MM-DD HH:MM:SS`: the source has
  no time zone and none is invented.
- `Customer ID` is stored as `13085.0`; it must be a whole number and becomes `13085`.

Input is a local file chosen by the operator, parsed with the standard library's XML reader. Do not
point it at an untrusted file.
"""

import argparse
import csv
import hashlib
import json
import math
import sys
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import iterparse

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
EXCEL_EPOCH = datetime(1899, 12, 30)
SHEETS = ((1, "xl/worksheets/sheet1.xml"), (2, "xl/worksheets/sheet2.xml"))
SOURCE_COLUMNS = {
    "A": "invoice",
    "B": "stock_code",
    "C": "description",
    "D": "quantity",
    "E": "invoice_date",
    "F": "price",
    "G": "customer_id",
    "H": "country",
}
EXPECTED_HEADER = [
    "Invoice",
    "StockCode",
    "Description",
    "Quantity",
    "InvoiceDate",
    "Price",
    "Customer ID",
    "Country",
]
CSV_HEADER = [
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
]
REQUIRED = ("invoice", "stock_code", "quantity", "invoice_date", "price", "country")
MAX_PART_BYTES = 4 * 1024**3  # a worksheet or the string table larger than this is not this file
HASH_CHUNK = 1024 * 1024


class PrepError(ValueError):
    """The source file is not the Online Retail II workbook this tool understands."""


@dataclass
class SheetStats:
    dimension: str = ""
    data_rows: int = 0
    invoice_dates_not_whole_minute: int = 0


@dataclass
class PrepStats:
    rows: int = 0
    sum_quantity: Decimal = Decimal(0)
    sum_quantity_times_price: Decimal = Decimal(0)
    null_customers: int = 0
    null_descriptions: int = 0
    sheets: dict[int, SheetStats] = field(default_factory=dict)
    csv_sha256: str = ""
    csv_bytes: int = 0

    def as_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["sum_quantity"] = str(self.sum_quantity)
        data["sum_quantity_times_price"] = format(self.sum_quantity_times_price, "f")
        return data


def serial_to_iso(text: str) -> tuple[str, bool]:
    """Excel serial → ('YYYY-MM-DD HH:MM:SS', whether it was not a whole minute)."""
    seconds = int((Decimal(text) * 86400).to_integral_value())  # nearest second
    moment = EXCEL_EPOCH + timedelta(seconds=seconds)
    return moment.strftime("%Y-%m-%d %H:%M:%S"), moment.second != 0


def price_text(text: str) -> str:
    """Shortest decimal that round-trips the stored double (2.5499999999999998 → 2.55)."""
    stored = float(text)
    if not math.isfinite(stored):
        raise PrepError(f"price is not a finite number: {text}")
    shortest = Decimal(repr(stored))
    if float(shortest) != stored:
        raise PrepError(f"price does not round-trip: {text}")
    return format(shortest, "f")


def int_text(text: str) -> str:
    value = Decimal(text)
    if value != value.to_integral_value():
        raise PrepError(f"non-integer where an integer is expected: {text}")
    return str(int(value))


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    strings: list[str] = []
    with archive.open("xl/sharedStrings.xml") as part:
        for _, element in iterparse(part, events=("end",)):  # noqa: S314 (trusted local file, see module docstring)
            if element.tag == NS + "si":
                strings.append("".join(t.text or "" for t in element.iter(NS + "t")))
                element.clear()
    return strings


def _check_sizes(archive: zipfile.ZipFile) -> None:
    names = ["xl/sharedStrings.xml", *(part for _, part in SHEETS)]
    for name in names:
        try:
            info = archive.getinfo(name)
        except KeyError:
            raise PrepError(f"not an Online Retail II workbook: missing {name}") from None
        if info.file_size > MAX_PART_BYTES:
            raise PrepError(f"{name} is larger than {MAX_PART_BYTES} bytes")


def _cell_value(element: Any, strings: list[str]) -> str | None:
    kind = element.get("t")
    if kind == "inlineStr":
        return "".join(t.text or "" for t in element.iter(NS + "t"))
    value = element.find(NS + "v")
    if value is None or value.text is None:
        return None
    if kind == "s":
        return strings[int(value.text)]
    return str(value.text)


def _convert_row(
    cells: dict[str, str | None], kinds: dict[str, str], sheet: int, row_no: int
) -> tuple[list[str | None], Decimal, Decimal, bool]:
    unknown = set(cells) - set(SOURCE_COLUMNS)
    if unknown:
        raise PrepError(f"unexpected columns {sorted(unknown)} at sheet {sheet} row {row_no}")
    r = {name: cells.get(col) for col, name in SOURCE_COLUMNS.items()}
    kind = {name: kinds.get(col) for col, name in SOURCE_COLUMNS.items()}
    missing = [name for name in REQUIRED if r[name] is None]
    if missing:
        raise PrepError(f"missing required cell {missing} at sheet {sheet} row {row_no}")

    def required(name: str) -> str:
        value = r[name]
        if value is None:  # unreachable after the check above; keeps the type honest
            raise PrepError(f"missing required cell {name} at sheet {sheet} row {row_no}")
        return value

    invoice, stock = required("invoice"), required("stock_code")
    invoice_no = invoice if kind["invoice"] == "s" else int_text(invoice)
    stock_code = stock if kind["stock_code"] == "s" else int_text(stock)
    qty = int_text(required("quantity"))
    iso, not_whole_minute = serial_to_iso(required("invoice_date"))
    customer = None if r["customer_id"] is None else int_text(str(r["customer_id"]))
    unit_price = price_text(required("price"))
    out: list[str | None] = [
        None,  # line_id, set by the caller
        None,  # source_sheet
        None,  # source_row
        invoice_no,
        stock_code,
        r["description"],
        qty,
        iso,
        unit_price,
        customer,
        required("country"),
    ]
    return out, Decimal(qty), Decimal(unit_price), not_whole_minute


def prepare(xlsx: Path, out_csv: Path) -> PrepStats:
    """Convert the workbook to the pinned CSV layout and return what was written."""
    stats = PrepStats()
    with zipfile.ZipFile(xlsx) as archive, out_csv.open("w", newline="", encoding="utf-8") as fh:
        _check_sizes(archive)
        strings = _shared_strings(archive)
        writer = csv.writer(fh, quoting=csv.QUOTE_NOTNULL, lineterminator="\n")
        writer.writerow(CSV_HEADER)
        for sheet_no, part in SHEETS:
            _convert_sheet(archive, part, sheet_no, strings, writer, stats)
    digest = hashlib.sha256()
    with out_csv.open("rb") as written:
        while chunk := written.read(HASH_CHUNK):
            digest.update(chunk)
            stats.csv_bytes += len(chunk)
    stats.csv_sha256 = digest.hexdigest()
    return stats


def _convert_sheet(
    archive: zipfile.ZipFile,
    part: str,
    sheet_no: int,
    strings: list[str],
    writer: Any,
    stats: PrepStats,
) -> None:
    sheet = stats.sheets.setdefault(sheet_no, SheetStats())
    cells: dict[str, str | None] = {}
    kinds: dict[str, str] = {}
    with archive.open(part) as handle:
        for _, element in iterparse(handle, events=("end",)):  # noqa: S314 (trusted local file, see module docstring)
            if element.tag == NS + "dimension":
                sheet.dimension = element.get("ref", "")
            elif element.tag == NS + "c":
                column = "".join(ch for ch in element.get("r", "") if ch.isalpha())
                cells[column] = _cell_value(element, strings)
                kinds.setdefault(column, element.get("t") or "n")
                element.clear()
            elif element.tag == NS + "row":
                row_no = int(element.get("r", "0"))
                if row_no == 1:
                    header = [cells.get(c) for c in "ABCDEFGH"]
                    if header != EXPECTED_HEADER:
                        raise PrepError(f"unexpected header in sheet {sheet_no}: {header}")
                else:
                    out, qty, price, not_whole = _convert_row(cells, kinds, sheet_no, row_no)
                    stats.rows += 1
                    sheet.data_rows += 1
                    sheet.invoice_dates_not_whole_minute += int(not_whole)
                    stats.sum_quantity += qty
                    stats.sum_quantity_times_price += qty * price
                    stats.null_customers += int(out[9] is None)
                    stats.null_descriptions += int(out[5] is None)
                    out[0], out[1], out[2] = str(stats.rows), str(sheet_no), str(row_no)
                    writer.writerow(out)
                cells, kinds = {}, {}
                element.clear()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("xlsx", type=Path, help="online_retail_II.xlsx from the official download")
    parser.add_argument("out_csv", type=Path, help="CSV to write (outside the repository)")
    args = parser.parse_args(argv)
    if args.out_csv.exists():
        print(f"refusing to overwrite {args.out_csv}", file=sys.stderr)
        return 2
    stats = prepare(args.xlsx, args.out_csv)
    print(json.dumps(stats.as_json(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
