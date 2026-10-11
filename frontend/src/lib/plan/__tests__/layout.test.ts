import { describe, expect, test } from "vitest";
import { metrics, plan } from "@/components/plan/__tests__/fixture";
import { EDGE_MAX_WIDTH, EDGE_MIN_WIDTH, edgeWidth, layoutPlan } from "../layout";
import { hottestNodeId } from "../hottest";

describe("layoutPlan", () => {
  test("lays out exactly the plan's nodes, one edge per parent link", () => {
    const { nodes, edges } = layoutPlan(plan);

    expect(nodes.map((n) => n.id).sort()).toEqual(plan.nodes.map((n) => n.id).sort());
    expect(edges.map((e) => [e.source, e.target])).toEqual([
      [0, 1],
      [1, 2],
    ]);
  });

  test("is top-down: every parent sits above its children", () => {
    const { nodes } = layoutPlan(plan);
    const y = new Map(nodes.map((n) => [n.id, n.y]));

    for (const node of plan.nodes) {
      if (node.parentId != null) expect(y.get(node.parentId)!).toBeLessThan(y.get(node.id)!);
    }
  });

  test("edges carry actual rows when analyzed, estimates otherwise", () => {
    expect(layoutPlan(plan).edges.find((e) => e.target === 2)?.rows).toBe(5000);

    const estimatesOnly = {
      ...plan,
      analyzed: false,
      nodes: plan.nodes.map((n) => ({ ...n, actualRows: null, actualLoops: null })),
    };
    const edge = layoutPlan(estimatesOnly).edges.find((e) => e.target === 2);
    expect(edge?.rows).toBe(500);
    expect(edge?.estimated).toBe(true);
  });
});

describe("edgeWidth", () => {
  test("grows with rows on a log scale and stays within bounds", () => {
    expect(edgeWidth(0)).toBe(EDGE_MIN_WIDTH);
    expect(edgeWidth(null)).toBe(EDGE_MIN_WIDTH);
    expect(edgeWidth(10)).toBeLessThan(edgeWidth(10_000));
    expect(edgeWidth(1e12)).toBe(EDGE_MAX_WIDTH);
  });
});

describe("hottestNodeId", () => {
  test("picks the node with the largest self time", () => {
    expect(hottestNodeId(metrics)).toBe(2);
  });

  test("is null when there is no timing (plain EXPLAIN)", () => {
    expect(hottestNodeId(metrics.map((m) => ({ ...m, selfTimeMs: null })))).toBeNull();
  });
});
