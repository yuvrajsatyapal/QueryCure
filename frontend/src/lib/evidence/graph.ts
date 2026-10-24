import type { EvidenceDetail, Finding, Hypothesis, OptimizationCandidate, Verification } from "@/lib/api/types";
import type { AuditCheck, AuditConcern } from "@/lib/report/types";

/** The evidence relationship graph (UI_UX §3.18): Evidence → Finding → Hypothesis → Candidate →
 * Verdict. Links are either *recorded* (a stored reference, named by `source`) or *inferred* by
 * this client. The only inferred link is finding → hypothesis: the backend stores no such
 * reference, so it is drawn when both cite the same evidence as support, and names that evidence. */
export type Column = "evidence" | "finding" | "hypothesis" | "candidate" | "verdict";
export const COLUMNS: readonly Column[] = ["evidence", "finding", "hypothesis", "candidate", "verdict"];

export type EvidenceState = "resolved" | "pending" | "error";

export type GraphNode =
  | { column: "evidence"; id: string; state: EvidenceState; detail: EvidenceDetail | null }
  | { column: "finding"; id: string; finding: Finding }
  | { column: "hypothesis"; id: string; hypothesis: Hypothesis }
  | { column: "candidate"; id: string; candidate: OptimizationCandidate }
  | { column: "verdict"; id: string; verification: Verification; candidate: OptimizationCandidate | null };

export type LinkKind = "cites" | "supports" | "contradicts" | "addresses" | "verified_by" | "audit_cites" | "shares_evidence";

export interface GraphLink {
  id: string;
  from: string;
  to: string;
  kind: LinkKind;
  basis: "recorded" | "inferred";
  /** The stored field the link comes from, or how it was inferred. */
  source: string;
  /** Inferred links: the shared evidence IDs. */
  via?: string[];
}

export interface MissingRef {
  from: string;
  ref: string;
  source: string;
}

export interface EvidenceGraph {
  nodes: GraphNode[];
  links: GraphLink[];
  /** Stored references to a record this run does not return (kept visible, never dropped). */
  missing: MissingRef[];
}

const verdictId = (v: Verification) => `vd_${v.candidateKey}_${v.round}`;

function auditRefs(v: Verification): { ids: string[]; source: string }[] {
  const checks = (v.checks as unknown as AuditCheck[]).map((c) => ({ ids: c.evidenceIds ?? [], source: `audit check ${c.name}` }));
  const concerns = (v.auditorConcerns as unknown as AuditConcern[]).map((c) => ({ ids: c.evidenceIds ?? [], source: "auditor concern" }));
  return [...checks, ...concerns];
}

