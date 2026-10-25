import { describe, expect, test } from "vitest";
import type { PlanDiff, PlanNodeDiff } from "@/lib/api/types";
import { changeLabels, diffRows, diffSummary, nodeMetricRows, ratioText, recordedActuals, summaryFigures } from "../diff";

const at = <T,>(xs: T[], i: number): T => {
  const v = xs[i];
  if (v === undefined) throw new Error(`no item ${i}`);
  return v;
};
const delta = (fromValue: number | null, toValue: number | null) => ({
  fromValue,
  toValue,
  ratio: fromValue !== null && toValue !== null && fromValue > 0 && toValue > 0 ? fromValue / toValue : null,
});
const none = delta(null, null);
const metrics = (over: Record<string, ReturnType<typeof delta>> = {}) => ({
  inclusiveTimeMs: none,
  selfTimeMs: none,
  totalActualRows: none,
  planRows: none,
  actualLoops: none,
  totalCost: none,
  selfSharedBlocks: none,
  selfTempWrittenBlocks: none,
  ...over,
});
const node = (over: Partial<PlanNodeDiff>): PlanNodeDiff =>
  ({
    status: "same",
    fromId: 1,
    toId: 1,
    fromLocator: "/a",
    toLocator: "/b",
    nodeTypeFrom: "Limit",
    nodeTypeTo: "Limit",
    relation: null,
    indexFrom: null,
    indexTo: null,
    depth: 0,
    changes: [],
    metrics: metrics(),
    ...over,
  }) as PlanNodeDiff;
const diff = (nodes: PlanNodeDiff[], summary: Partial<PlanDiff["summary"]> = {}): PlanDiff =>
  ({
    summary: {
      same: 0,
      changed: 0,
      added: 0,
      removed: 0,
      addedNodeTypes: [],
      removedNodeTypes: [],
      indexesUsedFrom: [],
      indexesUsedTo: [],
      newIndexesUsed: [],
      executionTimeMs: none,
      planningTimeMs: none,
      rootTotalCost: none,
      ...summary,
    },
    nodes,
  }) as PlanDiff;

// The shape of the local stub sandbox run: Sort and Seq Scan removed, Index Scan added.
const analyzed = diff(
  [
    node({ metrics: metrics({ totalActualRows: delta(50, 50), selfTimeMs: delta(0.01, 0.01), planRows: delta(50, 50) }) }),
    node({ status: "removed", toId: null, toLocator: null, nodeTypeFrom: "Sort", nodeTypeTo: null, depth: 1, metrics: metrics({ totalActualRows: delta(50, null), selfTimeMs: delta(0.2, null) }) }),
    node({ status: "removed", toId: null, toLocator: null, nodeTypeFrom: "Seq Scan", nodeTypeTo: null, relation: "orders", depth: 2, metrics: metrics({ totalActualRows: delta(1200, null), selfSharedBlocks: delta(90, null) }) }),
    node({
      status: "added",
      fromId: null,
      fromLocator: null,
      nodeTypeFrom: null,
      nodeTypeTo: "Index Scan",
      relation: "orders",
      indexTo: "orders_customer_id_created_at_idx",
      depth: 1,
      metrics: metrics({ totalActualRows: delta(null, 50), selfTimeMs: delta(null, 0.03), selfSharedBlocks: delta(null, 4) }),
    }),
  ],
  { removed: 2, added: 1, same: 1, removedNodeTypes: ["Seq Scan", "Sort"], addedNodeTypes: ["Index Scan"], newIndexesUsed: ["orders_customer_id_created_at_idx"], executionTimeMs: delta(0.32, 0.04) },
);

