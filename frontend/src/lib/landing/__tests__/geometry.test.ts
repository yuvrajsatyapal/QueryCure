import { expect, test } from "vitest";
import { curve } from "../geometry";

const rect = (left: number, top: number, width: number, height: number) => ({ left, top, width, height, right: left + width, bottom: top + height });

test("a target below the source gets a vertical S-curve from bottom-centre to top-centre", () => {
  expect(curve(rect(0, 0, 100, 40), rect(200, 100, 100, 40), { left: 0, top: 0 })).toBe("M50,40 C50,70 250,70 250,100");
});

test("a target beside the source gets a horizontal S-curve from right edge to left edge", () => {
  expect(curve(rect(0, 0, 100, 40), rect(200, 0, 100, 40), { left: 0, top: 0 })).toBe("M100,20 C150,20 150,20 200,20");
});

test("coordinates are relative to the box and the direction can be forced", () => {
  expect(curve(rect(10, 10, 20, 20), rect(10, 100, 20, 20), { left: 10, top: 10 }, "h")).toBe("M20,10 C10,10 10,100 0,100");
});
