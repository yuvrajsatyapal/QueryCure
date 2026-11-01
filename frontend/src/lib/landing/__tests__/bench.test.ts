import { describe, expect, test } from "vitest";
import { ILLUSTRATIVE_BENCH, logPosition, makeIllustrativeBench, median, mulberry32, quantile } from "../bench";

describe("illustrative benchmark", () => {
  test("matches the approved prototype to the displayed precision", () => {
    const b = ILLUSTRATIVE_BENCH;
    expect(b.n).toBe(40);
    expect(b.baselineMedian.toFixed(2)).toBe("12.50");
    expect(b.candidateMedian.toFixed(2)).toBe("3.95");
    expect(b.ratio.toFixed(2)).toBe("3.17");
    expect(b.ciLow.toFixed(2)).toBe("2.60");
    expect(b.ciHigh.toFixed(2)).toBe("3.44");
  });

  test("is deterministic: same seeds, same samples", () => {
    const a = makeIllustrativeBench();
    const b = makeIllustrativeBench();
    expect(a.baseline).toEqual(b.baseline);
    expect(a.candidate).toEqual(b.candidate);
    expect(a.ciLow).toBe(b.ciLow);
  });

  test("ratio is the baseline median over the candidate median, inside its interval", () => {
    const b = ILLUSTRATIVE_BENCH;
    expect(b.ratio).toBeCloseTo(b.baselineMedian / b.candidateMedian, 10);
    expect(b.ciLow).toBeLessThan(b.ratio);
    expect(b.ciHigh).toBeGreaterThan(b.ratio);
  });
});

describe("statistics helpers", () => {
  test("median of odd and even lengths, input untouched", () => {
    const xs = [3, 1, 2];
    expect(median(xs)).toBe(2);
    expect(xs).toEqual([3, 1, 2]);
    expect(median([4, 1, 3, 2])).toBe(2.5);
  });

  test("quantile interpolates linearly between order statistics", () => {
    expect(quantile([1, 2, 3, 4, 5], 0.25)).toBe(2);
    expect(quantile([1, 2, 3, 4], 0.5)).toBe(2.5);
    expect(quantile([10, 20], 0.95)).toBeCloseTo(19.5, 10);
  });

  test("mulberry32 is seeded and stays in [0, 1)", () => {
    const r1 = mulberry32(42);
    const r2 = mulberry32(42);
    const draws = Array.from({ length: 1000 }, () => r1());
    expect(draws).toEqual(Array.from({ length: 1000 }, () => r2()));
    expect(draws.every((x) => x >= 0 && x < 1)).toBe(true);
  });

  test("logPosition maps a log-scale domain to 0–100", () => {
    expect(logPosition(0.5, [0.5, 50])).toBe(0);
    expect(logPosition(50, [0.5, 50])).toBe(100);
    expect(logPosition(5, [0.5, 50])).toBeCloseTo(50, 10);
  });
});