export function buildEvidenceGraph(input: {
  findings: Finding[];
  hypotheses: Hypothesis[];
  candidates: OptimizationCandidate[];
  verifications: Verification[];
  evidence: ReadonlyMap<string, EvidenceDetail | "error">;
}): EvidenceGraph {
  const links: GraphLink[] = [];
  const missing: MissingRef[] = [];
  const seen = new Set<string>();
  const link = (l: Omit<GraphLink, "id">) => {
    const id = `${l.from}->${l.to}:${l.kind}`;
    if (seen.has(id)) return;
    seen.add(id);
    links.push({ id, ...l });
  };

  // Evidence in order of first consumer (findings, then hypotheses, then verdicts).
  const evidenceOrder: string[] = [];
  const addEvidence = (id: string) => {
    if (!evidenceOrder.includes(id)) evidenceOrder.push(id);
  };

  const findings = input.findings;
  const hypotheses = [...input.hypotheses].sort((a, b) => a.rank - b.rank);
  const candidates = [...input.candidates].sort((a, b) => a.round - b.round || a.key.localeCompare(b.key));
  const hypothesisKeys = new Set(hypotheses.map((h) => h.key));
  const byCandidate = new Map(candidates.map((c) => [c.key, c]));

  for (const f of findings) {
    for (const ev of f.evidenceIds) {
      addEvidence(ev);
      link({ from: ev, to: f.key, kind: "cites", basis: "recorded", source: "finding.evidence_ids" });
    }
  }
  for (const h of hypotheses) {
    for (const ev of h.supportingEvidence) {
      addEvidence(ev);
      link({ from: ev, to: h.key, kind: "supports", basis: "recorded", source: "hypothesis.supporting_evidence" });
    }
    for (const ev of h.contradictingEvidence ?? []) {
      addEvidence(ev);
      link({ from: ev, to: h.key, kind: "contradicts", basis: "recorded", source: "hypothesis.contradicting_evidence" });
    }
  }
  for (const f of findings) {
    for (const h of hypotheses) {
      const via = f.evidenceIds.filter((ev) => h.supportingEvidence.includes(ev));
      if (via.length > 0) link({ from: f.key, to: h.key, kind: "shares_evidence", basis: "inferred", source: "shared supporting evidence", via });
    }
  }
  for (const c of candidates) {
    for (const hy of c.addressesHypotheses) {
      if (hypothesisKeys.has(hy)) link({ from: hy, to: c.key, kind: "addresses", basis: "recorded", source: "candidate.addresses_hypotheses" });
      else missing.push({ from: c.key, ref: hy, source: "candidate.addresses_hypotheses" });
    }
  }
  const verdictNodes: GraphNode[] = [];
  const verdictIds = new Set<string>();
  for (const v of input.verifications) {
    let id = verdictId(v);
    for (let n = 2; verdictIds.has(id); n++) id = `${verdictId(v)}_${n}`;
    verdictIds.add(id);
    const c = byCandidate.get(v.candidateKey) ?? null;
    verdictNodes.push({ column: "verdict", id, verification: v, candidate: c });
    if (c) link({ from: c.key, to: id, kind: "verified_by", basis: "recorded", source: "verification.candidate_key" });
    else missing.push({ from: id, ref: v.candidateKey, source: "verification.candidate_key" });
    for (const ref of auditRefs(v)) {
      for (const ev of ref.ids) {
        addEvidence(ev);
        link({ from: ev, to: id, kind: "audit_cites", basis: "recorded", source: ref.source });
      }
    }
  }

  const evidenceNodes: GraphNode[] = evidenceOrder.map((id) => {
    const d = input.evidence.get(id);
    return { column: "evidence", id, state: d === undefined ? "pending" : d === "error" ? "error" : "resolved", detail: d && d !== "error" ? d : null };
  });
  return {
    nodes: [
      ...evidenceNodes,
      ...findings.map((f): GraphNode => ({ column: "finding", id: f.key, finding: f })),
      ...hypotheses.map((h): GraphNode => ({ column: "hypothesis", id: h.key, hypothesis: h })),
      ...candidates.map((c): GraphNode => ({ column: "candidate", id: c.key, candidate: c })),
      ...verdictNodes,
    ],
    links,
    missing,
  };
}

/** Everything upstream of `id` (what it rests on) and downstream (what rests on it), not the
 * siblings of either: the chain a reader follows from evidence to verdict. */
export function pathOf(graph: EvidenceGraph, id: string): { nodes: Set<string>; links: Set<string> } {
  const nodes = new Set<string>();
  const used = new Set<string>();
  if (!graph.nodes.some((n) => n.id === id)) return { nodes, links: used };
  nodes.add(id);
  const walk = (start: string, forward: boolean) => {
    const queue = [start];
    const visited = new Set([start]);
    while (queue.length) {
      const at = queue.shift()!;
      for (const l of graph.links) {
        const [here, there] = forward ? [l.from, l.to] : [l.to, l.from];
        if (here !== at) continue;
        used.add(l.id);
        nodes.add(there);
        if (!visited.has(there)) {
          visited.add(there);
          queue.push(there);
        }
      }
    }
  };
  walk(id, true);
  walk(id, false);
  return { nodes, links: used };
}

/** How a link is classified for display: a recorded contradicting citation is kept apart from
 * recorded support, and an inferred link is never shown as recorded. */
