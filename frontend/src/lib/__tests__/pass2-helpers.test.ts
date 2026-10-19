import { expect, test } from "vitest";
import { cappedCount, sumCounts } from "@/lib/investigations/counts";
import { groupByDay } from "@/lib/investigations/grouping";
import { reportSections } from "@/lib/report/sections";
import type { ReportV1 } from "@/lib/report/types";

test("a page without a next cursor is an exact count; one with a cursor is a lower bound", () => {
  expect(cappedCount({ items: [1, 2, 3], nextCursor: null })).toEqual({ value: 3, capped: false, label: "3" });
  expect(cappedCount({ items: new Array(100).fill(0), nextCursor: "c" })).toEqual({ value: 100, capped: true, label: "100+" });
  expect(cappedCount(undefined)).toBeNull();
  // A sum stays a lower bound when any part was capped, and unknown while any part is loading.
  expect(sumCounts([cappedCount({ items: [1], nextCursor: null }), cappedCount({ items: new Array(100).fill(0), nextCursor: "c" })])).toEqual({
    value: 101,
    capped: true,
    label: "101+",
  });
  expect(sumCounts([cappedCount({ items: [1, 2], nextCursor: null }), null])).toBeNull();
});

test("investigations group by local creation day, with month headings for older ones", () => {
  // Wednesday 2026-10-21, noon local time.
  const now = new Date(2026, 9, 21, 12, 0).getTime();
  const at = (d: number, m = 9, h = 9) => ({ createdAt: new Date(2026, m, d, h).toISOString() });
  const items = [at(21, 9, 11), at(21, 9, 1), at(20), at(19), at(17), at(3), at(28, 8)];
  const groups = groupByDay(items, now);
  expect(groups.map((g) => [g.label, g.items.length])).toEqual([
    ["Today", 2],
    ["Yesterday", 1],
    ["Earlier this week", 1],
    ["October 2026", 2],
    ["September 2026", 1],
  ]);
  // Order inside a group is the input order (the endpoint's newest-first).
  expect(groups[0]!.items[0]).toBe(items[0]);
  expect(groupByDay([], now)).toEqual([]);
});

const base = {
  query: { sql: "SELECT 1" },
  rounds: [],
  replay: null,
  missing: [],
  limitations: ["l"],
  nextSteps: ["n"],
} as unknown as ReportV1;

test("the table of contents lists only the sections the report renders, in article order", () => {
  expect(reportSections(base).map((s) => s.title)).toEqual([
    "Query",
    "Observed problem",
    "Hypotheses",
    "Recommendation",
    "Limitations",
    "Next steps",
    "Provenance and integrity",
  ]);
  const full = {
    ...base,
    rounds: [{}],
    replay: { replayOf: null, comparison: {} },
    missing: [{ section: "x", reason: "y" }],
  } as unknown as ReportV1;
  const sections = reportSections(full);
  expect(sections.map((s) => s.title)).toContain("Optimizations, approvals and benchmarks");
  expect(sections.map((s) => s.title)).toContain("Experiment replay");
  expect(sections.map((s) => s.title)).toContain("Missing evidence");
  expect(sections.find((s) => s.title === "Observed problem")?.id).toBe("report-observed-problem");
  expect(new Set(sections.map((s) => s.id)).size).toBe(sections.length);
});
