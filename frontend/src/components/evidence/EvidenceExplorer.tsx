"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import type { EvidenceDetail, Finding, Hypothesis, OptimizationCandidate, Verification } from "@/lib/api/types";
import { BADGE_STATUS, classifyRecommendation } from "@/lib/benchmark/analysis";
import { candidateKindLabel, describeCandidate } from "@/lib/benchmark/candidate";
import { COLUMNS, buildEvidenceGraph, explainingSelection, linkClass, orderNodes, pathOf, type Column, type GraphLink, type GraphNode } from "@/lib/evidence/graph";
import type { AuditCheck, AuditConcern } from "@/lib/report/types";
import { VerdictBadge } from "@/components/tournament/VerdictBadge";
import { Icon } from "@/components/ui/Icon";

const COLUMN_LABEL: Record<Column, string> = { evidence: "Evidence", finding: "Finding", hypothesis: "Hypothesis", candidate: "Candidate", verdict: "Verdict" };
export const PROVENANCE_TEXT: Record<string, string> = {
  measured: "measured by this run (live EXPLAIN, catalog read or sandbox timing)",
  imported: "taken from what was uploaded (plan or DDL), not measured by QueryCure",
  prerecorded: "a demo recording, not measured in this run",
  derived: "computed by QueryCure's deterministic code from other recorded data",
};
// How a link reads from each end: `out` on the record it starts at, `in` on the one it ends at.
const LINK_TEXT: Record<GraphLink["kind"], { out: string; in: string }> = {
  cites: { out: "cited by finding", in: "cites" },
  supports: { out: "supports", in: "supported by" },
  contradicts: { out: "contradicts", in: "contradicted by" },
  addresses: { out: "addressed by", in: "addresses" },
  verified_by: { out: "verdict", in: "for candidate" },
  audit_cites: { out: "cited by the auditor in", in: "auditor cites" },
  shares_evidence: { out: "inferred: shares evidence with", in: "inferred: shares evidence with" },
};
// The relationship as one phrase, read from source to target.
const RELATION: Record<GraphLink["kind"], string> = {
  cites: "finding cites this evidence",
  supports: "evidence supports the hypothesis",
  contradicts: "evidence contradicts the hypothesis",
  addresses: "candidate addresses the hypothesis",
  verified_by: "verdict recorded for the candidate",
  audit_cites: "Benchmark Auditor cites this evidence",
  shares_evidence: "finding and hypothesis cite the same supporting evidence",
};
const CLASS_TEXT = { recorded: "recorded", inferred: "inferred", contradicting: "recorded · contradicting" } as const;
// Below this width of the panel itself the columns stack and no lines are drawn.
const GRAPH_MIN_PX = 880;
// Descriptions longer than this get a "Show more" control in the stacked layout.
const LONG_BODY = 110;

const short = (id: string) => (id.length > 11 ? `${id.slice(0, 9)}…` : id);

function verdictOf(n: Extract<GraphNode, { column: "verdict" }>) {
  return n.candidate ? classifyRecommendation({ candidate: n.candidate, audit: n.verification }) : null;
}

/** The accessible name parts (full ID first, as before) and what the card shows: a readable type,
 * the description, and a provenance or status tag. */
function describe(n: GraphNode): { eyebrow: string; body: string; type: string; tag?: string; idText: string } {
  switch (n.column) {
    case "evidence": {
      if (n.state === "pending") return { eyebrow: `${n.id} · loading`, body: "Resolving the evidence record…", type: "loading", idText: n.id };
      if (n.state === "error") return { eyebrow: `${n.id} · not loaded`, body: "This evidence record could not be loaded.", type: "not loaded", idText: n.id };
      const e = n.detail!.evidence;
      return { eyebrow: `${n.id} · ${e.kind}`, body: e.summary, type: e.kind.replaceAll("_", " "), tag: e.provenance, idText: n.id };
    }
    case "finding":
      return { eyebrow: `${n.id} · ${n.finding.severity}`, body: n.finding.title, type: `${n.finding.severity} severity`, tag: "observed", idText: n.id };
    case "hypothesis":
      return {
        eyebrow: `${n.id} · rank ${n.hypothesis.rank} · ${n.hypothesis.confidence}`,
        body: n.hypothesis.statement,
        type: `rank ${n.hypothesis.rank} · ${n.hypothesis.confidence} confidence`,
        tag: "unverified",
        idText: n.id,
      };
    case "candidate":
      return { eyebrow: `${n.id} · ${candidateKindLabel(n.candidate.kind)}`, body: describeCandidate(n.candidate), type: candidateKindLabel(n.candidate.kind), tag: n.candidate.status, idText: n.id };
    case "verdict": {
      const rec = verdictOf(n);
      return {
        eyebrow: `${n.verification.candidateKey} · round ${n.verification.round + 1}`,
        body: rec?.label ?? n.verification.verdict,
        type: `round ${n.verification.round + 1}`,
        idText: n.verification.candidateKey,
      };
    }
  }
}

