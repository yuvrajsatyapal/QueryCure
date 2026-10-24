import { expect, test } from "vitest";
import type { EvidenceDetail, Finding, Hypothesis, RunEvent } from "@/lib/api/types";
import { buildTrace } from "@/lib/events/trace";
import {
  ancestorIds,
  citationsByNode,
  citedEvidenceIds,
  evidenceIdsOfSpan,
  findSpan,
  indexClaimSpans,
  indexEvidenceSpans,
  planTargetOfEvidence,
  stepForClaim,
  traceRows,
  treeKey,
} from "../links";

let seq = 0;
const ev = (type: string, payload: Record<string, unknown>): RunEvent => {
  seq += 1;
  return { runId: "r", seq, ts: new Date(Date.UTC(2026, 9, 12, 10, 0, seq)).toISOString(), type, payload } as RunEvent;
};

function sampleTrace() {
  seq = 0;
  return buildTrace(
    [
      ev("node.started", { node: "query_analyzer", agent: "query_analyzer", attempt: 1 }),
      ev("tool.started", { tool: "get_plan_node", agent: "query_analyzer" }),
      ev("tool.completed", { tool: "get_plan_node", agent: "query_analyzer", status: "ok", durationMs: 5, evidenceIds: ["ev_000000000001"] }),
      ev("finding.created", { key: "fd_1", agent: "query_analyzer", title: "Seq Scan", evidenceIds: ["ev_000000000001", "ev_000000000002"] }),
      ev("node.completed", { node: "query_analyzer", agent: "query_analyzer", attempt: 1, durationMs: 9 }),
      ev("node.started", { node: "synthesize_hypotheses", agent: "supervisor", attempt: 1 }),
      ev("hypothesis.created", { key: "hy_1", supportingEvidence: ["ev_000000000001"], contradictingEvidence: ["ev_000000000003"] }),
      ev("hypothesis.created", { key: "hy_1", supportingEvidence: [], contradictingEvidence: [] }),
      ev("node.completed", { node: "synthesize_hypotheses", agent: "supervisor", attempt: 1, durationMs: 3 }),
    ],
    { active: false },
  );
}

test("a claim key resolves to the step of its creation event; missing and ambiguous keys say so", () => {
  const trace = sampleTrace();
  const index = indexClaimSpans(trace);

  const finding = stepForClaim(index, "fd_1");
  expect(finding).toMatchObject({ status: "found", matches: 1 });
  expect(findSpan(trace, finding.status === "found" ? finding.spanId : "")?.name).toBe("Finding: Seq Scan");

  // Two events carry hy_1: the first is selected and the count is reported.
  const hypothesis = stepForClaim(index, "hy_1");
  expect(hypothesis).toMatchObject({ status: "found", matches: 2 });
  expect(stepForClaim(index, "fd_unknown")).toEqual({ status: "missing" });
});

test("ancestors of a nested row are its enclosing nodes, outermost first, excluding the run", () => {
  const trace = sampleTrace();
  const tool = trace.children[0]!.children[0]!;
  expect(ancestorIds(trace, tool.id)).toEqual([trace.children[0]!.id]);
  expect(ancestorIds(trace, trace.children[0]!.id)).toEqual([]);
  expect(ancestorIds(trace, "nope")).toEqual([]);
});

test("evidence maps to the trace rows that recorded it, producing tool first", () => {
  const trace = sampleTrace();
  const [analyst, synth] = trace.children;
  const index = indexEvidenceSpans(trace);
  expect(index.get("ev_000000000001")).toEqual([analyst!.children[0]!.id, analyst!.children[1]!.id, synth!.children[0]!.id]);
  expect(index.get("ev_000000000003")).toEqual([synth!.children[0]!.id]);
  expect(index.has("ev_000000000009")).toBe(false);
});

test("a step's evidence is everything its events recorded, deduplicated in order", () => {
  const trace = sampleTrace();
  const [analyst, synth] = trace.children;
  expect(evidenceIdsOfSpan(analyst!.children[0]!)).toEqual(["ev_000000000001"]);
  expect(evidenceIdsOfSpan(analyst!.children[1]!)).toEqual(["ev_000000000001", "ev_000000000002"]);
  expect(evidenceIdsOfSpan(synth!.children[0]!)).toEqual(["ev_000000000001", "ev_000000000003"]);
  // A node aggregates nothing it did not record itself.
  expect(evidenceIdsOfSpan(analyst!)).toEqual([]);
});