export function linkClass(l: GraphLink): "recorded" | "inferred" | "contradicting" {
  if (l.basis === "inferred") return "inferred";
  return l.kind === "contradicts" ? "contradicting" : "recorded";
}

const colIndex = (n: GraphNode) => COLUMNS.indexOf(n.column);

/** Crossings between links of neighbouring columns for a given node order. Links that skip a
 * column are routed along lanes under the cards, so they are not counted. */
export function countCrossings(graph: EvidenceGraph, order: GraphNode[]): number {
  const at = new Map<string, { col: number; i: number }>();
  for (const c of COLUMNS) order.filter((n) => n.column === c).forEach((n, i) => at.set(n.id, { col: COLUMNS.indexOf(c), i }));
  const adjacent = graph.links
    .map((l) => ({ a: at.get(l.from), b: at.get(l.to) }))
    .filter((x): x is { a: { col: number; i: number }; b: { col: number; i: number } } => !!x.a && !!x.b && x.b.col - x.a.col === 1);
  let n = 0;
  for (let i = 0; i < adjacent.length; i++) {
    for (let j = i + 1; j < adjacent.length; j++) {
      const p = adjacent[i]!;
      const q = adjacent[j]!;
      if (p.a.col === q.a.col && (p.a.i - q.a.i) * (p.b.i - q.b.i) < 0) n++;
    }
  }
  return n;
}

/** The same records, reordered within each column by the barycentre of their linked records
 * (a few sweeps both ways), keeping whichever order crosses least. Only positions change: no
 * record or link is added, removed or merged. */
export function orderNodes(graph: EvidenceGraph): GraphNode[] {
  const columns = COLUMNS.map((c) => graph.nodes.filter((n) => n.column === c));
  const flat = () => columns.flat();
  const index = new Map<string, number>();
  const reindex = () => columns.forEach((col) => col.forEach((n, i) => index.set(n.id, i)));
  reindex();
  const col = new Map(graph.nodes.map((n) => [n.id, colIndex(n)]));
  let best = flat();
  let bestCrossings = countCrossings(graph, best);
  const sweep = (c: number, upstream: boolean) => {
    const key = new Map<string, number>();
    for (const n of columns[c]!) {
      const ends = graph.links
        .filter((l) => (upstream ? l.to === n.id && (col.get(l.from) ?? c) < c : l.from === n.id && (col.get(l.to) ?? c) > c))
        .map((l) => index.get(upstream ? l.from : l.to) ?? 0);
      key.set(n.id, ends.length ? ends.reduce((a, b) => a + b, 0) / ends.length : index.get(n.id)!);
    }
    columns[c]!.sort((a, b) => key.get(a.id)! - key.get(b.id)! || index.get(a.id)! - index.get(b.id)!);
    reindex();
  };
  for (let round = 0; round < 4 && bestCrossings > 0; round++) {
    for (let c = 1; c < COLUMNS.length; c++) sweep(c, true);
    for (let c = COLUMNS.length - 2; c >= 0; c--) sweep(c, false);
    const crossings = countCrossings(graph, flat());
    if (crossings < bestCrossings) {
      best = flat();
      bestCrossings = crossings;
    }
  }
  return best;
}

/** The record to select first: the verdict that verified a candidate (latest round), else any
 * verdict for a recorded candidate, else the top-ranked hypothesis, else the first record. */
export function explainingSelection(graph: EvidenceGraph): string | null {
  const verdicts = graph.nodes.filter((n): n is Extract<GraphNode, { column: "verdict" }> => n.column === "verdict" && n.candidate !== null);
  const latest = (vs: typeof verdicts) => [...vs].sort((a, b) => b.verification.round - a.verification.round)[0]?.id;
  return (
    latest(verdicts.filter((v) => v.verification.verdict === "verified")) ??
    latest(verdicts) ??
    graph.nodes.find((n) => n.column === "hypothesis")?.id ??
    graph.nodes[0]?.id ??
    null
  );
}
