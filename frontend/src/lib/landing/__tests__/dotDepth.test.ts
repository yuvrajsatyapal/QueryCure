import { describe, expect, it } from "vitest";
import { DOT_DEPTH, farLayerOffset } from "../dotDepth";

describe("farLayerOffset", () => {
  it("is zero at the top of the page", () => {
    expect(Math.abs(farLayerOffset(0, 2))).toBe(0);
  });

  it("trails scroll at the parallax fraction", () => {
    expect(farLayerOffset(100, 1)).toBe(-10);
  });

  it("wraps within one tile so the pattern repeats seamlessly", () => {
    for (const y of [0, 333, 1200, 7919, 40000]) {
      const off = farLayerOffset(y, 2);
      expect(off).toBeLessThanOrEqual(0);
      expect(off).toBeGreaterThan(-DOT_DEPTH.tile);
    }
  });

  it("snaps to whole device pixels", () => {
    for (const y of [1, 37, 123, 999]) {
      const device = farLayerOffset(y, 2) * 2;
      expect(Math.abs(device - Math.round(device))).toBeLessThan(1e-9);
    }
  });

  it("does not move when intensity is zero", () => {
    expect(Math.abs(farLayerOffset(5000, 2, { ...DOT_DEPTH, intensity: 0 }))).toBe(0);
  });
});
