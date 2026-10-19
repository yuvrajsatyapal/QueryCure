import type { EvidenceDetail, Finding, Hypothesis } from "@/lib/api/types";
import type { Span, TraceRow } from "@/lib/events/trace";

/* Links between the trace, claims (findings, hypotheses), evidence and plan nodes (UI_UX §3.6).
 * Pure functions over recorded data: a link exists only when an event or an evidence record
 * states it, and every way a link can fail is returned as a named status, never guessed. */

type Payload = Record<string, unknown>;
const CLAIM_EVENTS = new Set(["finding.created", "hypothesis.created"]);
const EVIDENCE_FIELDS = ["evidenceIds", "supportingEvidence", "contradictingEvidence"] as const;

const strings = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);

function walk(root: Span, visit: (span: Span, parents: Span[]) => void, parents: Span[] = []): void {
  for (const child of root.children) {
    visit(child, parents);
    walk(child, visit, [...parents, child]);
  }
}

export function findSpan(root: Span, id: string): Span | undefined {
  if (root.id === id) return root;
  let found: Span | undefined;
  walk(root, (s) => {
    if (!found && s.id === id) found = s;
  });
  return found;
}

/** IDs of the rows enclosing `id`, outermost first; the run row is not included. */
export function ancestorIds(root: Span, id: string): string[] {
  let result: string[] = [];
  walk(root, (s, parents) => {
    if (s.id === id) result = parents.map((p) => p.id);
  });
  return result;
}

/** Claim key (fd_…, hy_…) → IDs of the trace rows whose creation event carries that key. */
export function indexClaimSpans(root: Span): Map<string, string[]> {
  const index = new Map<string, string[]>();
  walk(root, (s) => {
    const event = s.kind === "event" ? s.events[0] : undefined;
    if (!event || !CLAIM_EVENTS.has(event.type)) return;
    const key = (event.payload as Payload).key;
    if (typeof key !== "string" || !key) return;
    index.set(key, [...(index.get(key) ?? []), s.id]);
  });
  return index;
}

export type StepMatch = { status: "found"; spanId: string; matches: number } | { status: "missing" };

export function stepForClaim(index: Map<string, string[]>, key: string): StepMatch {
  const ids = index.get(key);
  if (!ids?.length) return { status: "missing" };
  return { status: "found", spanId: ids[0]!, matches: ids.length };
}

/** Evidence the row's own events recorded (tool results, claim citations), in order, unique. */
export function evidenceIdsOfSpan(span: Span): string[] {
  const ids = [...span.evidenceIds];
  for (const event of span.events) {
    const p = event.payload as Payload;
    for (const field of EVIDENCE_FIELDS) ids.push(...strings(p[field]));
  }
  return [...new Set(ids)];
}

export type PlanTarget =
  | { status: "found"; planSha: string; nodeId: number }
  | { status: "not_plan_node" }
  | { status: "plan_unavailable" }
  | { status: "node_unavailable"; planSha: string };

interface PlanRef {
  sha256: string;
  plan: { nodes: { id: number }[] };
}

/** Where plan-node evidence points, checked against the plans this run actually has. */
export function planTargetOfEvidence(detail: EvidenceDetail, plans: PlanRef[]): PlanTarget {
  if (detail.evidence.kind !== "plan_node") return { status: "not_plan_node" };
  const sha = detail.artifact?.sha256 ?? detail.evidence.artifactSha256 ?? null;
  const plan = plans.find((p) => p.sha256 === sha);
  if (!plan) return { status: "plan_unavailable" };
  const nodeId = (detail.evidence.data as Payload).nodeId;
  if (typeof nodeId !== "number" || !plan.plan.nodes.some((n) => n.id === nodeId)) {
    return { status: "node_unavailable", planSha: plan.sha256 };
  }
  return { status: "found", planSha: plan.sha256, nodeId };
}

