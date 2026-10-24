import { describe, expect, test } from "vitest";
import type { EvidenceDetail, Finding, Hypothesis, OptimizationCandidate, Verification } from "@/lib/api/types";
import { buildEvidenceGraph, countCrossings, explainingSelection, linkClass, orderNodes, pathOf } from "../graph";

const finding = (key: string, evidenceIds: string[]): Finding =>
  ({ key, agent: "query_analyzer", title: `Finding ${key}`, detail: "d", severity: "high", evidenceIds }) as Finding;
const hypothesis = (key: string, rank: number, supportingEvidence: string[], contradictingEvidence: string[] = []): Hypothesis =>
  ({
    key,
    rank,
    category: "missing_index",
    confidence: "high",
    statement: `Hypothesis ${key}`,
    supportingEvidence,
    contradictingEvidence,
    proposedBy: ["index_strategist"],
    uncertaintyNotes: "",
    verificationMethod: "benchmark",
  }) as Hypothesis;
const candidate = (key: string, addressesHypotheses: string[], status = "verified"): OptimizationCandidate =>
  ({
    key,
    id: `${key}-id`,
    kind: "create_index",
    ddl: [`CREATE INDEX ${key}`],
    querySql: null,
    addressesHypotheses,
    expectedBenefit: "Removes the sort",
    estimatedCost: { indexSizeEstimateBytes: 1024, writeOverhead: "low" },
    risks: [],
    round: 0,
    sqlSha256: "s",
    status,
    proposedBy: "optimization_engineer",
    rollbackSql: null,
  }) as OptimizationCandidate;
const verification = (candidateKey: string, checkIds: string[], extra: Partial<Verification> = {}): Verification =>
  ({
    candidateKey,
    candidateId: `${candidateKey}-id`,
    experimentId: "exp-1",
    round: 0,
    engineVerdict: "verified",
    verdict: "verified",
    auditorDowngraded: false,
    auditorStatus: "completed",
    auditorNotes: null,
    auditorPromptVersion: null,
    reasons: [],
    checks: [{ name: "correctness", status: "pass", detail: "same rows", evidence_ids: checkIds, evidenceIds: checkIds }],
    auditorConcerns: [],
    ...extra,
  }) as Verification;
const detail = (id: string, kind = "plan_node"): EvidenceDetail =>
  ({
    evidence: { id, kind, provenance: "measured", summary: `summary ${id}`, locator: "/x", data: {}, artifactSha256: null },
    artifact: null,
    citedByFindings: [],
    citedByHypotheses: [],
  }) as EvidenceDetail;

const E1 = "ev_000000000001";
const E2 = "ev_000000000002";
const E3 = "ev_000000000003";
const E4 = "ev_000000000004";
const E5 = "ev_000000000005";

describe("buildEvidenceGraph", () => {
  const input = {
    findings: [finding("f_1", [E1, E2]), finding("f_2", [E4])],
    hypotheses: [hypothesis("hy_1", 1, [E2, E3], [E4]), hypothesis("hy_2", 2, [E5])],
    candidates: [candidate("oc_1", ["hy_1"]), candidate("oc_2", ["hy_2"], "proposed")],
    verifications: [verification("oc_1", [E5])],
    evidence: new Map<string, EvidenceDetail | "error">([
      [E1, detail(E1)],
      [E2, "error"],
    ]),
  };
  const g = buildEvidenceGraph(input);
  const link = (from: string, to: string) => g.links.find((l) => l.from === from && l.to === to);

  test("every evidence ID any record cites is a node, resolved or not", () => {
    const ev = g.nodes.filter((n) => n.column === "evidence");
    expect(ev.map((n) => n.id).sort()).toEqual([E1, E2, E3, E4, E5].sort());
    expect(ev.find((n) => n.id === E1)?.state).toBe("resolved");
    expect(ev.find((n) => n.id === E2)?.state).toBe("error");
    expect(ev.find((n) => n.id === E3)?.state).toBe("pending");
  });

  test("recorded links come from stored references and name their source field", () => {
    expect(link(E1, "f_1")).toMatchObject({ kind: "cites", basis: "recorded", source: "finding.evidence_ids" });
    expect(link(E3, "hy_1")).toMatchObject({ kind: "supports", basis: "recorded", source: "hypothesis.supporting_evidence" });
    expect(link(E4, "hy_1")).toMatchObject({ kind: "contradicts", basis: "recorded", source: "hypothesis.contradicting_evidence" });
    expect(link("hy_1", "oc_1")).toMatchObject({ kind: "addresses", basis: "recorded", source: "candidate.addresses_hypotheses" });
    expect(link("oc_1", "vd_oc_1_0")).toMatchObject({ kind: "verified_by", basis: "recorded", source: "verification.candidate_key" });
    expect(link(E5, "vd_oc_1_0")).toMatchObject({ kind: "audit_cites", basis: "recorded", source: "audit check correctness" });
  });

  test("finding → hypothesis is never recorded; it is inferred from shared cited evidence and says which", () => {
    expect(link("f_1", "hy_1")).toMatchObject({ basis: "inferred", kind: "shares_evidence", via: [E2] });
    // A contradicting citation is not support: f_2 and hy_1 share only E4, which hy_1 contradicts.
    expect(link("f_2", "hy_1")).toBeUndefined();
    // No shared evidence, no link.
    expect(link("f_1", "hy_2")).toBeUndefined();
    expect(g.links.filter((l) => l.basis === "inferred").every((l) => l.kind === "shares_evidence")).toBe(true);
  });

  test("a candidate without a recorded verification has no verdict node", () => {
    expect(g.nodes.filter((n) => n.column === "verdict").map((n) => n.id)).toEqual(["vd_oc_1_0"]);
  });

  test("references to records that are not in the run are kept as missing, not dropped", () => {
    const g2 = buildEvidenceGraph({ ...input, candidates: [candidate("oc_9", ["hy_404"])], verifications: [] });
    expect(g2.missing).toContainEqual({ from: "oc_9", ref: "hy_404", source: "candidate.addresses_hypotheses" });
  });

  test("evidence is ordered by its first consumer so lines cross less", () => {
    const order = g.nodes.filter((n) => n.column === "evidence").map((n) => n.id);
    expect(order.indexOf(E1)).toBeLessThan(order.indexOf(E3));
    expect(order.indexOf(E4)).toBeLessThan(order.indexOf(E5));
  });
});