describe("diffRows", () => {
  test("pairs each side with what was recorded, and marks one-sided rows", () => {
    const rows = diffRows(analyzed);
    expect(rows.map((r) => r.status)).toEqual(["same", "removed", "removed", "added"]);
    expect(at(rows, 1).from?.label).toBe("Sort");
    expect(at(rows, 1).to).toBeNull();
    expect(at(rows, 3).from).toBeNull();
    expect(at(rows, 3).to).toMatchObject({ label: "Index Scan", relation: "orders", index: "orders_customer_id_created_at_idx" });
    expect(at(rows, 3).to?.rows).toEqual({ value: 50, kind: "measured" });
    expect(at(rows, 3).to?.selfMs).toBe(0.03);
    expect(new Set(rows.map((r) => r.key)).size).toBe(rows.length);
  });

  test("a node type change reads from → to and names what changed", () => {
    const row = at(diffRows(
      diff([node({ status: "changed", nodeTypeFrom: "Seq Scan", nodeTypeTo: "Index Scan", relation: "orders", indexTo: "o_idx", changes: ["node_type", "index_name"] })]),
    ), 0);
    expect(row.label).toBe("Seq Scan → Index Scan");
    expect(row.typeChanged).toBe(true);
    expect(row.changes).toEqual(["node type", "index"]);
  });

  test("without actual rows the planner estimate is shown and labelled as one", () => {
    const row = at(diffRows(diff([node({ metrics: metrics({ planRows: delta(1000, 20) }) })])), 0);
    expect(row.from?.rows).toEqual({ value: 1000, kind: "estimated" });
    expect(row.to?.rows).toEqual({ value: 20, kind: "estimated" });
    expect(row.from?.selfMs).toBeNull();
  });

  test("a side with nothing recorded has no rows figure rather than a zero", () => {
    const row = at(diffRows(diff([node({})])), 0);
    expect(row.from?.rows).toBeNull();
  });
});

describe("changeLabels", () => {
  test("maps every compared field the backend reports and keeps unknown ones verbatim", () => {
    expect(changeLabels(["node_type", "relation_name", "index_name", "join_type", "index_cond", "filter", "sort_key", "sort_method", "something_new"])).toEqual([
      "node type",
      "relation",
      "index",
      "join type",
      "index condition",
      "filter",
      "sort key",
      "sort method",
      "something_new",
    ]);
  });
});

describe("nodeMetricRows", () => {
  test("lists only recorded metrics, each with its provenance", () => {
    const rows = nodeMetricRows(at(analyzed.nodes, 3));
    expect(rows.map((r) => r.key)).toEqual(["selfTimeMs", "totalActualRows", "selfSharedBlocks"]);
    expect(rows.every((r) => r.kind === "measured")).toBe(true);
    const est = nodeMetricRows(node({ metrics: metrics({ planRows: delta(10, 5), totalCost: delta(100, 4) }) }));
    expect(est.map((r) => [r.key, r.kind])).toEqual([
      ["planRows", "estimated"],
      ["totalCost", "estimated"],
    ]);
  });
});

describe("summaryFigures", () => {
  test("keeps the capture time, planner cost and buffer sum apart, with their sources", () => {
    const figures = summaryFigures(
      diff(analyzed.nodes, { executionTimeMs: delta(0.32, 0.04), rootTotalCost: delta(1500, 12), planningTimeMs: none }),
    );
    expect(figures.map((f) => f.key)).toEqual(["executionTimeMs", "rootTotalCost", "sharedBlocks"]);
    expect(figures.find((f) => f.key === "executionTimeMs")).toMatchObject({ kind: "measured", from: 0.32, to: 0.04 });
    expect(figures.find((f) => f.key === "rootTotalCost")?.kind).toBe("estimated");
    // Summed over the nodes that recorded buffers on each side: 90 baseline, 4 candidate.
    expect(figures.find((f) => f.key === "sharedBlocks")).toMatchObject({ from: 90, to: 4, kind: "measured" });
  });

  test("a figure is left out when neither side recorded it", () => {
    expect(summaryFigures(diff([node({})]))).toEqual([]);
  });
});

describe("recordedActuals", () => {
  test("tells EXPLAIN ANALYZE plans from estimate-only plans, per side", () => {
    expect(recordedActuals(analyzed)).toEqual({ from: true, to: true });
    expect(recordedActuals(diff([node({ metrics: metrics({ planRows: delta(10, 10) }) })]))).toEqual({ from: false, to: false });
  });
});

describe("ratioText", () => {
  test("describes a ratio without claiming a speedup", () => {
    expect(ratioText(8)).toBe("8.00× lower");
    expect(ratioText(0.5)).toBe("2.00× higher");
    expect(ratioText(1)).toBe("unchanged");
    expect(ratioText(null)).toBeNull();
  });
});

test("diffSummary reads like the design", () => {
  expect(diffSummary(analyzed)).toBe("Seq Scan, Sort removed; Index Scan added; new index used: orders_customer_id_created_at_idx");
  expect(diffSummary(diff([node({})]))).toBe("No structural change");
});
