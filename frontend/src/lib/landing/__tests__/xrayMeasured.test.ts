import { describe, expect, test } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { MEASURED, formatMs, logRowsPct, formatMicros } from "../xrayMeasured";

const recorded = (rel: string) => readFileSync(resolve(process.cwd(), "..", rel), "utf8");

describe("measured X-Ray data", () => {
  test("is the recorded PostgreSQL run, byte for byte", () => {
    expect(readFileSync(resolve(__dirname, "../xray_pg_result.json"), "utf8")).toBe(recorded("docs/design/prototypes/landing/xray_pg_result.json"));
  });

  test("the run count is the one the check script uses", () => {
    const script = recorded("docs/design/prototypes/landing/xray_pg_check.py");
    expect(script).toMatch(new RegExp(`^RUNS = ${MEASURED.runs}\\b`, "m"));
  });

  test("reads the engine, table size and plan counts from the run", () => {
    expect(MEASURED.engine).toBe("PostgreSQL 17.11");
    expect(MEASURED.tableRows).toBe(2_000_000);
    expect(MEASURED.before.kept).toBe(47);
    expect(MEASURED.before.discarded).toBe(1_999_953);
    expect(MEASURED.before.examined).toBe(2_000_000);
    expect(MEASURED.before.sortIn).toBe(47);
    expect(MEASURED.after.rows).toBe(20);
    expect(MEASURED.limit).toBe(20);
  });

  test("rows examined by the Seq Scan add up to the whole table", () => {
    expect(MEASURED.before.examined).toBe(MEASURED.tableRows);
  });

  test("timings are the recorded medians and ranges", () => {
    expect(MEASURED.before.medianMs).toBe(84.386);
    expect([MEASURED.before.minMs, MEASURED.before.maxMs]).toEqual([76.399, 104.298]);
    expect(MEASURED.after.medianMs).toBe(0.006);
    expect([MEASURED.after.minMs, MEASURED.after.maxMs]).toEqual([0.006, 0.019]);
  });

  test("the ratio is computed from the medians, not typed in", () => {
    expect(MEASURED.ratio).toBeCloseTo(84.386 / 0.006, 6);
    expect(Math.round(MEASURED.ratio * 10) / 10).toBe(14064.3);
  });

  test("the After lane is a fraction of the Before lane on a linear scale", () => {
    expect(MEASURED.afterLane).toBeCloseTo(0.006 / 84.386, 9);
  });
});

describe("display helpers", () => {
  test("formatMs keeps tenths above 1 ms and microsecond precision below", () => {
    expect(formatMs(84.386)).toBe("84.4");
    expect(formatMs(0.006)).toBe("0.006");
    expect(formatMs(0)).toBe("0.000");
  });

  test("formatMicros shows sub-millisecond medians as whole microseconds", () => {
    expect(formatMicros(0.006)).toBe("6 µs");
  });

  test("logRowsPct places row counts on a log axis from 1 row to the whole table", () => {
    expect(logRowsPct(MEASURED.tableRows)).toBe(100);
    expect(logRowsPct(1)).toBe(0);
    expect(logRowsPct(20)).toBeCloseTo(20.6, 1);
    expect(logRowsPct(47)).toBeCloseTo(26.5, 1);
  });
});
