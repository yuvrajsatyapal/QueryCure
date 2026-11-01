import { describe, expect, test } from "vitest";
import { XRAY_VIEWS, elbowPath, viewDiff } from "../xray";

describe("X-Ray views", () => {
  test("Before is Limit → Sort → Seq Scan with its endpoint; After is Limit → Index Scan with removed operators", () => {
    expect(XRAY_VIEWS.before.show).toEqual(["limit", "sort", "seq", "note", "baseline"]);
    expect(XRAY_VIEWS.after.show).toEqual(["limit", "idx", "removed", "note", "result"]);
  });

  test("edges run child to parent, leaf first", () => {
    expect(XRAY_VIEWS.before.edges.map(([c, p]) => `${c}>${p}`)).toEqual(["seq>sort", "sort>limit"]);
    expect(XRAY_VIEWS.after.edges.map(([c, p]) => `${c}>${p}`)).toEqual(["idx>limit"]);
  });

  test("the notes scope the 20-row stop and the missing Sort to this example", () => {
    expect(XRAY_VIEWS.after.note).toMatch(/^In this example/);
    expect(XRAY_VIEWS.after.note).toMatch(/stops after 20/);
  });
});

describe("viewDiff", () => {
  test("Before → After: Sort, Seq Scan and the baseline leave; Index Scan, removed list and result enter", () => {
    expect(viewDiff("before", "after")).toEqual({
      leaving: ["sort", "seq", "note", "baseline"],
      entering: ["idx", "removed", "note", "result"],
    });
  });

  test("After → Before is the mirror", () => {
    expect(viewDiff("after", "before")).toEqual({
      leaving: ["idx", "removed", "note", "result"],
      entering: ["sort", "seq", "note", "baseline"],
    });
  });

  test("the same view changes nothing", () => {
    expect(viewDiff("after", "after")).toEqual({ leaving: [], entering: [] });
  });
});

describe("elbowPath", () => {
  test("runs from the child's left edge to the parent's spine, then up to the parent's bottom", () => {
    const child = { left: 40, top: 60, height: 50 };
    const parent = { left: 14, top: 0, height: 40 };
    expect(elbowPath(child, parent, 13)).toBe("M40 79H27V40");
  });

  test("a short child anchors at its middle", () => {
    expect(elbowPath({ left: 30, top: 100, height: 20 }, { left: 10, top: 50, height: 30 }, 7)).toBe("M30 110H17V80");
  });
});
