# Landing page prototype

Approved by the owner on 2026-11-01. `index.html` is a standalone page (inline CSS and JS, Google Fonts only); open it directly or serve the folder. It is the visual reference for the production landing page in `frontend/src/app/page.tsx`. It is not shipped.

## Hero: Query X-Ray

One query, `SELECT * FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 20`, shown as its plan before and after `CREATE INDEX ON orders (customer_id, created_at DESC)`:

- **Before:** Limit → Sort (top-N heapsort) → Seq Scan on orders (2,000,000 rows examined, 47 kept).
- **After:** Limit → Index Scan using `orders_customer_id_created_at_idx` (20 rows examined); Sort and Seq Scan removed.

## Two sources of numbers, kept apart

| Source | Before | After | Speed-up | Where it appears |
|---|---|---|---|---|
| Illustrative benchmark (seeded PRNG in the page, shared with the benchmark section) | 12.50 ms median | 3.95 ms median | 3.17× | X-Ray result, labelled illustrative and from a separate example |
| Real PostgreSQL check (`xray_pg_check.py`) | 84.4 ms median | 0.006 ms median | ≈ 14,000× | This README and `xray_pg_result.json` only |

The 3.17× is **not** a measurement of the X-Ray plan. It comes from the page's illustrative benchmark, which models a typical verified index improvement. The owner chose to keep it (2026-11-01) on the condition that it is labelled as a separate illustrative example and never presented as the measured result of the X-Ray plan.

## Real PostgreSQL check

`xray_pg_check.py` rebuilds the X-Ray scenario on PostgreSQL 17 (local sandbox) in temporary tables inside one transaction that is rolled back: 2,000,000 orders, ≈ 47 per customer, the query above, then the index. Results are in `xray_pg_result.json`:

- Plan shapes match the X-Ray exactly: Before is Limit 20 → Sort (top-N heapsort, 20) → Seq Scan (47 rows, 1,999,953 removed by filter); After is Limit 20 → Index Scan with actual rows 20 and no Sort. The index name matches.
- Server-side `Execution Time` (EXPLAIN ANALYZE, timing off, 30 runs each): median 84.4 ms before, 0.006 ms after. Client wall-clock would add network and fetch time to both and compress the ratio; it was not measured.

This supports the X-Ray's annotation ("the scan stops after 20"). It does not support 3.17× for this plan, which is why the two are kept apart. A single, internally consistent example would need a different, reproducible scenario that genuinely measures about 3×; timings must not be tuned to fit the design.

Re-run (needs `docker compose -f infra/docker/compose.yaml up -d sandbox-db sandbox-relay`):

```bash
cd backend && uv run python -I ../docs/design/prototypes/landing/xray_pg_check.py
```