/** Copies a full ID; the short form is what the card shows. */
function CopyId({ id, onCopied }: { id: string; onCopied: (id: string) => void }) {
  return (
    <button
      type="button"
      aria-label={`Copy ID ${id}`}
      title={`${id} (copy)`}
      onClick={() => {
        void navigator.clipboard?.writeText(id).then(
          () => onCopied(id),
          () => undefined,
        );
      }}
      className="grid size-6 shrink-0 place-items-center rounded text-muted hover:bg-hover hover:text-ink pointer-coarse:size-10"
    >
      <Icon name="copy" size={12} />
    </button>
  );
}

function Card({
  node,
  selected,
  onPath,
  dim,
  focusable,
  stacked,
  onSelect,
  onCopied,
}: {
  node: GraphNode;
  selected: boolean;
  onPath: boolean;
  /** Not on the selected path: drawn quieter, still selectable. */
  dim: boolean;
  focusable: boolean;
  stacked: boolean;
  onSelect: (id: string) => void;
  onCopied: (id: string) => void;
}) {
  const d = describe(node);
  const [open, setOpen] = useState(false);
  const hypothesis = node.column === "hypothesis";
  const verdict = node.column === "verdict" ? verdictOf(node) : null;
  const long = stacked && !verdict && d.body.length > LONG_BODY;
  const bodyId = `ev-body-${node.id}`;
  return (
    <div
      data-ev-card={node.id}
      className={`relative z-10 flex min-w-0 flex-col rounded-lg border bg-surface ${hypothesis ? "border-dashed" : ""} ${
        selected ? "border-accent shadow-[0_0_0_1px_var(--accent)]" : onPath ? "border-accent/60" : "border-border hover:border-border-strong"
      } ${node.column === "evidence" && node.state === "error" ? "border-rejected/50" : ""} ${dim ? "opacity-55 hover:opacity-100 focus-within:opacity-100" : ""}`}
    >
      <button
        type="button"
        data-ev-node={node.id}
        tabIndex={focusable ? 0 : -1}
        aria-pressed={selected}
        aria-label={`${COLUMN_LABEL[node.column]} ${d.eyebrow}: ${d.body}${onPath && !selected ? " (on the selected path)" : ""}${dim ? " (not on the selected path)" : ""}`}
        title={`${d.eyebrow}\n${d.body}`}
        onClick={() => onSelect(node.id)}
        className="flex w-full min-w-0 flex-col gap-1 rounded-t-lg px-2.5 pt-2 pb-1 text-left outline-none focus-visible:ring-2 focus-visible:ring-accent pointer-coarse:pt-3"
      >
        <span className="flex min-w-0 flex-wrap items-start gap-x-1.5 gap-y-0.5 text-[11px] leading-4 text-muted">
          <span className="min-w-0 break-words">{d.type}</span>
          {d.tag ? <span className="ml-auto shrink-0 rounded-sm border border-border px-1 font-mono">{d.tag}</span> : null}
        </span>
        {verdict ? (
          <span>
            <VerdictBadge status={BADGE_STATUS[verdict.kind]} />
          </span>
        ) : (
          <span id={bodyId} className={`text-[13px] leading-[18px] break-words text-ink ${stacked ? (long && !open ? "line-clamp-3" : "") : "line-clamp-3"}`}>
            {d.body}
          </span>
        )}
      </button>
      <span className="flex min-w-0 items-center gap-1 px-2.5 pb-1.5">
        <span className="min-w-0 truncate font-mono text-[11px] text-muted" title={d.idText}>
          {stacked ? d.idText : short(d.idText)}
        </span>
        <CopyId id={d.idText} onCopied={onCopied} />
        {long ? (
          <button
            type="button"
            aria-expanded={open}
            aria-controls={bodyId}
            onClick={() => setOpen((v) => !v)}
            className="ml-auto shrink-0 rounded px-1.5 text-xs text-link hover:underline pointer-coarse:min-h-10"
          >
            {open ? "Show less" : "Show more"}
          </button>
        ) : null}
      </span>
    </div>
  );
}

type Geometry = Map<string, { left: number; right: number; y: number; bottom: number; col: number }>;
const LANE = { gap: 8, pad: 14, gutter: 14, r: 6 };

