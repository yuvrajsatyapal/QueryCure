import { expect, test } from "vitest";
import type { EvidenceDetail, Finding, Hypothesis, OptimizationCandidate } from "@/lib/api/types";
import { buildRunScopeItems, groupRunScopeItems, RUN_SCOPE_GROUPS } from "../runScope";

const finding = (key: string, title: string, evidenceIds: string[] = []) =>
  ({ key, title, agent: "query_analyzer", detail: "d", severity: "high", evidenceIds }) as Finding;
const hypothesis = (key: string, statement: string, supportingEvidence: string[] = []) =>
  ({
    key,
    rank: 1,
    statement,
    category: "missing_index",
    supportingEvidence,
    contradictingEvidence: [],
    confidence: "medium",
    uncertaintyNotes: "",
    verificationMethod: "benchmark",
    proposedBy: ["index_strategist"],
  }) as Hypothesis;
const candidate = (key: string, status: string, ddl: string[]) =>
  ({ key, kind: "create_index", ddl, querySql: null, status }) as unknown as OptimizationCandidate;
const detail = (id: string, summary: string) =>
  ({ evidence: { id, kind: "plan_node", locator: "/0", summary, data: {}, provenance: "imported" } }) as unknown as EvidenceDetail;

const base = {
  runId: "run-1",
  findings: [finding("fd_1", "Seq Scan dominates", ["ev_a", "ev_b"])],
  hypotheses: [hypothesis("hy_1", "A composite index is missing", ["ev_b", "ev_c"])],
  candidates: [candidate("oc_1", "verified", ["CREATE INDEX ON orders (customer_id, created_at)"])],
  evidence: new Map<string, EvidenceDetail | "error">([
    ["ev_a", detail("ev_a", "Seq Scan on orders")],
    ["ev_c", "error"],
  ]),
  planArms: ["oc_1"],
};

test("one item per finding, hypothesis, candidate, plan diff and cited evidence, each stamped with its run", () => {
  const items = buildRunScopeItems(base);
  expect(items.map((i) => [i.group, i.label])).toEqual([
    ["Findings", "Seq Scan dominates"],
    ["Hypotheses", "A composite index is missing"],
    ["Candidates", "Composite index on orders (customer_id, created_at)"],
    ["Plan diffs", "Plan diff · baseline → oc_1"],
    ["Evidence", "Seq Scan on orders"],
    ["Evidence", "ev_b"],
    ["Evidence", "ev_c"],
  ]);
  expect(new Set(items.map((i) => i.runId))).toEqual(new Set(["run-1"]));
  expect(new Set(items.map((i) => i.id)).size).toBe(items.length);
});

test("findings say their severity and agent, so same-titled findings stay distinguishable", () => {
  expect(buildRunScopeItems(base).find((i) => i.group === "Findings")?.detail).toBe("High severity · Query Analyzer");
});

test("candidates show their recorded status in words, never a speed-up figure", () => {
  const [item] = buildRunScopeItems({ ...base, findings: [], hypotheses: [], planArms: [], evidence: new Map() });
  expect(item?.detail).toBe("Verified · tested scope");
  expect(item?.detail).not.toMatch(/×|speed/i);
  expect(item?.target).toEqual({ kind: "candidate", key: "oc_1" });
});

test("evidence distinguishes cached details, details not loaded yet, and details that could not be loaded", () => {
  const evidence = buildRunScopeItems(base).filter((i) => i.group === "Evidence");
  expect(evidence.map((i) => [i.label, i.detail, i.availability])).toEqual([
    ["Seq Scan on orders", "ev_a · plan_node · imported", "loaded"],
    ["ev_b", "Details load when opened", "not_loaded"],
    ["ev_c", "Details unavailable", "unavailable"],
  ]);
  expect(evidence.map((i) => i.target)).toEqual([
    { kind: "evidence", id: "ev_a" },
    { kind: "evidence", id: "ev_b" },
    { kind: "evidence", id: "ev_c" },
  ]);
});

test("plan diffs are offered only for arms with a captured plan; unknown plan data offers none", () => {
  expect(buildRunScopeItems({ ...base, planArms: [] }).some((i) => i.group === "Plan diffs")).toBe(false);
  expect(buildRunScopeItems({ ...base, planArms: null }).some((i) => i.group === "Plan diffs")).toBe(false);
  const diff = buildRunScopeItems(base).find((i) => i.group === "Plan diffs");
  expect(diff?.target).toEqual({ kind: "plan-diff", arm: "oc_1" });
  expect(diff?.detail).toBe("Composite index on orders (customer_id, created_at)");
});

test("missing data yields no items rather than placeholders", () => {
  expect(buildRunScopeItems({ runId: "run-1", findings: undefined, hypotheses: undefined, candidates: undefined, evidence: new Map(), planArms: null })).toEqual([]);
});

test("keys, IDs and categories are searchable keywords", () => {
  const items = buildRunScopeItems(base);
  const has = (id: string, word: string) => items.find((i) => i.id === id)?.keywords.includes(word);
  expect(has("finding-fd_1", "fd_1")).toBe(true);
  expect(has("finding-fd_1", "ev_a")).toBe(true);
  expect(has("hypothesis-hy_1", "missing_index")).toBe(true);
  expect(has("candidate-oc_1", "oc_1")).toBe(true);
  expect(has("evidence-ev_a", "ev_a")).toBe(true);
});

test("grouping keeps the group order and caps each group, counting what it hid", () => {
  const many = { ...base, findings: Array.from({ length: 7 }, (_, i) => finding(`fd_${i}`, `Finding ${i}`)) };
  const groups = groupRunScopeItems(buildRunScopeItems(many), 5);
  expect(groups.map((g) => g.group)).toEqual(RUN_SCOPE_GROUPS.filter((g) => groups.some((x) => x.group === g)));
  const findings = groups.find((g) => g.group === "Findings");
  expect(findings?.items).toHaveLength(5);
  expect(findings?.hidden).toBe(2);
  expect(groups.find((g) => g.group === "Hypotheses")?.hidden).toBe(0);
});
