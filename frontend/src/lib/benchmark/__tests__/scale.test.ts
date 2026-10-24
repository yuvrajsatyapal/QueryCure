import { describe, expect, test } from "vitest";
import { adaptiveLogTicks, dodgeLanes, fraction, logDomain, placeLabels, tickText, tukeyOutliers } from "../scale";

describe("logDomain", () => {
  test("pads the recorded values and keeps every one inside", () => {
    const d = logDomain([1.47, 1.69, 1], { minDecades: 0.1 })!;
    expect(d.lo).toBeLessThan(1);
    expect(d.hi).toBeGreaterThan(1.69);
    expect(d.widened).toBe(false);
  });

  test("a near-1× cluster is widened to the minimum span, not stretched across the chart", () => {
    const d = logDomain([1, 1.02, 1.05], { minDecades: 0.12 })!;
    expect(d.widened).toBe(true);
    expect(Math.log10(d.hi) - Math.log10(d.lo)).toBeCloseTo(0.12, 6);
    // The 3% interval covers well under half the axis: small differences stay small.
    expect(fraction(d, 1.05) - fraction(d, 1.02)).toBeLessThan(0.15);
  });

  test("a single value or identical values give a finite domain, never NaN", () => {
    const d = logDomain([1.3, 1.3], { minDecades: 0.1 })!;
    expect(Number.isFinite(d.lo) && Number.isFinite(d.hi)).toBe(true);
    expect(fraction(d, 1.3)).toBeCloseTo(0.5, 6);
  });

  test("non-positive and non-finite values are ignored; nothing usable gives null", () => {
    expect(logDomain([0, -1, Number.NaN, Number.POSITIVE_INFINITY])).toBeNull();
    expect(logDomain([0, 2, Number.NaN])!.hi).toBeGreaterThan(2);
  });
});

describe("adaptiveLogTicks", () => {
  const near = logDomain([1, 1.02, 1.08], { minDecades: 0.12 })!;

  test("an interval near 1× gets readable ticks around 1×, not just 1× and 2×", () => {
    const ticks = adaptiveLogTicks(near, 600, { must: [1] });
    expect(ticks).toContain(1);
    expect(ticks.length).toBeGreaterThanOrEqual(3);
    for (const t of ticks) expect(t).toBe(Number(t.toPrecision(3)));
  });

  test("a 0.9×–2× axis gets intermediate ticks, not just 0.9×, 1× and 2×", () => {
    const d = { lo: 0.9, hi: 2.02, widened: false };
    const ticks = adaptiveLogTicks(d, 460, { must: [1] });
    expect(ticks.length).toBeGreaterThanOrEqual(4);
    expect(ticks.some((t) => t > 1 && t < 2)).toBe(true);
  });

  test("density follows the width: fewer ticks on a phone than on a desktop", () => {
    const wide = logDomain([0.5, 4], { minDecades: 0.1 })!;
    const desktop = adaptiveLogTicks(wide, 900, { must: [1] });
    const phone = adaptiveLogTicks(wide, 260, { must: [1] });
    expect(phone.length).toBeLessThan(desktop.length);
    expect(phone).toContain(1);
  });

  test("ticks are never closer than the minimum gap in pixels", () => {
    for (const [lo, hi, w] of [
      [0.3, 30, 300],
      [0.9, 1.3, 240],
      [0.05, 0.4, 500],
      [1.2, 1.9, 320],
    ] as const) {
      const d = logDomain([lo, hi])!;
      const ticks = adaptiveLogTicks(d, w, { minGapPx: 40 });
      const xs = ticks.map((t) => fraction(d, t) * w);
      for (let i = 1; i < xs.length; i++) expect(xs[i]! - xs[i - 1]!).toBeGreaterThanOrEqual(40 - 1e-6);
    }
  });

  test("a required reference is kept and its crowding neighbours are dropped", () => {
    const d = logDomain([0.98, 1.4])!;
    const ticks = adaptiveLogTicks(d, 300, { must: [1], minGapPx: 40 });
    expect(ticks).toContain(1);
    const x1 = fraction(d, 1) * 300;
    for (const t of ticks) if (t !== 1) expect(Math.abs(fraction(d, t) * 300 - x1)).toBeGreaterThanOrEqual(40 - 1e-6);
  });

  test("intervals entirely below 1× and widely separated intervals still get ticks inside the domain", () => {
    for (const values of [[0.4, 0.7, 1], [0.02, 50, 1]]) {
      const d = logDomain(values)!;
      const ticks = adaptiveLogTicks(d, 500, { must: [1] });
      expect(ticks.length).toBeGreaterThanOrEqual(2);
      for (const t of ticks) expect(t >= d.lo && t <= d.hi).toBe(true);
    }
  });
});

describe("tickText", () => {
  test("prints at most three significant digits without trailing zeros", () => {
    expect(tickText(1)).toBe("1");
    expect(tickText(1.1)).toBe("1.1");
    expect(tickText(0.95)).toBe("0.95");
    expect(tickText(0.0003)).toBe("0.0003");
    expect(tickText(1.2500000001)).toBe("1.25");
  });
});

describe("placeLabels", () => {
  test("labels that would collide are hidden, and the priority label always survives", () => {
    const shown = placeLabels(
      [
        { key: "a", x: 100, text: "0.95×" },
        { key: "ref", x: 112, text: "1×", priority: true },
        { key: "c", x: 200, text: "1.5×" },
      ],
      320,
    );
    expect(shown.map((l) => l.key)).toEqual(["ref", "c"]);
  });

  test("labels at the edges are anchored inside the chart instead of clipped", () => {
    const shown = placeLabels(
      [
        { key: "lo", x: 2, text: "0.25 ms" },
        { key: "hi", x: 318, text: "5 ms" },
      ],
      320,
    );
    expect(shown.find((l) => l.key === "lo")!.anchor).toBe("start");
    expect(shown.find((l) => l.key === "hi")!.anchor).toBe("end");
  });
});

describe("dodgeLanes", () => {
  test("is deterministic and keeps overlapping samples on different lanes", () => {
    const p = [0.5, 0.5, 0.5, 0.2, 0.8];
    const a = dodgeLanes(p, 0.02, 5);
    expect(dodgeLanes(p, 0.02, 5)).toEqual(a);
    expect(new Set(a.slice(0, 3)).size).toBe(3);
    expect(a[3]).toBe(0);
    expect(a[4]).toBe(0);
  });

  test("lanes alternate around the centre and never exceed the limit", () => {
    const lanes = dodgeLanes(Array(20).fill(0.3), 0.02, 5);
    for (const l of lanes) expect(Math.abs(l)).toBeLessThanOrEqual(2);
    expect(lanes.slice(0, 5)).toEqual([0, -1, 1, -2, 2]);
  });
});

describe("tukeyOutliers", () => {
  test("flags samples beyond 1.5 IQR from the quartiles and keeps the rest", () => {
    expect(tukeyOutliers([1, 2, 3, 10, -5], 1.5, 3)).toEqual([false, false, false, true, true]);
  });

  test("a zero IQR does not flag samples equal to the quartiles", () => {
    expect(tukeyOutliers([2, 2, 2, 3], 2, 2)).toEqual([false, false, false, true]);
  });
});