/** Links that skip a column would pass behind the cards between and look as if they ended there,
 * so they run down the gutter, along a lane under every card (one lane per target), and up the
 * gutter in front of the target. */
function lanePath(a: { right: number; y: number }, b: { left: number; y: number }, lane: number): string {
  const { gutter: g, r } = LANE;
  const x1 = a.right + g;
  const x2 = b.left - g;
  return [
    `M${a.right} ${a.y}`,
    `L${x1 - r} ${a.y} Q${x1} ${a.y} ${x1} ${a.y + r}`,
    `L${x1} ${lane - r} Q${x1} ${lane} ${x1 + r} ${lane}`,
    `L${x2 - r} ${lane} Q${x2} ${lane} ${x2} ${lane - r}`,
    `L${x2} ${b.y + r} Q${x2} ${b.y} ${x2 + r} ${b.y}`,
    `L${b.left} ${b.y}`,
  ].join(" ");
}

/** Lane offsets below the cards, one per target of a column-skipping link. */
function lanesOf(links: GraphLink[], geometry: Geometry): Map<string, number> {
  const lanes = new Map<string, number>();
  for (const l of links) {
    const a = geometry.get(l.from);
    const b = geometry.get(l.to);
    if (a && b && b.col - a.col > 1 && !lanes.has(l.to)) lanes.set(l.to, lanes.size);
  }
  return lanes;
}

function linkColor(l: GraphLink, strong: boolean): string {
  const c = linkClass(l);
  return c === "contradicting" ? "var(--rejected)" : c === "inferred" ? "var(--hypothesis)" : strong ? "var(--accent)" : "var(--border-strong)";
}

function Lines({
  links,
  geometry,
  path,
  quiet,
  hot,
  width,
  height,
  onHover,
}: {
  links: GraphLink[];
  geometry: Geometry;
  path: Set<string>;
  /** Path mode: links off the path are drawn faint. */
  quiet: boolean;
  /** A link being inspected: drawn strongest, the rest recede. */
  hot: string | null;
  width: number;
  height: number;
  onHover: (link: GraphLink | null, at?: { x: number; y: number }) => void;
}) {
  const lanes = lanesOf(links, geometry);
  const floor = Math.max(0, ...[...geometry.values()].map((g) => g.bottom)) + LANE.pad;
  const shapes = links.flatMap((l) => {
    const a = geometry.get(l.from);
    const b = geometry.get(l.to);
    if (!a || !b) return [];
    const mid = (a.right + b.left) / 2;
    const d = b.col - a.col > 1 ? lanePath(a, b, floor + (lanes.get(l.to) ?? 0) * LANE.gap) : `M${a.right} ${a.y} C ${mid} ${a.y}, ${mid} ${b.y}, ${b.left} ${b.y}`;
    return [{ l, d, end: b }];
  });
  // Faint links first, so highlighted ones are drawn on top.
  const weight = (l: GraphLink) => (l.id === hot ? 3 : path.has(l.id) ? 2 : 1);
  shapes.sort((p, q) => weight(p.l) - weight(q.l));
  return (
    <svg aria-hidden="true" width={width} height={height} className="pointer-events-none absolute inset-0 z-0 overflow-visible">
      {shapes.map(({ l, d, end }) => {
        const on = path.has(l.id);
        const isHot = l.id === hot;
        const faded = hot !== null ? !isHot : quiet && !on;
        const color = linkColor(l, on || isHot);
        const opacity = faded ? 0.22 : on || isHot || linkClass(l) === "contradicting" ? 1 : 0.8;
        return (
          <g key={l.id}>
            <path
              d={d}
              fill="none"
              stroke={color}
              strokeWidth={isHot ? 2.5 : on ? 1.75 : 1.25}
              strokeDasharray={l.basis === "inferred" ? "2 4" : undefined}
              strokeOpacity={opacity}
            />
            {/* Where the link ends: a dot at the target's edge, so it never seems to stop behind a card. */}
            <circle cx={end.left - 2.5} cy={end.y} r={isHot || on ? 2.75 : 2} fill={color} fillOpacity={opacity} />
            {/* A wider invisible stroke so the link is easy to point at. */}
            <path
              d={d}
              fill="none"
              stroke="transparent"
              strokeWidth={10}
              style={{ pointerEvents: "stroke", cursor: "help" }}
              onMouseMove={(e) => {
                const box = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
                onHover(l, { x: e.clientX - box.left, y: e.clientY - box.top });
              }}
              onMouseLeave={() => onHover(null)}
            />
          </g>
        );
      })}
    </svg>
  );
}

