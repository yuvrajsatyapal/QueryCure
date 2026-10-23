import { describe, expect, test } from "vitest";
import type { NodeMetrics, PlanNode, PlanTree } from "@/lib/api/types";
import { metrics, plan } from "@/components/plan/__tests__/fixture";
import {
  ancestorIds,
  costShare,
  estimateAssessment,
  estimateSentence,
  expandableIds,
  stopsEarly,
  nodeFlags,
  planSummary,
} from "../analysis";

const m = (over: Partial<NodeMetrics>): NodeMetrics => ({ nodeId: 9, estimateErrorRatio: null, estimateDirection: null, ...over }) as NodeMetrics;
const n = (over: Partial<PlanNode>): PlanNode => ({ id: 9, nodeType: "Index Scan", children: [], extra: {}, locator: "/x", ...over }) as PlanNode;

describe("estimateAssessment", () => {
  test("uses the backend ratio and direction; 10× is significant, 100× severe", () => {
    expect(estimateAssessment(n({ planRows: 500, actualRows: 5000, actualLoops: 1 }), m({ estimateErrorRatio: 10, estimateDirection: "under" })).level).toBe("significant");
    expect(estimateAssessment(n({ planRows: 5, actualRows: 5000, actualLoops: 1 }), m({ estimateErrorRatio: 1000, estimateDirection: "under" })).level).toBe("severe");
    expect(estimateAssessment(n({ planRows: 500, actualRows: 600, actualLoops: 1 }), m({ estimateErrorRatio: 1.2, estimateDirection: "under" })).level).toBe("ok");
  });

  test("a node that never executed is not a misestimate", () => {
    // PostgreSQL reports actual rows 0 for a never-executed node; the raw ratio would read 500× over.
    const a = estimateAssessment(n({ planRows: 500, actualRows: 0, actualLoops: 0 }), m({ estimateErrorRatio: 500, estimateDirection: "over" }));
    expect(a.level).toBe("never_executed");
  });

  test("a large ratio on a handful of rows is shown but not flagged", () => {
    const a = estimateAssessment(n({ planRows: 1, actualRows: 12, actualLoops: 1 }), m({ estimateErrorRatio: 12, estimateDirection: "under" }));
    expect(a.level).toBe("small");
  });

  test("small rows per loop still count when the loops add up", () => {
    // 1 estimated vs 15 actual per loop over 10,000 loops: 150,000 rows the planner did not expect.
    const a = estimateAssessment(n({ planRows: 1, actualRows: 15, actualLoops: 10_000 }), m({ estimateErrorRatio: 15, estimateDirection: "under" }));
    expect(a.level).toBe("significant");
  });

  test("plain EXPLAIN has no actual rows, so the error is unavailable", () => {
    expect(estimateAssessment(n({ planRows: 500 }), m({})).level).toBe("unavailable");
    expect(estimateAssessment(n({ planRows: 500 }), undefined).level).toBe("unavailable");
  });
});

test("estimateSentence states expected and returned rows per loop in words", () => {
  const node = n({ planRows: 120, actualRows: 4812, actualLoops: 1 });
  expect(estimateSentence(node, m({ estimateErrorRatio: 40.1, estimateDirection: "under" }))).toBe(
    "Planner expected 120 rows per loop; 4,812 returned: 40× under.",
  );
  expect(estimateSentence(n({ planRows: 500, actualRows: 0, actualLoops: 0 }), m({ estimateErrorRatio: 500 }))).toBe(
    "Never executed: the planner expected 500 rows per loop.",
  );
  expect(estimateSentence(n({ planRows: 500 }), undefined)).toBe("Planner expected 500 rows per loop; actual rows not measured (plain EXPLAIN).");
});

describe("nodeFlags", () => {
  test("hottest is the single largest self time; expensive is a share of at least 20%", () => {
    const flags = nodeFlags(plan, metrics);
    expect(flags.get(2)).toMatchObject({ hottest: true, expensive: true });
    expect(flags.get(1)).toMatchObject({ hottest: false, expensive: false }); // 20 / 120.5 = 16.6%
    expect(flags.get(0)).toMatchObject({ hottest: false, expensive: false });
  });

  test("without timing nothing is flagged expensive or hottest", () => {
    const noTiming = metrics.map((x) => ({ ...x, selfTimeMs: null, selfTimeShare: null, inclusiveTimeMs: null }));
    const flags = nodeFlags({ ...plan, analyzed: false, hasTiming: false }, noTiming);
    expect([...flags.values()].some((f) => f.hottest || f.expensive)).toBe(false);
  });
});

