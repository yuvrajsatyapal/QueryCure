# Dataset: UCI Online Retail II (`online_retail_ii@v1`)

A fixed, real dataset for Mode C benchmarks, beside the generated workloads. Decision and rationale: [ADR-0033](../engineering/adr/ADR-0033-fixed-real-datasets-in-mode-c.md). How the reference and loader work: [BENCHMARK_ENGINE §11](../architecture/BENCHMARK_ENGINE.md#11-demo-workloads-ground-truth-fixtures).

**The data is not in this repository and must not be committed.** It is licensed CC BY 4.0, which allows redistribution with attribution, but a 133 MB file does not belong in Git and each machine should verify its own copy against the pin below.

## Source and licence
| | |
|---|---|
| Name | Online Retail II |
| Provider | UCI Machine Learning Repository |
| Page | https://archive.ics.uci.edu/dataset/502/online+retail+ii |
| DOI | https://doi.org/10.24432/C5CG6D |
| Licence | Creative Commons Attribution 4.0 International (CC BY 4.0) |
| Download | https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip (one entry, `online_retail_II.xlsx`) |

**Citation.** Chen, D. (2012). *Online Retail II* [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C5CG6D

A report or document that shows results from this data must carry this attribution and say that the data was converted (below).

## Checksums (trust on first use)
UCI publishes no checksums. These are the digests of the files downloaded on 2026-11-06 (zip 45,622,418 bytes; xlsx 45,622,278 bytes):

| File | SHA-256 |
|---|---|
| `online+retail+ii.zip` | `572e36277c2390fbfde10664750731e0a86f55e33470d91919085f0408e67bfb` |
| `online_retail_II.xlsx` | `bcbe73b35f5b7babf197fb0cb983a11f5d9ff929078d4aa53d171b1f2df2e980` |
| `online_retail_ii.csv` (prepared, 132,964,983 bytes) | `b3471c34b27325f6f68aa58184689a076669885e27d15ebde92dcb198efd9840` |

The 12-character reference identifier `b3471c34b273` is the first 12 hex digits of the **CSV** digest. The registry pins the full CSV digest and the size; the loader verifies both before any database write. The zip and xlsx digests are for your own check of the download. If a future download differs from these, treat it as a different dataset: do not edit the pin, add a new version.

## Getting and preparing the file
1. Download the zip from the page above and unzip `online_retail_II.xlsx`. Check its SHA-256 against the table.
2. Prepare the CSV (the tool refuses to overwrite an existing file):

   ```bash
   cd backend
   uv run python -m querycure.workloads.retail_prep /path/to/online_retail_II.xlsx \
     ~/Datasets/QueryCure/online-retail-ii/online_retail_ii.csv
   ```

   It prints the row count, sums and the CSV's SHA-256. The output must equal the pinned digest; the tool is deterministic. On 2026-11-06 it reproduced the pinned CSV byte for byte from the official xlsx.
3. The default location is `$QC_DATASETS_DIR` (default `~/Datasets/QueryCure`) `/online-retail-ii/online_retail_ii.csv`. Both the build command and the data-backed tests read it from there; `--csv` overrides it for the build command.
4. Build the sandbox template once (local sandbox only; it creates and drops databases):

   ```bash
   SANDBOX_BENCH_PASSWORD=... uv run python -m querycure.workloads build-template \
     --sandbox-url postgresql://qc_sandbox_admin:...@127.0.0.1:55432/sandbox_admin
   ```

The worker container never needs the file; it uses the finished template. A run that reaches Mode C without the template fails with `SANDBOX_UNAVAILABLE` and this command in the message.

## What was changed from the published file
Every row is kept as published. Nothing is deduplicated, repaired or imputed.

- Added: `line_id` (1…N, sheet then row order), `source_sheet`, `source_row` (the Excel row number). `line_id` makes `ORDER BY …, line_id` a total order, which the result-equivalence check needs.
- Renamed: UCI documents `InvoiceNo`, `UnitPrice`, `CustomerID`; the workbook headers are `Invoice`, `Price`, `Customer ID` and the table uses `invoice_no`, `unit_price`, `customer_id`.
- Converted: `InvoiceDate` from an Excel serial to a naive `YYYY-MM-DD HH:MM:SS` (all values are whole minutes); `Customer ID` from `13085.0` to `13085`; invoice and stock codes stored as numbers are written as integers; prices are stored as IEEE doubles in Excel, so `2.55` appears as `2.5499999999999998`, and the CSV holds the shortest decimal that round-trips the double (`2.55`), never a rounded value.
- In the CSV an unquoted empty field is NULL (the cell was absent) and a quoted `""` is an empty string.

## Table
`retail_lines`: `line_id bigint PRIMARY KEY`, `source_sheet smallint`, `source_row integer`, `invoice_no text`, `stock_code text`, `description text` (nullable), `quantity integer`, `invoice_date timestamp` (naive), `unit_price numeric(12,3)`, `customer_id integer` (nullable), `country text`. `numeric(12,3)` keeps the 18 prices that have three decimals; `timestamp` without time zone because the source has no zone.

## Reconciliation (pinned, checked on every load)
| Check | Value |
|---|---:|
| Rows (sheet 1: 525,461; sheet 2: 541,910) | 1,067,371 |
| Sum of `quantity` | 10,608,492 |
| Sum of `quantity × unit_price` | 19,287,250.568 |
| Rows with NULL `customer_id` | 243,007 |
| Rows with NULL `description` | 4,382 |

An independent recount of the workbook's XML (row elements, string references, non-empty cells) agreed with the converter and the profile. A load that differs in any of these is rolled back.

## Data-quality notes
From the profile of the prepared file. These are properties of the real data, not defects to fix, and reports that use it should not hide them.

- **Duplicates.** 34,335 extra copies of exact-duplicate lines (32,907 distinct duplicated lines). Not removed.
- **Missing customers.** 243,007 lines (22.77%) have no customer id; 750 of them are on cancellations. 5,942 distinct customer ids (12346 to 18287). Lines per customer: median 53, p90 323, p99 1,132, maximum 13,097 (customer 17841).
- **Cancellations and negatives.** 19,494 lines are on cancellation invoices (invoice numbers starting with `C`) and 6 on adjustment invoices (`A`). 22,950 lines have a negative quantity (quantity range −80,995 to 80,995); 5 lines have a negative price; 6,202 have a zero price. All 4,382 lines without a description have a zero price.
- **Non-product lines.** 63 irregular stock codes (for example `POST`, `DOT`, `M`) with 6,094 lines; some carry large prices (up to 38,970) that dominate sums.
- **Two sheets.** Invoices can span both sheets (1,088 do), and 2,813 customers appear in both. 83 invoices have more than one timestamp.
- **Time.** 604 days have lines; per-day median 1,566.5, maximum 7,756. Timestamps are naive wall-clock values as published: no zone is documented or assumed.
- **Skew.** Customer and invoice sizes are heavily skewed (median invoice 9 lines, maximum 1,350), which is why the registered parameter sets include the heaviest, a median, a single-line and a nonexistent customer.
- **Rows are in chronological order**, so `invoice_date` correlates strongly with physical position and a date index is unusually cheap on this data.

## Registered queries
`recent_lines_for_customer` (primary, newest 50 lines of one customer), `lines_of_invoice`, `customer_totals_in_window` (date windows of one day, one month and the full range). Each orders totally or aggregates. Their parameter sets use IDs taken from the profile: the heaviest customer 17841, a median customer 12413, a single-line customer 12382, a nonexistent id 18288; invoices 489450 (typical), 537434 (largest, 1,350 lines), C489449 (cancellation) and 999999 (missing).

## Status
Loader, template build and catalog are implemented and were checked against the local servers on 2026-11-06 (the template builds in seconds and reproduces every reconciliation value in a clone). No benchmark, eval case or recording exists for this dataset, so there is no expected verdict yet and no speed-up claim.