function Legend() {
  return (
    <ul aria-label="Link legend" className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
      <li className="flex items-center gap-1.5">
        <svg aria-hidden="true" width="20" height="6">
          <path d="M0 3 H20" stroke="var(--accent)" strokeWidth="1.75" />
        </svg>
        Recorded reference
      </li>
      <li className="flex items-center gap-1.5">
        <svg aria-hidden="true" width="20" height="6">
          <path d="M0 3 H20" stroke="var(--rejected)" strokeWidth="1.5" />
        </svg>
        Recorded, contradicts
      </li>
      <li className="flex items-center gap-1.5">
        <svg aria-hidden="true" width="20" height="6">
          <path d="M0 3 H20" stroke="var(--hypothesis)" strokeWidth="1.5" strokeDasharray="2 4" />
        </svg>
        Inferred by QueryCure (shared evidence, not stored)
      </li>
      <li className="flex items-center gap-1.5">
        <svg aria-hidden="true" width="20" height="6">
          <path d="M0 3 H20" stroke="var(--border-strong)" strokeWidth="1.25" strokeOpacity="0.35" />
        </svg>
        Faint: not on the selected path (highlighting is not stronger evidence)
      </li>
    </ul>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </>
  );
}

const nodeName = (n: GraphNode | undefined, id: string) => (n ? `${COLUMN_LABEL[n.column].toLowerCase()} ${id}` : `${id} (not in this run)`);

/** One link in words: source, target, relationship, recorded field or inference basis, class. */
function LinkDetails({ l, byId }: { l: GraphLink; byId: Map<string, GraphNode> }) {
  return (
    <>
      <span className="block">
        {nodeName(byId.get(l.from), l.from)} → {nodeName(byId.get(l.to), l.to)}
      </span>
      <span className="block text-muted">{RELATION[l.kind]}</span>
      <span className="block text-muted">
        {l.basis === "inferred" ? `inferred from shared supporting evidence ${l.via?.join(", ")}` : `recorded field: ${l.source}`}
      </span>
    </>
  );
}

function LinkList({
  node,
  links,
  byId,
  onSelect,
  onInspect,
}: {
  node: GraphNode;
  links: GraphLink[];
  byId: Map<string, GraphNode>;
  onSelect: (id: string) => void;
  onInspect: (id: string | null) => void;
}) {
  const mine = links.filter((l) => l.from === node.id || l.to === node.id);
  if (mine.length === 0) return <p className="text-xs text-muted">No links to other records in this run.</p>;
  return (
    <ul className="flex flex-col gap-1.5 text-xs">
      {mine.map((l) => {
        const other = l.from === node.id ? l.to : l.from;
        const target = byId.get(other);
        const c = linkClass(l);
        return (
          <li
            key={l.id}
            onMouseEnter={() => onInspect(l.id)}
            onMouseLeave={() => onInspect(null)}
            onFocus={() => onInspect(l.id)}
            onBlur={() => onInspect(null)}
            className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded px-1 -mx-1 hover:bg-hover"
          >
            <span
              className={`rounded-sm border px-1 font-mono text-[11px] ${
                c === "inferred" ? "border-dashed border-hypothesis text-hypothesis" : c === "contradicting" ? "border-rejected/60 text-rejected" : "border-border text-muted"
              }`}
            >
              {l.basis}
            </span>
            {c === "contradicting" ? <span className="text-rejected">contradicting</span> : null}
            <span className="text-muted">{l.from === node.id ? LINK_TEXT[l.kind].out : LINK_TEXT[l.kind].in}</span>
            <button
              type="button"
              onClick={() => onSelect(other)}
              aria-label={`Open ${target ? COLUMN_LABEL[target.column].toLowerCase() : "record"} ${other}; link: ${l.from} to ${l.to}, ${RELATION[l.kind]}, ${CLASS_TEXT[c]}, ${
                l.basis === "inferred" ? `inferred from shared supporting evidence ${l.via?.join(", ")}` : `recorded field ${l.source}`
              }`}
              className="font-mono text-link hover:underline disabled:text-muted disabled:no-underline"
              disabled={!target}
            >
              {other}
            </button>
            <span className="w-full font-mono text-[11px] text-muted">{l.basis === "inferred" ? `via ${l.via?.join(", ")}` : `from ${l.source}`}</span>
          </li>
        );
      })}
    </ul>
  );
}