test("planSummary counts flagged nodes and carries the plan's own timings", () => {
  expect(planSummary(plan, metrics)).toEqual({
    nodes: 3,
    analyzed: true,
    hasTiming: true,
    hasBuffers: true,
    planningTimeMs: 0.25,
    executionTimeMs: 121,
    expensive: 1,
    misestimates: 1, // the Sort's 25× over sits below a LIMIT that stopped it early
    hottestId: 2,
  });
});

test("ancestorIds lists parents from the root down, for revealing a selected node", () => {
  expect(ancestorIds(plan, 2)).toEqual([0, 1]);
  expect(ancestorIds(plan, 0)).toEqual([]);
  expect(ancestorIds(plan, 42)).toEqual([]);
});

test("expandableIds lists every node with children", () => {
  expect(expandableIds(plan)).toEqual([0, 1]);
});

test("costShare is cumulative cost relative to the costliest node, not to the root", () => {
  // A Limit root is cheaper than the Sort it stops early, so the root is not the denominator.
  const costed: PlanTree = {
    ...plan,
    nodes: plan.nodes.map((x) => ({ ...x, totalCost: x.id === 0 ? 50 : x.id === 1 ? 200 : 100 })),
  };
  expect(costShare(costed, costed.nodes[0]!)).toBeCloseTo(0.25);
  expect(costShare(costed, costed.nodes[1]!)).toBe(1);
  expect(costShare(plan, plan.nodes[0]!)).toBeNull(); // no costs recorded
});

describe("stopsEarly: a LIMIT above stops a node before it returns every row", () => {
  // Limit -> Gather Merge -> Sort -> Seq Scan, as in the recorded orders plan.
  const scan = n({ id: 3, parentId: 2, nodeType: "Seq Scan" });
  const sort = n({ id: 2, parentId: 1, nodeType: "Sort", children: [scan] });
  const gather = n({ id: 1, parentId: 0, nodeType: "Gather Merge", children: [sort] });
  const limit = n({ id: 0, parentId: null, nodeType: "Limit", children: [gather] });
  const tree = { root: limit, nodes: [limit, gather, sort, scan], analyzed: true, hasTiming: true, hasBuffers: false } as unknown as PlanTree;

  test("nodes streaming into the LIMIT stop early; a Sort's input does not", () => {
    expect(stopsEarly(tree, 1)).toBe(true);
    expect(stopsEarly(tree, 2)).toBe(true); // the Sort reads all input but emits only what is pulled
    expect(stopsEarly(tree, 3)).toBe(false); // the Sort consumed the whole scan
    expect(stopsEarly(tree, 0)).toBe(false);
  });

  test("a hashed aggregate consumes all input, a sorted one streams", () => {
    const hashed = { ...tree, nodes: tree.nodes.map((x) => (x.id === 2 ? { ...x, nodeType: "Aggregate", extra: { Strategy: "Hashed" } } : x)) } as PlanTree;
    const sorted = { ...tree, nodes: tree.nodes.map((x) => (x.id === 2 ? { ...x, nodeType: "Aggregate", extra: { Strategy: "Sorted" } } : x)) } as PlanTree;
    expect(stopsEarly(hashed, 3)).toBe(false);
    expect(stopsEarly(sorted, 3)).toBe(true);
  });

  test("fewer rows than estimated below a LIMIT is not flagged; more rows still is", () => {
    const over = estimateAssessment(n({ planRows: 8666, actualRows: 20, actualLoops: 1 }), m({ estimateErrorRatio: 433.3, estimateDirection: "over" }), { stoppedEarly: true });
    expect(over.level).toBe("stopped_early");
    const under = estimateAssessment(n({ planRows: 20, actualRows: 8666, actualLoops: 1 }), m({ estimateErrorRatio: 433.3, estimateDirection: "under" }), { stoppedEarly: true });
    expect(under.level).toBe("severe");
  });

  test("nodeFlags applies the rule from the plan's own structure", () => {
    const metricsFor = [
      m({ nodeId: 1, estimateErrorRatio: 433, estimateDirection: "over" }),
      m({ nodeId: 3, estimateErrorRatio: 50, estimateDirection: "over" }),
    ];
    const withRows = {
      ...tree,
      nodes: tree.nodes.map((x) => ({ ...x, planRows: 8666, actualRows: 20, actualLoops: 1 })),
    } as PlanTree;
    const flags = nodeFlags(withRows, metricsFor);
    expect(flags.get(1)?.estimate.level).toBe("stopped_early");
    expect(flags.get(3)?.estimate.level).toBe("significant");
  });
});
