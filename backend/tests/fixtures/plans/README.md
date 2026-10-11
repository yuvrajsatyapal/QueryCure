# Plan fixtures

`synthetic_*.json` files are **hand-written** in PostgreSQL's `EXPLAIN (FORMAT JSON)` shape with round
numbers, so expected metrics can be computed by hand in the tests. They are not measurements of any
database and must never be presented as such.

`pg17_*.json` files are **real captures**, frozen as test inputs:

| File | Statement |
|---|---|
| `pg17_canonical_hot_analyze.json` | `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT * FROM orders WHERE customer_id = 1024 ORDER BY created_at DESC LIMIT 20` |
| `pg17_canonical_plain.json` | the same query, plain `EXPLAIN (FORMAT JSON)` |
| `pg17_join_aggregate_analyze.json` | `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT c.region, count(*) FROM customers c JOIN orders o ON o.customer_id = c.id WHERE c.id < 500 GROUP BY c.region` |

Provenance: PostgreSQL 17.11 (Docker `postgres:17`, aarch64, default settings) on the
`orders_ecommerce@v1:sf=1:seed=42` workload, captured 2026-10-11 on a developer laptop.
Timings describe that machine on that day only. They are parser fixtures, never benchmark results.
