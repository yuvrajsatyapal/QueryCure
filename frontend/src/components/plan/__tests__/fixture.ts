import type { NodeMetrics, PlanNode, PlanTree } from "@/lib/api/types";

function node(id: number, parentId: number | null, nodeType: string, extra: Partial<PlanNode> = {}): PlanNode {
  return {
    id,
    parentId,
    locator: `/0/Plan${id ? `/Plans/${id - 1}` : ""}`,
    nodeType,
    children: [],
    extra: {},
    ...extra,
  } as PlanNode;
}

// Mirrors the synthetic canonical fixture used by the backend tests (hand-computed numbers).
const scan = node(2, 1, "Seq Scan", { relationName: "orders", planRows: 500, actualRows: 5000, actualLoops: 1, filter: "(customer_id = 1024)" });
const sort = node(1, 0, "Sort", { planRows: 500, actualRows: 20, actualLoops: 1, sortKey: ["created_at DESC"], children: [scan] });
const limit = node(0, null, "Limit", { planRows: 20, actualRows: 20, actualLoops: 1, children: [sort] });

export const plan: PlanTree = {
  root: limit,
  nodes: [limit, sort, scan],
  analyzed: true,
  hasTiming: true,
  hasBuffers: true,
  planningTimeMs: 0.25,
  executionTimeMs: 121,
};

const base = { rowsRemovedByFilterTotal: null, sortSpilled: false, selfSharedHitBlocks: 0, selfSharedReadBlocks: 0, selfTempReadBlocks: 0, selfTempWrittenBlocks: 0 };
export const metrics: NodeMetrics[] = [
  { ...base, nodeId: 0, inclusiveTimeMs: 120.5, selfTimeMs: 0.5, selfTimeShare: 0.5 / 120.5, totalActualRows: 20, estimateErrorRatio: 1, estimateDirection: "exact" },
  { ...base, nodeId: 1, inclusiveTimeMs: 120, selfTimeMs: 20, selfTimeShare: 20 / 120.5, totalActualRows: 20, estimateErrorRatio: 25, estimateDirection: "over", sortSpilled: true, selfTempReadBlocks: 50, selfTempWrittenBlocks: 50 },
  { ...base, nodeId: 2, inclusiveTimeMs: 100, selfTimeMs: 100, selfTimeShare: 100 / 120.5, totalActualRows: 5000, estimateErrorRatio: 10, estimateDirection: "under", rowsRemovedByFilterTotal: 995000, selfSharedHitBlocks: 100, selfSharedReadBlocks: 900 },
] as NodeMetrics[];
