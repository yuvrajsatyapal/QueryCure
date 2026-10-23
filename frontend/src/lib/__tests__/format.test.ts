import { expect, test } from "vitest";
import { formatCost, formatMs, formatNs, formatRows, formatSpeedup } from "../format";

test("missing values read as an em dash, never as zero", () => {
  for (const f of [formatCost, formatMs, formatNs, formatRows, formatSpeedup]) {
    expect(f(null)).toBe("—");
    expect(f(undefined)).toBe("—");
  }
  expect(formatNs(Number.NaN)).toBe("—");
  expect(formatSpeedup(Number.POSITIVE_INFINITY)).toBe("—");
});

test("formatNs converts nanoseconds to the millisecond display", () => {
  expect(formatNs(228_999.5)).toBe("0.23 ms");
  expect(formatNs(4_400_000)).toBe("4.40 ms");
  expect(formatNs(12_340_000)).toBe("12.3 ms");
  expect(formatNs(1_250_000_000)).toBe("1250 ms");
});

test("formatSpeedup keeps two decimals below 10×, one above", () => {
  expect(formatSpeedup(1.5850702367128586)).toBe("1.59×");
  expect(formatSpeedup(1)).toBe("1.00×");
  expect(formatSpeedup(13.84)).toBe("13.8×");
});

test("formatCost uses PostgreSQL's two decimals and thousands separators", () => {
  expect(formatCost(0)).toBe("0.00");
  expect(formatCost(18334.5)).toBe("18,334.50");
});
