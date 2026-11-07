# Landing page prototype

Approved by the owner on 2026-11-01. `index.html` is a standalone page (inline CSS and JS, Google Fonts only); open it directly or serve the folder. It is the visual reference for the production landing page in `frontend/src/app/page.tsx`. It is not shipped.

## Hero: Query X-Ray

One query, `SELECT * FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 20`, shown as its plan before and after `CREATE INDEX ON orders (customer_id, created_at DESC)`:

- **Before:** Limit → Sort (top-N heapsort) → Seq Scan on orders (2,000,000 rows examined, 47 kept).
- **After:** Limit → Index Scan using `orders_customer_id_created_at_idx` (20 rows examined); Sort and Seq Scan removed.

## Numbers (updated 2026-11-07)

The production X-Ray no longer uses the seeded illustrative benchmark. Its numbers all come from the real PostgreSQL check below (84.4 ms → 0.006 ms server-side, ≈14,064×), copied to `frontend/src/lib/landing/xray_pg_result.json` and read through `xrayMeasured.ts`. This closes the earlier open decision: the card no longer shows a plan it did not measure. The seeded 12.50 → 3.95 ms / 3.17× benchmark stays only in the benchmark section, labelled illustrative. The standalone `index.html` in this folder still shows the old illustrative result and is a historical design reference, not the shipped card.

Re-recording `xray_pg_result.json` here means copying it to the frontend path too; the unit test fails if the two differ.

## Real PostgreSQL check

`xray_pg_check.py` rebuilds the X-Ray scenario on PostgreSQL 17 (local sandbox) in temporary tables inside one transaction that is rolled back: 2,000,000 orders, ≈ 47 per customer, the query above, then the index. Results are in `xray_pg_result.json`:

- Plan shapes match the X-Ray exactly: Before is Limit 20 → Sort (top-N heapsort, 20) → Seq Scan (47 rows, 1,999,953 removed by filter); After is Limit 20 → Index Scan with actual rows 20 and no Sort. The index name matches.
- Server-side `Execution Time` (EXPLAIN ANALYZE, timing off, 30 runs each): median 84.4 ms before, 0.006 ms after. Client wall-clock would add network and fetch time to both and compress the ratio; it was not measured.

This supports the X-Ray's annotation ("the scan stops after 20"). It does not support 3.17× for this plan, which is why the two are kept apart. A single, internally consistent example would need a different, reproducible scenario that genuinely measures about 3×; timings must not be tuned to fit the design.

Re-run (needs `docker compose -f infra/docker/compose.yaml up -d sandbox-db sandbox-relay`):

```bash
cd backend && uv run python -I ../docs/design/prototypes/landing/xray_pg_check.py
```