function Record({
  node,
  graph,
  byId,
  onSelect,
  onInspect,
  actions,
}: {
  node: GraphNode;
  graph: ReturnType<typeof buildEvidenceGraph>;
  byId: Map<string, GraphNode>;
  onSelect: (id: string) => void;
  onInspect: (id: string | null) => void;
  actions: React.ReactNode;
}) {
  return (
    <aside aria-label="Selected record" className="flex min-w-0 flex-col gap-3 rounded-lg border border-border bg-surface-2 p-4">
      <div className="flex flex-col gap-0.5">
        <span className="qc-eyebrow">{COLUMN_LABEL[node.column]} record</span>
        <span className="font-mono text-sm font-medium break-all">{node.id}</span>
      </div>
      {node.column === "evidence" ? (
        node.detail ? (
          <>
            <p className="text-sm">{node.detail.evidence.summary}</p>
            <dl className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
              <Field label="Kind">
                <span className="font-mono">{node.detail.evidence.kind}</span>
              </Field>
              <Field label="Provenance">
                <span className="font-mono">{node.detail.evidence.provenance}</span>
                <span className="block text-muted">{PROVENANCE_TEXT[node.detail.evidence.provenance] ?? "not described"}</span>
              </Field>
              <Field label="Locator">
                <span className="font-mono">{node.detail.evidence.locator || "—"}</span>
              </Field>
              <Field label="Artifact">
                {node.detail.artifact ?? node.detail.evidence.artifactSha256 ? (
                  <span className="font-mono" title={node.detail.artifact?.sha256 ?? node.detail.evidence.artifactSha256 ?? undefined}>
                    {node.detail.artifact?.kind ? `${node.detail.artifact.kind} · ` : ""}
                    {(node.detail.artifact?.sha256 ?? node.detail.evidence.artifactSha256 ?? "").slice(0, 12)}…
                  </span>
                ) : (
                  <span className="text-muted">none recorded</span>
                )}
              </Field>
              {Object.entries(node.detail.evidence.data).map(([k, v]) => (
                <Field key={k} label={k}>
                  <span className="font-mono">{v === null ? "null" : String(v)}</span>
                </Field>
              ))}
            </dl>
            <p className="text-xs text-muted">
              Cited by (recorded):{" "}
              {[...node.detail.citedByFindings, ...node.detail.citedByHypotheses].length
                ? [...node.detail.citedByFindings, ...node.detail.citedByHypotheses].join(" · ")
                : "no finding or hypothesis"}
            </p>
          </>
        ) : (
          <p className="text-sm text-muted">{node.state === "pending" ? "Resolving the evidence record…" : "The evidence record could not be loaded. The ID stays listed because a record cites it."}</p>
        )
      ) : node.column === "finding" ? (
        <>
          <p className="text-sm font-medium">{node.finding.title}</p>
          <p className="text-sm text-muted">{node.finding.detail}</p>
          <p className="text-xs text-muted">
            {node.finding.agent.replaceAll("_", " ")} · severity {node.finding.severity}
          </p>
        </>
      ) : node.column === "hypothesis" ? (
        <>
          <p className="text-sm">{node.hypothesis.statement}</p>
          <p className="text-xs text-muted">
            Rank {node.hypothesis.rank} · {node.hypothesis.category.replaceAll("_", " ")} · confidence {node.hypothesis.confidence} · unverified · checked by{" "}
            {node.hypothesis.verificationMethod.replaceAll("_", " ")}
          </p>
          {node.hypothesis.uncertaintyNotes ? <p className="text-xs text-muted">Uncertainty: {node.hypothesis.uncertaintyNotes}</p> : null}
        </>
      ) : node.column === "candidate" ? (
        <>
          <p className="text-sm font-medium">{describeCandidate(node.candidate)}</p>
          <pre className="overflow-x-auto rounded-md bg-surface p-2 font-mono text-xs whitespace-pre-wrap">{node.candidate.ddl.join(";\n") || node.candidate.querySql}</pre>
          <div className="flex flex-wrap items-center gap-2">
            <VerdictBadge status={node.candidate.status} />
          </div>
          <dl className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
            <Field label="Predicted">
              {node.candidate.expectedBenefit} <span className="text-muted">(the agent&apos;s expectation, not measured)</span>
            </Field>
            <Field label="Est. index size">
              {node.candidate.estimatedCost.indexSizeEstimateBytes === null || node.candidate.estimatedCost.indexSizeEstimateBytes === undefined
                ? "—"
                : `${Math.round(node.candidate.estimatedCost.indexSizeEstimateBytes / 1024)} kB`}{" "}
              <span className="text-muted">predicted</span>
            </Field>
            <Field label="Write overhead">
              {node.candidate.estimatedCost.writeOverhead ?? "unknown"} <span className="text-muted">predicted</span>
            </Field>
          </dl>
        </>
      ) : (
        <VerdictRecord node={node} />
      )}
      <div className="flex flex-col gap-1.5">
        <span className="qc-eyebrow">Links</span>
        <LinkList node={node} links={graph.links} byId={byId} onSelect={onSelect} onInspect={onInspect} />
      </div>
      {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
    </aside>
  );
}

const CHECK_ICON: Record<string, { icon: string; tone: string; word: string }> = {
  pass: { icon: "✓", tone: "text-verified", word: "pass" },
  warn: { icon: "!", tone: "text-inconclusive", word: "warning" },
  fail: { icon: "✕", tone: "text-rejected", word: "fail" },
  skip: { icon: "–", tone: "text-muted", word: "skipped" },
};

function VerdictRecord({ node }: { node: Extract<GraphNode, { column: "verdict" }> }) {
  const v = node.verification;
  const rec = verdictOf(node);
  const checks = v.checks as unknown as AuditCheck[];
  const concerns = v.auditorConcerns as unknown as AuditConcern[];
  return (
    <>
      {rec ? (
        <span className="self-start">
          <VerdictBadge status={BADGE_STATUS[rec.kind]} />
        </span>
      ) : null}
      <p className="text-xs text-muted">
        Engine verdict <span className="font-mono">{v.engineVerdict}</span> · final <span className="font-mono">{v.verdict}</span> · auditor{" "}
        {v.auditorStatus === "deterministic_only" ? "deterministic checks only" : v.auditorStatus}
        {v.auditorDowngraded ? " · downgraded by the auditor" : ""}. The auditor can only downgrade.
      </p>
      <ul aria-label="Audit checks" className="flex flex-col gap-1 text-xs">
        {checks.map((c) => {
          const s = CHECK_ICON[c.status] ?? CHECK_ICON.skip!;
          return (
            <li key={c.name} className="grid grid-cols-[1rem_minmax(0,1fr)] gap-x-1.5">
              <span aria-hidden="true" className={s.tone}>
                {s.icon}
              </span>
              <span>
                <span className="font-mono">{c.name}</span> <span className={s.tone}>{s.word}</span>
                <span className="block text-muted">{c.detail}</span>
              </span>
            </li>
          );
        })}
      </ul>
      {concerns.length ? (
        <ul aria-label="Auditor concerns" className="flex flex-col gap-1 text-xs">
          {concerns.map((c, i) => (
            <li key={i}>
              <span className="font-mono">{c.severity}</span> · {c.text}
            </li>
          ))}
        </ul>
      ) : null}
    </>
  );
}

/** Evidence relationships (UI_UX §3.18, prototype "Evidence"): columns read left to right from
 * evidence to verdict. Lines are drawn only between records a stored reference links (solid), or
 * that QueryCure inferred (dotted, named). "Selected path" highlights one chain and keeps every
 * other record visible but quieter; "Everything" draws all of them alike. */
export function EvidenceExplorer({
  findings,
  hypotheses,
  candidates,
  verifications,
  evidence,
  actionsFor,
  initial,
}: {
  findings: Finding[];
  hypotheses: Hypothesis[];
  candidates: OptimizationCandidate[];
  verifications: Verification[];
  evidence: ReadonlyMap<string, EvidenceDetail | "error">;
  /** Navigation buttons for the selected record (Show in plan, Show step, Open in benchmark). */
  actionsFor?: (node: GraphNode) => React.ReactNode;
  /** Record to select first, when it exists. */
  initial?: string | null;
}) {
  const graph = useMemo(() => buildEvidenceGraph({ findings, hypotheses, candidates, verifications, evidence }), [findings, hypotheses, candidates, verifications, evidence]);
  const ordered = useMemo(() => orderNodes(graph), [graph]);
  const byId = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph]);
  const fallback = useMemo(() => explainingSelection(graph), [graph]);
  const [picked, setPicked] = useState<string | null>(null);
  const selected = picked && byId.has(picked) ? picked : initial && byId.has(initial) ? initial : fallback;
  const [scope, setScope] = useState<"path" | "all">("path");
  const path = useMemo(() => (selected ? pathOf(graph, selected) : { nodes: new Set<string>(), links: new Set<string>() }), [graph, selected]);
  const links = graph.links;
  const [inspect, setInspect] = useState<string | null>(null);
  const [tip, setTip] = useState<{ link: GraphLink; x: number; y: number } | null>(null);
  const [copied, setCopied] = useState("");

  const empty = graph.nodes.length === 0;
  const box = useRef<HTMLDivElement>(null);
  const focusNext = useRef<string | null>(null);
  const grid = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState<number | null>(null);
  const [geometry, setGeometry] = useState<{ map: Geometry; w: number; h: number }>({ map: new Map(), w: 0, h: 0 });
  const wide = width === null || width >= GRAPH_MIN_PX;
  const layoutKey = `${scope}|${selected}|${graph.nodes.length}|${[...evidence.keys()].length}`;

  useLayoutEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
    // The section mounts only once there is something to show.
  }, [empty]);
  useLayoutEffect(() => {
    const host = grid.current;
    if (!host || !wide) return;
    const measure = () => {
      const origin = host.getBoundingClientRect();
      const map: Geometry = new Map();
      host.querySelectorAll<HTMLElement>("[data-ev-card]").forEach((el) => {
        const r = el.getBoundingClientRect();
        const col = COLUMNS.indexOf(el.closest<HTMLElement>("[data-ev-column]")?.dataset.evColumn as Column);
        map.set(el.dataset.evCard!, { left: r.left - origin.left, right: r.right - origin.left, y: r.top - origin.top + r.height / 2, bottom: r.bottom - origin.top, col });
      });
      setGeometry({ map, w: origin.width, h: origin.height });
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(host);
    return () => ro.disconnect();
  }, [wide, layoutKey]);
  // Escape dismisses a link tooltip or a link being inspected.
  useEffect(() => {
    if (!tip && !inspect) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setTip(null);
      setInspect(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [tip, inspect]);

  // Arrow keys: up/down within a column, left/right to a linked record in the next column.
  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (!selected || !["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
    if (!(e.target as HTMLElement).hasAttribute("data-ev-node")) return;
    const here = byId.get(selected);
    if (!here) return;
    const col = ordered.filter((n) => n.column === here.column);
    const i = col.findIndex((n) => n.id === selected);
    let next: string | undefined;
    if (e.key === "ArrowUp") next = col[Math.max(0, i - 1)]?.id;
    else if (e.key === "ArrowDown") next = col[Math.min(col.length - 1, i + 1)]?.id;
    else if (e.key === "Home") next = ordered[0]?.id;
    else if (e.key === "End") next = ordered.at(-1)?.id;
    else {
      const forward = e.key === "ArrowRight";
      const ci = COLUMNS.indexOf(here.column);
      for (let c = ci + (forward ? 1 : -1); c >= 0 && c < COLUMNS.length && !next; c += forward ? 1 : -1) {
        const inCol = ordered.filter((n) => n.column === COLUMNS[c]);
        const linked = inCol.find((n) => links.some((l) => (forward ? l.from === selected && l.to === n.id : l.to === selected && l.from === n.id)));
        next = (linked ?? inCol[Math.min(i, inCol.length - 1)])?.id;
      }
    }
    if (!next) return;
    e.preventDefault();
    focusNext.current = next;
    setPicked(next);
  }
  // Keyboard moves land focus on the new card once it has rendered.
  useEffect(() => {
    const id = focusNext.current;
    if (!id) return;
    focusNext.current = null;
    box.current?.querySelector<HTMLElement>(`[data-ev-node="${id}"]`)?.focus();
  }, [selected]);

  const counts = COLUMNS.map((c) => [c, graph.nodes.filter((n) => n.column === c).length] as const);
  const inferred = graph.links.filter((l) => l.basis === "inferred").length;
  const node = selected ? byId.get(selected) : undefined;
  const hotLink = tip?.link.id ?? inspect;
  const hot = hotLink ? graph.links.find((l) => l.id === hotLink) : undefined;

  if (empty) {
    return <p className="qc-panel p-6 text-muted">No evidence recorded yet: findings and hypotheses cite evidence as the agents run.</p>;
  }

  const side = wide && width !== null && width >= 1240;
  return (
    <section ref={box} aria-label="Evidence relationships" className="flex min-w-0 flex-col gap-3">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="flex min-w-0 flex-col">
          <h2 className="text-lg font-semibold">Evidence relationships</h2>
          <p className="text-xs text-muted">
            {counts.map(([c, n]) => `${n} ${COLUMN_LABEL[c].toLowerCase()}${n === 1 ? "" : c === "evidence" ? "" : "s"}`).join(" · ")}
            {` · ${graph.links.length - inferred} recorded links, ${inferred} inferred`}
          </p>
        </div>
        <div role="group" aria-label="Show" className="ml-auto inline-flex rounded-md bg-surface-2 p-0.5">
          {(["path", "all"] as const).map((s) => (
            <button
              key={s}
              type="button"
              aria-pressed={scope === s}
              onClick={() => setScope(s)}
              className={`h-7 rounded px-3 text-xs pointer-coarse:h-10 ${scope === s ? "bg-surface text-ink shadow-sm" : "text-muted hover:text-ink"}`}
            >
              {s === "path" ? "Selected path" : "Everything"}
            </button>
          ))}
        </div>
      </header>
      <Legend />
      {graph.missing.length ? (
        <p role="note" className="text-xs text-inconclusive">
          {graph.missing.map((m) => `${m.from} references ${m.ref} (${m.source}), which this run does not return`).join("; ")}.
        </p>
      ) : null}
      <p className="text-xs text-muted">
        {scope === "path" && node
          ? `Selected path: ${path.nodes.size} of ${graph.nodes.length} records linked to ${COLUMN_LABEL[node.column].toLowerCase()} ${node.id}; the rest stay listed, quieter.`
          : "Every record and link, drawn alike."}
        {wide ? " Point at a line, or at a link in the record panel, to read it." : " Narrow panel: records are listed by column with their links; the Results view or a wider window draws the lines."}
      </p>
      <p aria-live="polite" className="sr-only">
        {copied ? `Copied ${copied}` : ""}
      </p>
      <div className={`flex min-w-0 gap-4 ${side ? "flex-row items-start" : "flex-col"}`}>
        <div
          ref={grid}
          onKeyDown={onKeyDown}
          style={wide ? { paddingBottom: LANE.pad + lanesOf(links, geometry.map).size * LANE.gap } : undefined}
          className={`relative min-w-0 flex-1 ${wide ? "grid grid-cols-5 gap-x-7" : "flex flex-col gap-4"}`}
        >
          {wide ? (
            <Lines
              links={links}
              geometry={geometry.map}
              path={path.links}
              quiet={scope === "path"}
              hot={hotLink}
              width={geometry.w}
              height={geometry.h}
              onHover={(l, at) => setTip(l && at ? { link: l, ...at } : null)}
            />
          ) : null}
          {wide && tip ? (
            <div
              role="tooltip"
              className="pointer-events-none absolute z-30 w-64 rounded-md border border-border-strong bg-surface px-2.5 py-2 text-xs shadow-lg"
              style={{ left: Math.max(0, Math.min(tip.x + 12, geometry.w - 256)), top: tip.y + 14 }}
            >
              <span className="mb-1 block font-mono text-[11px] font-medium">{CLASS_TEXT[linkClass(tip.link)]}</span>
              <LinkDetails l={tip.link} byId={byId} />
            </div>
          ) : null}
          {COLUMNS.map((c) => {
            const items = ordered.filter((n) => n.column === c);
            return (
              <div key={c} role="group" aria-label={`${COLUMN_LABEL[c]} column`} data-ev-column={c} className="flex min-w-0 flex-col gap-2.5">
                <h3 className="qc-eyebrow">{COLUMN_LABEL[c]}</h3>
                {items.length === 0 ? (
                  <p className="text-xs text-muted">{c === "verdict" ? "No benchmark verdict recorded." : c === "candidate" ? "No candidates." : "None."}</p>
                ) : (
                  items.map((n) => (
                    <div key={n.id} className="flex min-w-0 flex-col gap-1">
                      <Card
                        node={n}
                        selected={n.id === selected}
                        onPath={path.nodes.has(n.id)}
                        dim={scope === "path" && !path.nodes.has(n.id)}
                        focusable={n.id === selected}
                        stacked={!wide}
                        onSelect={setPicked}
                        onCopied={setCopied}
                      />
                      {!wide ? (
                        <span className="pl-2 font-mono text-[11px] break-words text-muted">
                          {links
                            .filter((l) => l.to === n.id)
                            .map((l) => `${l.basis === "inferred" ? "≈ " : l.kind === "contradicts" ? "✕ " : ""}${short(l.from)}`)
                            .join(" · ") || (c === "evidence" ? "" : "no incoming links")}
                        </span>
                      ) : null}
                    </div>
                  ))
                )}
              </div>
            );
          })}
        </div>
        {node ? (
          <div className={side ? "w-80 shrink-0" : "w-full"}>
            <Record node={node} graph={graph} byId={byId} onSelect={setPicked} onInspect={setInspect} actions={actionsFor?.(node)} />
            {hot && !tip ? (
              <p role="status" className="mt-2 rounded-md border border-border bg-surface px-2.5 py-2 text-xs">
                <span className="mb-1 block font-mono text-[11px] font-medium">{CLASS_TEXT[linkClass(hot)]}</span>
                <LinkDetails l={hot} byId={byId} />
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}