describe("pathOf", () => {
  const g = buildEvidenceGraph({
    findings: [finding("f_1", [E1]), finding("f_2", [E4])],
    hypotheses: [hypothesis("hy_1", 1, [E1]), hypothesis("hy_2", 2, [E4])],
    candidates: [candidate("oc_1", ["hy_1"]), candidate("oc_2", ["hy_2"])],
    verifications: [verification("oc_1", []), verification("oc_2", [])],
    evidence: new Map(),
  });

  test("the path of a candidate runs back to its evidence and on to its verdict, and nothing else", () => {
    const p = pathOf(g, "oc_1");
    expect([...p.nodes].sort()).toEqual([E1, "f_1", "hy_1", "oc_1", "vd_oc_1_0"].sort());
    expect(p.nodes.has("oc_2")).toBe(false);
    expect(p.nodes.has(E4)).toBe(false);
  });

  test("the path of an evidence item follows everything downstream of it", () => {
    const p = pathOf(g, E4);
    expect([...p.nodes].sort()).toEqual([E4, "f_2", "hy_2", "oc_2", "vd_oc_2_0"].sort());
  });

  test("an unknown node has an empty path", () => {
    expect(pathOf(g, "nope").nodes.size).toBe(0);
  });
});

describe("orderNodes", () => {
  // Default order crosses: f_1 cites E2 (second), f_2 cites E1 (first); hy_1 follows f_2.
  const g = buildEvidenceGraph({
    findings: [finding("f_1", [E2]), finding("f_2", [E1])],
    hypotheses: [hypothesis("hy_1", 1, [E1]), hypothesis("hy_2", 2, [E2])],
    candidates: [candidate("oc_1", ["hy_2"]), candidate("oc_2", ["hy_1"])],
    verifications: [verification("oc_1", [E3]), verification("oc_2", [])],
    evidence: new Map(),
  });

  test("reorders records within their columns only, keeping every record", () => {
    const ordered = orderNodes(g);
    expect(ordered.map((n) => n.id).sort()).toEqual(g.nodes.map((n) => n.id).sort());
    const columns = (ns: typeof ordered) => ns.map((n) => n.column);
    expect(new Set(columns(ordered))).toEqual(new Set(columns(g.nodes)));
    for (const n of ordered) expect(g.nodes.find((m) => m.id === n.id)).toBe(n);
  });

  test("never increases crossings, and removes them where an order without any exists", () => {
    expect(countCrossings(g, g.nodes)).toBeGreaterThan(0);
    expect(countCrossings(g, orderNodes(g))).toBe(0);
  });

  test("is deterministic", () => {
    expect(orderNodes(g).map((n) => n.id)).toEqual(orderNodes(g).map((n) => n.id));
  });
});

describe("explainingSelection", () => {
  test("starts at the verified verdict, the record that explains the recommendation", () => {
    const g = buildEvidenceGraph({
      findings: [finding("f_1", [E1])],
      hypotheses: [hypothesis("hy_1", 1, [E1])],
      candidates: [candidate("oc_1", ["hy_1"], "rejected"), candidate("oc_2", ["hy_1"])],
      verifications: [verification("oc_1", [], { verdict: "rejected", engineVerdict: "rejected" }), verification("oc_2", [])],
      evidence: new Map(),
    });
    expect(explainingSelection(g)).toBe("vd_oc_2_0");
  });

  test("without a verified verdict, falls back to a verdict, then the top hypothesis", () => {
    const base = { findings: [finding("f_1", [E1])], hypotheses: [hypothesis("hy_2", 2, [E1]), hypothesis("hy_1", 1, [E1])], evidence: new Map() };
    const rejected = buildEvidenceGraph({ ...base, candidates: [candidate("oc_1", ["hy_1"], "rejected")], verifications: [verification("oc_1", [], { verdict: "rejected" })] });
    expect(explainingSelection(rejected)).toBe("vd_oc_1_0");
    expect(explainingSelection(buildEvidenceGraph({ ...base, candidates: [], verifications: [] }))).toBe("hy_1");
    expect(explainingSelection(buildEvidenceGraph({ ...base, hypotheses: [], candidates: [], verifications: [] }))).toBe(E1);
  });
});

describe("linkClass", () => {
  test("contradicting evidence is its own class; inferred stays inferred", () => {
    const g = buildEvidenceGraph({
      findings: [finding("f_1", [E1])],
      hypotheses: [hypothesis("hy_1", 1, [E1], [E2])],
      candidates: [],
      verifications: [],
      evidence: new Map(),
    });
    const of = (from: string, to: string) => linkClass(g.links.find((l) => l.from === from && l.to === to)!);
    expect(of(E1, "f_1")).toBe("recorded");
    expect(of(E2, "hy_1")).toBe("contradicting");
    expect(of("f_1", "hy_1")).toBe("inferred");
  });
});
