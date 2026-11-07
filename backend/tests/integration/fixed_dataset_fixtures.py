"""A tiny stand-in for the Online Retail II file, for tests of the loader and the template build.

Four lines shaped like the file's irregular rows: a duplicate pair, a NULL description with a NULL
customer, a negative quantity, a three-decimal price, an empty-string (not NULL) description and a
zero price. `dataset()` pins it the way the registry pins the real file, so the same code paths run.
"""

import hashlib

from querycure.workloads.registry import FixedDataset, Reconciliation, WorkloadRef

HEADER = (
    b'"line_id","source_sheet","source_row","invoice_no","stock_code","description","quantity",'
    b'"invoice_date","unit_price","customer_id","country"\n'
)
ROWS = (
    # a real line; a duplicate of it (kept); NULL description + NULL customer + negative quantity
    # + a three-decimal price; an empty-string (not NULL) description; a zero price.
    b'"1","1","2","489434","85048","15CM CHRISTMAS GLASS BALL 20 LIGHTS","12",'
    b'"2009-12-01 07:45:00",'
    b'"6.95","13085","United Kingdom"\n'
    b'"2","1","3","489434","85048","15CM CHRISTMAS GLASS BALL 20 LIGHTS","12",'
    b'"2009-12-01 07:45:00",'
    b'"6.95","13085","United Kingdom"\n'
    b'"3","1","4","C489449","79323P",,"-3","2009-12-01 07:46:00","0.001",,"EIRE"\n'
    b'"4","2","2","537434","M","","1","2011-12-09 12:50:00","0.0","12346","United Kingdom"\n'
)
CSV = HEADER + ROWS
COLUMNS = [
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


def dataset(content: bytes = CSV, **recon: object) -> FixedDataset:
    facts: dict[str, object] = {
        "rows": 4,
        "sum_quantity": 22,
        "sum_quantity_times_price": "166.797",  # 12*6.95 + 12*6.95 - 3*0.001 + 1*0
        "null_customers": 1,
        "null_descriptions": 1,
    }
    facts.update(recon)
    return FixedDataset(
        csv_sha256=hashlib.sha256(content).hexdigest(),
        csv_bytes=len(content),
        folder="online-retail-ii",
        filename="online_retail_ii.csv",
        table="retail_lines",
        columns=COLUMNS,
        reconciliation=Reconciliation.model_validate(facts),
        source_url="https://example.invalid/data",
        licence="test",
        citation="test",
    )


def ref(ds: FixedDataset) -> WorkloadRef:
    return WorkloadRef(name="online_retail_ii", version=1, data_id=ds.data_id)