const plans = [{ sha256: "planA", plan: { nodes: [{ id: 0 }, { id: 2 }] } }];
const detail = (kind: string, data: Record<string, unknown>, sha: string | null): EvidenceDetail =>
  ({
    evidence: { id: "ev_000000000001", kind, locator: "", summary: "s", data, provenance: "imported", artifactSha256: sha },
    artifact: sha ? { sha256: sha, kind: "plan_analyze" } : null,
    citedByFindings: [],
    citedByHypotheses: [],
  }) as unknown as EvidenceDetail;

test("plan-node evidence resolves to a node of this run's plan, and every other case is named", () => {
  expect(planTargetOfEvidence(detail("plan_node", { nodeId: 2 }, "planA"), plans)).toEqual({ status: "found", planSha: "planA", nodeId: 2 });
  expect(planTargetOfEvidence(detail("index_list", {}, null), plans)).toEqual({ status: "not_plan_node" });
  expect(planTargetOfEvidence(detail("plan_node", { nodeId: 2 }, "other"), plans)).toEqual({ status: "plan_unavailable" });
  expect(planTargetOfEvidence(detail("plan_node", { nodeId: 9 }, "planA"), plans)).toEqual({ status: "node_unavailable", planSha: "planA" });
  expect(planTargetOfEvidence(detail("plan_node", { nodeId: "2" }, "planA"), plans)).toEqual({ status: "node_unavailable", planSha: "planA" });
});

test("citations group findings and hypotheses by the plan node their evidence resolves to", () => {
  const findings = [
    { key: "fd_1", evidenceIds: ["ev_a", "ev_b"] },
    { key: "fd_2", evidenceIds: ["ev_c"] },
  ] as Finding[];
  const hypotheses = [{ key: "hy_1", supportingEvidence: ["ev_a"], contradictingEvidence: ["ev_d"] }] as unknown as Hypothesis[];
  expect(citedEvidenceIds(findings, hypotheses)).toEqual(["ev_a", "ev_b", "ev_c", "ev_d"]);

  const resolved = new Map<string, EvidenceDetail | "error">([
    ["ev_a", detail("plan_node", { nodeId: 2 }, "planA")],
    ["ev_b", detail("plan_node", { nodeId: 2 }, "planA")],
    ["ev_c", "error"],
    // ev_d not resolved yet: pending.
  ]);
  const result = citationsByNode(findings, hypotheses, resolved, "planA");
  expect(result.byNode.get(2)).toEqual({ findings: ["fd_1"], hypotheses: ["hy_1"] });
  expect(result.byNode.size).toBe(1);
  expect(result).toMatchObject({ pending: 1, failed: 1 });
  // Another plan of the run gets none of these citations.
  expect(citationsByNode(findings, hypotheses, resolved, "planB").byNode.size).toBe(0);
});

test("tree keys move through visible rows, expand, collapse and climb to the parent", () => {
  const trace = sampleTrace();
  const analyst = trace.children[0]!;
  const tool = analyst.children[0]!;
  const rows = traceRows(trace, new Set());
  expect(rows.map((r) => [r.span.id, r.depth])).toEqual([
    ["run", 0],
    [analyst.id, 1],
    [tool.id, 2],
    [analyst.children[1]!.id, 2],
    [trace.children[1]!.id, 1],
    [trace.children[1]!.children[0]!.id, 2],
    [trace.children[1]!.children[1]!.id, 2],
  ]);
  const collapsed = new Set<string>();
  expect(treeKey(rows, "run", "ArrowDown", collapsed)).toEqual({ select: analyst.id });
  expect(treeKey(rows, "run", "ArrowUp", collapsed)).toBeNull();
  expect(treeKey(rows, tool.id, "ArrowLeft", collapsed)).toEqual({ select: analyst.id });
  expect(treeKey(rows, analyst.id, "ArrowLeft", collapsed)).toEqual({ collapse: analyst.id });
  expect(treeKey(rows, analyst.id, "ArrowRight", collapsed)).toEqual({ select: tool.id });
  expect(treeKey(rows, analyst.id, "ArrowRight", new Set([analyst.id]))).toEqual({ expand: analyst.id });
  expect(treeKey(rows, tool.id, "ArrowRight", collapsed)).toBeNull();
  expect(treeKey(rows, tool.id, "Home", collapsed)).toEqual({ select: "run" });
  expect(treeKey(rows, "run", "End", collapsed)).toEqual({ select: rows.at(-1)!.span.id });
  expect(treeKey(rows, "run", "x", collapsed)).toBeNull();
});
