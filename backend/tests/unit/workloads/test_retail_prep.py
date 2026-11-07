"""The Online Retail II preparation tool (Part B, M3), on a small synthetic workbook.

No real data is used or needed: the workbook is built in memory with the same layout as the UCI
download (two sheets, shared strings, the eight source columns).
"""

import hashlib
import zipfile
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from querycure.workloads import retail_prep
from querycure.workloads.registry import WORKLOADS
from querycure.workloads.retail_prep import PrepError, int_text, price_text, serial_to_iso

HEADER = [
    "Invoice",
    "StockCode",
    "Description",
    "Quantity",
    "InvoiceDate",
    "Price",
    "Customer ID",
    "Country",
]
COLUMNS = "ABCDEFGH"
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

# A cell is ("s", text) for a shared string, ("n", raw) for a numeric cell, or None for no cell.
Cell = tuple[str, str] | None
Row = Sequence[Cell]


def s(text: str) -> Cell:
    return ("s", text)


def n(raw: str) -> Cell:
    return ("n", raw)


HEADER_ROW: Row = [s(h) for h in HEADER]
# 2009-12-01 07:45:00 is serial 40148.322916666664 in the real file.
D1 = "40148.322916666664"


BASE: dict[str, Cell] = {
    "invoice": s("489434"),
    "stock": s("79323P"),
    "description": s("PINK CHERRY LIGHTS"),
    "quantity": n("12"),
    "when": n(D1),
    "price": n("6.75"),
    "customer": n("13085.0"),
    "country": s("United Kingdom"),
}


def line(**overrides: Cell) -> Row:
    """A valid published line; an override of None removes that cell (a NULL)."""
    unknown = set(overrides) - set(BASE)
    if unknown:
        raise KeyError(unknown)
    return list({**BASE, **overrides}.values())


def build_xlsx(path: Path, sheet1: Sequence[Row], sheet2: Sequence[Row]) -> Path:
    strings: list[str] = []

    def string_index(text: str) -> int:
        if text not in strings:
            strings.append(text)
        return strings.index(text)

    def sheet_xml(rows: Sequence[Row]) -> str:
        body = []
        for number, row in enumerate(rows, start=1):
            cells = []
            for column, cell in zip(COLUMNS, row, strict=True):
                if cell is None:
                    continue
                kind, value = cell
                if kind == "s":
                    cells.append(f'<c r="{column}{number}" t="s"><v>{string_index(value)}</v></c>')
                else:
                    cells.append(f'<c r="{column}{number}"><v>{value}</v></c>')
            body.append(f'<row r="{number}">{"".join(cells)}</row>')
        dimension = f"A1:H{len(rows)}"
        return (
            f'<worksheet xmlns="{NS}"><dimension ref="{dimension}"/>'
            f"<sheetData>{''.join(body)}</sheetData></worksheet>"
        )

    parts = {
        "xl/worksheets/sheet1.xml": sheet_xml(sheet1),
        "xl/worksheets/sheet2.xml": sheet_xml(sheet2),
    }
    shared = "".join(f"<si><t>{escape(t)}</t></si>" for t in strings)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("xl/sharedStrings.xml", f'<sst xmlns="{NS}">{shared}</sst>')
        for name, xml in parts.items():
            archive.writestr(name, xml)
    return path


def prepare(
    tmp_path: Path, sheet1: Sequence[Row], sheet2: Sequence[Row]
) -> tuple[str, retail_prep.PrepStats]:
    xlsx = build_xlsx(tmp_path / "in.xlsx", sheet1, sheet2)
    out = tmp_path / "out.csv"
    stats = retail_prep.prepare(xlsx, out)
    return out.read_text(encoding="utf-8"), stats


def test_rows_are_converted_as_published_with_provenance_columns(tmp_path: Path) -> None:
    text, stats = prepare(
        tmp_path,
        [HEADER_ROW, line(), line(invoice=n("489435"), stock=n("85048"), quantity=n("-3"))],
        [HEADER_ROW, line(invoice=s("C537434"), customer=None, price=n("0.001"))],
    )

    assert text.splitlines() == [
        '"line_id","source_sheet","source_row","invoice_no","stock_code","description",'
        '"quantity","invoice_date","unit_price","customer_id","country"',
        '"1","1","2","489434","79323P","PINK CHERRY LIGHTS","12","2009-12-01 07:45:00","6.75",'
        '"13085","United Kingdom"',
        '"2","1","3","489435","85048","PINK CHERRY LIGHTS","-3","2009-12-01 07:45:00","6.75",'
        '"13085","United Kingdom"',
        '"3","2","2","C537434","79323P","PINK CHERRY LIGHTS","12","2009-12-01 07:45:00","0.001",,'
        '"United Kingdom"',
    ]
    assert stats.rows == 3