/** Every evidence ID cited by a finding or hypothesis, in order, unique. */
export function citedEvidenceIds(findings: Finding[], hypotheses: Hypothesis[]): string[] {
  return [
    ...new Set([
      ...findings.flatMap((f) => f.evidenceIds),
      ...hypotheses.flatMap((h) => [...h.supportingEvidence, ...(h.contradictingEvidence ?? [])]),
    ]),
  ];
}

export interface Citation {
  findings: string[];
  hypotheses: string[];
}

/** Findings and hypotheses per plan node of one plan. `resolved` maps evidence ID → detail,
 * or "error" when it failed to load; absent IDs are still pending. */
export function citationsByNode(
  findings: Finding[],
  hypotheses: Hypothesis[],
  resolved: ReadonlyMap<string, EvidenceDetail | "error">,
  planSha: string,
): { byNode: Map<number, Citation>; pending: number; failed: number } {
  const byNode = new Map<number, Citation>();
  const nodeOf = (id: string): number | null => {
    const d = resolved.get(id);
    if (!d || d === "error" || d.evidence.kind !== "plan_node") return null;
    if ((d.artifact?.sha256 ?? d.evidence.artifactSha256) !== planSha) return null;
    const nodeId = (d.evidence.data as Payload).nodeId;
    return typeof nodeId === "number" ? nodeId : null;
  };
  const add = (ids: string[], key: string, field: keyof Citation) => {
    for (const id of ids) {
      const node = nodeOf(id);
      if (node === null) continue;
      const entry = byNode.get(node) ?? { findings: [], hypotheses: [] };
      if (!entry[field].includes(key)) entry[field].push(key);
      byNode.set(node, entry);
    }
  };
  for (const f of findings) add(f.evidenceIds, f.key, "findings");
  for (const h of hypotheses) add([...h.supportingEvidence, ...(h.contradictingEvidence ?? [])], h.key, "hypotheses");
  const all = citedEvidenceIds(findings, hypotheses);
  return {
    byNode,
    pending: all.filter((id) => !resolved.has(id)).length,
    failed: all.filter((id) => resolved.get(id) === "error").length,
  };
}

/** Visible tree rows including the run itself at depth 0. */
export function traceRows(root: Span, collapsed: ReadonlySet<string>): TraceRow[] {
  const rows: TraceRow[] = [{ span: root, depth: 0 }];
  const visit = (s: Span, depth: number) => {
    rows.push({ span: s, depth });
    if (!collapsed.has(s.id)) for (const c of s.children) visit(c, depth + 1);
  };
  for (const c of root.children) visit(c, 1);
  return rows;
}

export type TreeAction = { select: string } | { expand: string } | { collapse: string };

/** WAI-ARIA tree keys over the visible rows (UI_UX §3.6). The run row is not collapsible. */
export function treeKey(rows: TraceRow[], current: string, key: string, collapsed: ReadonlySet<string>): TreeAction | null {
  const i = rows.findIndex((r) => r.span.id === current);
  if (i < 0) return rows[0] ? { select: rows[0].span.id } : null;
  const row = rows[i]!;
  const hasChildren = row.depth > 0 && row.span.children.length > 0;
  switch (key) {
    case "ArrowDown":
      return rows[i + 1] ? { select: rows[i + 1]!.span.id } : null;
    case "ArrowUp":
      return i > 0 ? { select: rows[i - 1]!.span.id } : null;
    case "Home":
      return { select: rows[0]!.span.id };
    case "End":
      return { select: rows.at(-1)!.span.id };
    case "ArrowRight":
      if (row.depth === 0) return rows[1] ? { select: rows[1].span.id } : null;
      if (!hasChildren) return null;
      return collapsed.has(row.span.id) ? { expand: row.span.id } : { select: row.span.children[0]!.id };
    case "ArrowLeft": {
      if (hasChildren && !collapsed.has(row.span.id)) return { collapse: row.span.id };
      for (let j = i - 1; j >= 0; j -= 1) if (rows[j]!.depth < row.depth) return { select: rows[j]!.span.id };
      return null;
    }
    default:
      return null;
  }
}
