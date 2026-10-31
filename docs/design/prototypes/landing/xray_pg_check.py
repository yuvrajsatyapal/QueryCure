"""Checks the landing page's illustrative X-Ray scenario against a real PostgreSQL (local sandbox, temp tables, rolled back).

Scenario: orders with 2,000,000 rows, ~47 rows per customer; the query and index from the landing page.
Prints plan shapes (node types, actual rows, Sort present?) and median execution times before/after the index.
"""

import json
import statistics
import sys

import psycopg

DSN = "postgresql://qc_sandbox_admin:qc_local_dev_only@127.0.0.1:55432/sandbox_admin"
QUERY = "SELECT * FROM orders WHERE customer_id = %s ORDER BY created_at DESC LIMIT 20"
CUSTOMERS = 42553  # 2,000,000 / 42,553 ≈ 47 rows per customer
RUNS = 30


def walk(node: dict, depth: int = 0) -> list[dict]:
    out = [{
        "depth": depth,
        "node": node["Node Type"] + (f" using {node['Index Name']}" if "Index Name" in node else "") + (f" on {node['Relation Name']}" if "Relation Name" in node else ""),
        "actual_rows": node.get("Actual Rows"),
        "removed_by_filter": node.get("Rows Removed by Filter"),
        "sort_method": node.get("Sort Method"),
        "filter": node.get("Filter") or node.get("Index Cond"),
    }]
    for child in node.get("Plans", []):
        out += walk(child, depth + 1)
    return out


def measure(cur: psycopg.Cursor, cid: int) -> dict:
    cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + QUERY, (cid,))
    plan = cur.fetchone()[0][0]
    times = []
    for _ in range(RUNS):
        cur.execute("EXPLAIN (ANALYZE, TIMING OFF, FORMAT JSON) " + QUERY, (cid,))
        times.append(cur.fetchone()[0][0]["Execution Time"])
    return {"nodes": walk(plan["Plan"]), "median_exec_ms": round(statistics.median(times), 3), "min_ms": round(min(times), 3), "max_ms": round(max(times), 3)}


def main() -> None:
    with psycopg.connect(DSN, autocommit=False) as conn, conn.cursor() as cur:
        cur.execute("SELECT version()")
        version = cur.fetchone()[0]
        cur.execute("SET LOCAL statement_timeout = '300s'")
        cur.execute("""
            CREATE TEMP TABLE orders (
              id bigint PRIMARY KEY, customer_id int NOT NULL, status text NOT NULL,
              total numeric(10,2) NOT NULL, created_at timestamptz NOT NULL)
        """)
        cur.execute(f"""
            INSERT INTO orders
            SELECT g, (g % {CUSTOMERS}) + 1, (ARRAY['paid','shipped','refunded'])[1 + g % 3],
                   (g % 50000) / 100.0, timestamptz '2024-01-01' + (random() * interval '700 days')
            FROM generate_series(1, 2000000) g
        """)
        cur.execute("ANALYZE orders")
        cid = 1234
        cur.execute("SELECT count(*) FROM orders WHERE customer_id = %s", (cid,))
        matching = cur.fetchone()[0]
        before = measure(cur, cid)
        cur.execute("CREATE INDEX ON orders (customer_id, created_at DESC)")
        cur.execute("ANALYZE orders")
        cur.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'orders' AND indexname <> 'orders_pkey'")
        index_name = cur.fetchone()[0]
        after = measure(cur, cid)
        conn.rollback()
    result = {"postgres": version.split(",")[0], "rows": 2_000_000, "matching_rows_for_customer": matching,
              "index_name": index_name, "before": before, "after": after,
              "median_ratio": round(before["median_exec_ms"] / after["median_exec_ms"], 1)}
    json.dump(result, sys.stdout, indent=1)


if __name__ == "__main__":
    main()
