import { describe, expect, test } from "vitest";
import { suggestTitle } from "../title";

describe("suggestTitle", () => {
  test("filter, sort and limit on one table", () => {
    expect(suggestTitle("SELECT * FROM orders WHERE customer_id = 1024 ORDER BY created_at DESC LIMIT 20")).toBe(
      "orders · where customer_id · order by created_at · limit 20",
    );
  });

  test("joins list every table once, in order, without schema or quotes", () => {
    expect(
      suggestTitle(
        'SELECT o.id FROM public.orders o JOIN "customers" c ON c.id = o.customer_id LEFT JOIN orders o2 ON o2.id = o.id WHERE c.region = $1',
      ),
    ).toBe("orders + customers · where region");
  });

  test("more than three tables are summarised", () => {
    expect(suggestTitle("select 1 from a join b on true join c on true join d on true join e on true")).toBe("a + b + c +2");
  });

  test("CTE names are not tables", () => {
    expect(
      suggestTitle("WITH recent AS (SELECT * FROM orders WHERE created_at > now() - interval '1 day') SELECT count(*) FROM recent"),
    ).toBe("orders · where created_at · aggregate");
  });

  test("group by wins over the generic aggregate label", () => {
    expect(suggestTitle("SELECT status, count(*) FROM orders GROUP BY status")).toBe("orders · group by status");
  });

  test("comments and string literals cannot inject words", () => {
    expect(
      suggestTitle("-- FROM secrets\nSELECT * /* JOIN hidden */ FROM orders WHERE note = 'from users where x = 1' AND id = 2"),
    ).toBe("orders · where note, id");
  });

  test("at most two filter columns, and qualified names keep the column", () => {
    expect(suggestTitle("SELECT * FROM t WHERE t.a = 1 AND t.b > 2 AND t.c < 3")).toBe("t · where a, b");
  });

  test("subqueries in FROM are skipped, inner tables still count", () => {
    expect(suggestTitle("SELECT * FROM (SELECT * FROM events) e WHERE e.kind = 'x'")).toBe("events · where kind");
  });

  test("blank or unreadable SQL gives no suggestion", () => {
    expect(suggestTitle("")).toBeNull();
    expect(suggestTitle("   -- only a comment")).toBeNull();
    expect(suggestTitle("SELECT 1")).toBeNull();
  });

  test("the same SQL always gives the same title and it is capped", () => {
    const long = `SELECT * FROM ${"x".repeat(300)} WHERE a = 1`;
    const title = suggestTitle(long);
    expect(title).toBe(suggestTitle(long));
    expect(title?.length).toBeLessThanOrEqual(120);
    expect(title?.endsWith("…")).toBe(true);
  });
});