def test_float_noise_prices_become_the_shortest_round_tripping_decimal() -> None:
    cases = {
        "2.5499999999999998": "2.55",
        "0.10000000000000001": "0.1",
        "-53594.360000000001": "-53594.36",
        "38970": "38970.0",  # the shortest repr of the double keeps ".0"; numeric parses it
        "0": "0.0",
        "6.75": "6.75",
        "1E-3": "0.001",
    }
    for stored, expected in cases.items():
        assert price_text(stored) == expected, stored


def test_the_true_three_decimal_price_is_kept_exactly() -> None:
    # 18 rows of the real file carry 0.001; numeric(12,3) holds it, numeric(10,2) would not.
    assert price_text("0.001") == "0.001"
    assert price_text("0.0010000000000000000") == "0.001"
    assert price_text("1.001") == "1.001"


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf"])
def test_a_price_that_is_not_a_finite_double_is_refused(bad: str) -> None:
    with pytest.raises(PrepError):
        price_text(bad)


def test_integers_must_be_whole_numbers() -> None:
    assert int_text("13085.0") == "13085"
    assert int_text("-80995") == "-80995"
    with pytest.raises(PrepError):
        int_text("1.5")


def test_dates_are_naive_timestamps_and_odd_seconds_are_counted() -> None:
    assert serial_to_iso("40148.322916666664") == ("2009-12-01 07:45:00", False)
    assert serial_to_iso("40513.5") == ("2010-12-01 12:00:00", False)
    iso, odd = serial_to_iso("40148.322928240736")  # one second later
    assert (iso, odd) == ("2009-12-01 07:45:01", True)


def test_null_and_empty_string_are_different_in_the_csv(tmp_path: Path) -> None:
    text, stats = prepare(
        tmp_path,
        [
            HEADER_ROW,
            line(description=None, customer=None),
            line(description=s("")),
        ],
        [HEADER_ROW],
    )

    rows = text.splitlines()[1:]
    # Unquoted empty is NULL; a quoted "" is an empty string (COPY ... CSV reads them that way).
    assert rows[0] == (
        '"1","1","2","489434","79323P",,"12","2009-12-01 07:45:00","6.75",,"United Kingdom"'
    )
    assert rows[1] == (
        '"2","1","3","489434","79323P","","12","2009-12-01 07:45:00","6.75","13085",'
        '"United Kingdom"'
    )
    assert (stats.null_descriptions, stats.null_customers) == (1, 1)


def test_line_ids_run_across_sheets_and_source_rows_are_excel_rows(tmp_path: Path) -> None:
    text, _ = prepare(
        tmp_path,
        [HEADER_ROW, line(), line()],
        [HEADER_ROW, line(), line()],
    )

    ids = [row.replace('"', "").split(",")[:3] for row in text.splitlines()[1:]]
    assert ids == [["1", "1", "2"], ["2", "1", "3"], ["3", "2", "2"], ["4", "2", "3"]]


def test_statistics_match_an_independent_recount(tmp_path: Path) -> None:
    sheet1 = [
        HEADER_ROW,
        line(quantity=n("12"), price=n("6.75")),
        line(quantity=n("-2"), price=n("2.5499999999999998"), customer=None),
    ]
    sheet2 = [HEADER_ROW, line(quantity=n("5"), price=n("0.001"), description=None)]
    out = tmp_path / "out.csv"

    stats = retail_prep.prepare(build_xlsx(tmp_path / "in.xlsx", sheet1, sheet2), out)

    assert stats.rows == 3
    assert stats.sum_quantity == Decimal(15)
    assert stats.sum_quantity_times_price == Decimal("12") * Decimal("6.75") - Decimal(
        "2"
    ) * Decimal("2.55") + Decimal("5") * Decimal("0.001")
    assert (stats.null_customers, stats.null_descriptions) == (1, 1)
    assert stats.sheets[1].dimension == "A1:H3"
    assert stats.sheets[1].data_rows == 2
    assert stats.sheets[2].data_rows == 1
    raw = out.read_bytes()
    assert stats.csv_sha256 == hashlib.sha256(raw).hexdigest()
    assert stats.csv_bytes == len(raw)


