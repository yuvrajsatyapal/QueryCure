/* Run-scoped palette results (UI_UX §3.15): the selected run's findings, hypotheses, candidates,
 * plan diffs and cited evidence, built only from data the page already holds. Pure, so what the
 * palette may claim (recorded statuses, no derived speed-ups) is unit-tested rather than assumed. */

import type { EvidenceDetail, Finding, Hypothesis, OptimizationCandidate } from "@/lib/api/types";
import { describeCandidate } from "@/lib/benchmark/candidate";
import { statusLabel } from "@/lib/benchmark/status";
import { agentLabel } from "@/lib/investigation/agents";

export const RUN_SCOPE_GROUPS = ["Findings", "Hypotheses", "Candidates", "Plan diffs", "Evidence"] as const;
export type RunScopeGroup = (typeof RUN_SCOPE_GROUPS)[number];

export type RunScopeTarget =
  | { kind: "finding"; key: string }
  | { kind: "hypothesis"; key: string }
  | { kind: "candidate"; key: string }
  | { kind: "plan-diff"; arm: string }
  | { kind: "evidence"; id: string };

/** `loaded`: details are cached; `not_loaded`: fetched when opened; `unavailable`: the fetch failed. */
export type EvidenceAvailability = "loaded" | "not_loaded" | "unavailable";

export interface RunScopeItem {
  id: string;
  runId: string;
  group: RunScopeGroup;
  label: string;
  detail?: string;
  keywords: string[];
  target: RunScopeTarget;
  availability?: EvidenceAvailability;
}

export interface RunScopeInput {
  runId: string;
  findings: Finding[] | undefined;
  hypotheses: Hypothesis[] | undefined;
  candidates: OptimizationCandidate[] | undefined;
  /** Evidence details already in the query cache, by ID ("error" when the fetch failed). */
  evidence: ReadonlyMap<string, EvidenceDetail | "error">;
  /** Arms with a captured plan in the run's latest round; null while that is not known. */
  planArms: readonly string[] | null;
}

const SEVERITY: Record<string, string> = { info: "Info", low: "Low severity", medium: "Medium severity", high: "High severity" };

export function buildRunScopeItems({ runId, findings, hypotheses, candidates, evidence, planArms }: RunScopeInput): RunScopeItem[] {
  const fs = findings ?? [];
  const hs = hypotheses ?? [];
  const cs = candidates ?? [];
  const byKey = new Map(cs.map((c) => [c.key, c]));
  const cited = [
    ...new Set([...fs.flatMap((f) => f.evidenceIds), ...hs.flatMap((h) => [...h.supportingEvidence, ...(h.contradictingEvidence ?? [])])]),
  ];
  return [
    ...fs.map<RunScopeItem>((f) => ({
      id: `finding-${f.key}`,
      runId,
      group: "Findings",
      label: f.title,
      detail: `${SEVERITY[f.severity] ?? f.severity} · ${agentLabel(f.agent)}`,
      keywords: [f.key, f.severity, f.agent, ...f.evidenceIds],
      target: { kind: "finding", key: f.key },
    })),
    ...hs.map<RunScopeItem>((h) => ({
      id: `hypothesis-${h.key}`,
      runId,
      group: "Hypotheses",
      label: h.statement,
      detail: `#${h.rank} · ${h.confidence} confidence · unverified`,
      keywords: [h.key, h.category, h.confidence, ...h.supportingEvidence, ...(h.contradictingEvidence ?? [])],
      target: { kind: "hypothesis", key: h.key },
    })),
    ...cs.map<RunScopeItem>((c) => ({
      id: `candidate-${c.key}`,
      runId,
      group: "Candidates",
      label: describeCandidate(c),
      detail: statusLabel(c.status),
      keywords: [c.key, c.kind, c.status, ...c.ddl],
      target: { kind: "candidate", key: c.key },
    })),
    ...(planArms ?? []).map<RunScopeItem>((arm) => {
      const c = byKey.get(arm);
      return {
        id: `plan-diff-${arm}`,
        runId,
        group: "Plan diffs",
        label: `Plan diff · baseline → ${arm}`,
        detail: c ? describeCandidate(c) : undefined,
        keywords: [arm, "plan", "diff", "explain", "compare"],
        target: { kind: "plan-diff", arm },
      };
    }),
    ...cited.map<RunScopeItem>((id) => {
      const known = evidence.get(id);
      const base = { id: `evidence-${id}`, runId, group: "Evidence" as const, target: { kind: "evidence" as const, id } };
      if (known === "error") return { ...base, label: id, detail: "Details unavailable", keywords: [id], availability: "unavailable" };
      if (!known) return { ...base, label: id, detail: "Details load when opened", keywords: [id], availability: "not_loaded" };
      const e = known.evidence;
      return { ...base, label: e.summary, detail: `${id} · ${e.kind} · ${e.provenance}`, keywords: [id, e.kind, e.provenance], availability: "loaded" };
    }),
  ];
}

export interface RunScopeSection<T extends RunScopeItem = RunScopeItem> {
  group: RunScopeGroup;
  items: T[];
  /** Matches left out by the cap; the palette says how many so nothing disappears silently. */
  hidden: number;
}

export function groupRunScopeItems<T extends RunScopeItem>(items: readonly T[], cap: number): RunScopeSection<T>[] {
  return RUN_SCOPE_GROUPS.flatMap((group) => {
    const all = items.filter((i) => i.group === group);
    return all.length === 0 ? [] : [{ group, items: all.slice(0, cap), hidden: Math.max(all.length - cap, 0) }];
  });
}
