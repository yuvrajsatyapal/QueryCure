import { describe, expect, test } from "vitest";
import { describeCandidate } from "../candidate";

const index = (...ddl: string[]) => describeCandidate({ kind: "create_index", ddl, querySql: null });

describe("describeCandidate", () => {
  test("single and composite btree indexes", () => {
    expect(index("CREATE INDEX ON orders (customer_id)")).toBe("Index on orders (customer_id)");
    expect(index("CREATE INDEX ON orders (customer_id, created_at)")).toBe("Composite index on orders (customer_id, created_at)");
    expect(index("create index if not exists ix_o on public.orders using btree (customer_id desc, created_at)")).toBe(
      "Composite index on orders (customer_id desc, created_at)",
    );
  });

  test("method, INCLUDE and WHERE are named, not dropped", () => {
    expect(index("CREATE INDEX ON orders USING hash (status)")).toBe("Index on orders (status) · hash");
    expect(index("CREATE INDEX ON orders (customer_id) INCLUDE (total, status)")).toBe("Index on orders (customer_id) · includes total, status");
    expect(index("CREATE INDEX ON orders (created_at) WHERE status = 'open'")).toBe("Index on orders (created_at) · partial");
  });

  test("expression elements keep their text, quoted identifiers lose the quotes", () => {
    expect(index('CREATE INDEX ON "Orders" (lower(email))')).toBe("Index on Orders (lower(email))");
  });

  test("extended statistics and ANALYZE", () => {
    expect(describeCandidate({ kind: "extended_statistics", ddl: ["CREATE STATISTICS s1 (dependencies, mcv) ON city, zip FROM customers"], querySql: null })).toBe(
      "Extended statistics on customers (city, zip) · dependencies, mcv",
    );
    expect(describeCandidate({ kind: "extended_statistics", ddl: ["CREATE STATISTICS ON a, b FROM public.t"], querySql: null })).toBe(
      "Extended statistics on t (a, b)",
    );
    expect(describeCandidate({ kind: "analyze_statistics", ddl: ["ANALYZE orders"], querySql: null })).toBe("Refresh planner statistics on orders");
    expect(describeCandidate({ kind: "analyze_statistics", ddl: ["ANALYZE public.orders (customer_id)"], querySql: null })).toBe(
      "Refresh planner statistics on orders (customer_id)",
    );
  });

  test("several statements are joined, a rewrite is named as such", () => {
    expect(describeCandidate({ kind: "create_index", ddl: ["CREATE INDEX ON orders (customer_id)", "ANALYZE orders"], querySql: null })).toBe(
      "Index on orders (customer_id) + Refresh planner statistics on orders",
    );
    expect(describeCandidate({ kind: "query_rewrite", ddl: [], querySql: "SELECT 1" })).toBe("Query rewrite");
  });

  test("unparseable text falls back to the generic kind label instead of guessing", () => {
    expect(index("CREATE UNIQUE INDEX ON orders (id)")).toBe("Index candidate");
    expect(describeCandidate({ kind: "create_index", ddl: [], querySql: null })).toBe("Index candidate");
    expect(describeCandidate({ kind: "something_new", ddl: ["DROP TABLE x"], querySql: null })).toBe("something new");
  });
});