def test_the_same_workbook_always_gives_the_same_bytes(tmp_path: Path) -> None:
    rows = [HEADER_ROW, line(), line(customer=None)]
    xlsx = build_xlsx(tmp_path / "in.xlsx", rows, [HEADER_ROW])
    first, second = tmp_path / "a.csv", tmp_path / "b.csv"

    a = retail_prep.prepare(xlsx, first)
    b = retail_prep.prepare(xlsx, second)

    assert first.read_bytes() == second.read_bytes()
    assert a.csv_sha256 == b.csv_sha256


def test_the_csv_layout_is_the_one_the_registry_loads() -> None:
    fixed = WORKLOADS["online_retail_ii"].fixed
    assert fixed is not None

    assert fixed.columns == retail_prep.CSV_HEADER


def test_a_changed_header_is_refused(tmp_path: Path) -> None:
    wrong = [s("InvoiceNo"), *HEADER_ROW[1:]]
    with pytest.raises(PrepError, match="unexpected header"):
        prepare(tmp_path, [wrong, line()], [HEADER_ROW])


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ({"quantity": None}, "missing required cell"),
        ({"country": None}, "missing required cell"),
        ({"quantity": n("1.5")}, "non-integer"),
        ({"price": n("nan")}, "not a finite number"),
        ({"customer": n("12.5")}, "non-integer"),
    ],
)
def test_a_row_that_is_not_the_published_shape_is_refused(
    tmp_path: Path, field: dict[str, Cell], message: str
) -> None:
    with pytest.raises(PrepError, match=message):
        prepare(tmp_path, [HEADER_ROW, line(**field)], [HEADER_ROW])


def test_an_extra_column_is_refused(tmp_path: Path) -> None:
    xlsx = build_xlsx(tmp_path / "in.xlsx", [HEADER_ROW], [HEADER_ROW])
    with zipfile.ZipFile(xlsx) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    contents["xl/worksheets/sheet1.xml"] = contents["xl/worksheets/sheet1.xml"].replace(
        b"</sheetData>",
        b'<row r="2"><c r="I2"><v>1</v></c></row></sheetData>',
    )
    with zipfile.ZipFile(tmp_path / "extra.xlsx", "w") as archive:
        for name, data in contents.items():
            archive.writestr(name, data)

    with pytest.raises(PrepError, match="unexpected columns"):
        retail_prep.prepare(tmp_path / "extra.xlsx", tmp_path / "out.csv")


def test_a_workbook_without_the_second_sheet_is_refused(tmp_path: Path) -> None:
    with zipfile.ZipFile(tmp_path / "short.xlsx", "w") as archive:
        archive.writestr("xl/sharedStrings.xml", f'<sst xmlns="{NS}"></sst>')
        archive.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{NS}"/>')

    with pytest.raises(PrepError, match=r"missing xl/worksheets/sheet2\.xml"):
        retail_prep.prepare(tmp_path / "short.xlsx", tmp_path / "out.csv")


def test_the_command_refuses_to_overwrite_an_existing_file(tmp_path: Path) -> None:
    xlsx = build_xlsx(tmp_path / "in.xlsx", [HEADER_ROW, line()], [HEADER_ROW])
    existing = tmp_path / "out.csv"
    existing.write_text("keep me")

    code = retail_prep.main([str(xlsx), str(existing)])

    assert code == 2
    assert existing.read_text() == "keep me"


def test_the_command_writes_the_csv_and_prints_the_statistics(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    xlsx = build_xlsx(tmp_path / "in.xlsx", [HEADER_ROW, line()], [HEADER_ROW])
    out = tmp_path / "out.csv"

    code = retail_prep.main([str(xlsx), str(out)])

    assert code == 0
    printed = capsys.readouterr().out
    assert f'"csv_sha256": "{hashlib.sha256(out.read_bytes()).hexdigest()}"' in printed
    assert '"rows": 1' in printed
