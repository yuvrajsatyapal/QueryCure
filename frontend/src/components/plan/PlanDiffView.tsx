"use client";

import { useQuery } from "@tanstack/react-query";
import { useRef, useState, type ReactNode } from "react";
import { ErrorNotice } from "@/components/common/ErrorNotice";
import { Icon } from "@/components/ui/Icon";
import { Skeleton } from "@/components/ui/Skeleton";
import { getPlanDiff, reportKeys } from "@/lib/api/reports";
import type { PlanDiff } from "@/lib/api/types";
import { formatCost, formatMs, formatNs, formatRows } from "@/lib/format";
import {
  diffRows,
  diffSummary,
  nodeMetricRows,
  ratioText,
  recordedActuals,
  summaryFigures,
  type DiffRow,
  type DiffSide,
  type MetricUnit,
  type Provenance,
} from "@/lib/plan/diff";

export { diffSummary };

export type DiffLayout = "side" | "unified";

/** The benchmark's own medians for the same candidate and parameter set: the measurement that
 * decides, shown beside (never merged with) the single plan capture. */
export interface BenchmarkMedians {
  baselineNs: number;
  candidateNs: number;
  nBaseline: number;
  nCandidate: number;
}

const STATUS: Record<DiffRow["status"], { chip: string; glyph: string; tone: string; row: string }> = {
  same: { chip: "same", glyph: "=", tone: "text-muted", row: "" },
  changed: { chip: "changed", glyph: "~", tone: "text-inconclusive", row: "bg-inconclusive/8" },
  added: { chip: "added", glyph: "+", tone: "text-verified", row: "bg-verified/8" },
  removed: { chip: "removed", glyph: "−", tone: "text-rejected", row: "bg-rejected/8" },
};

const chipText = (r: DiffRow) => (r.typeChanged ? "type changed" : STATUS[r.status].chip);

function format(unit: MetricUnit, v: number | null): string {
  if (v === null) return "—";
  if (unit === "ms") return formatMs(v);
  if (unit === "cost") return formatCost(v);
  return formatRows(v);
}

function KindTag({ kind }: { kind: Provenance }) {
  return (
    <span className={`qc-tag h-5 font-mono text-[11px] ${kind === "estimated" ? "border-dashed" : ""}`}>{kind === "measured" ? "measured" : "estimate"}</span>
  );
}

function rowsText(s: DiffSide | null): string {
  if (!s?.rows) return "—";
  return s.rows.kind === "estimated" ? `~${formatRows(s.rows.value)}` : formatRows(s.rows.value);
}

/** Numeric columns appear when the diff's own container is wide (≥ 42 rem); in narrower panels
 * (the studio is 324–606 px today) the same figures sit under the node name instead. The cells
 * stay in the table (a hidden cell would shift later cells into the wrong columns); only their
 * padding and content go, and `Cell` keeps the hidden content out of the accessibility tree. */
const WIDE = "p-0 @2xl/diff:px-2 @2xl/diff:py-2";
const NARROW = "@2xl/diff:hidden";

/** Content shown only in the wide layout; `display: none` also hides it from screen readers. */
function Wide({ children }: { children: ReactNode }) {
  return <span className="hidden @2xl/diff:inline">{children}</span>;
}

function Figures({ rows, self, className = "" }: { rows: string; self: string; className?: string }) {
  return (
    <span className={`block font-mono text-[11px] text-muted ${className}`}>
      rows {rows} · self {self}
    </span>
  );
}

function NodeName({ side, row, strike = false, children }: { side: DiffSide; row: DiffRow; strike?: boolean; children?: ReactNode }) {
  const where = [side.relation, side.index].filter(Boolean).join(" · ");
  // Long index names are truncated here, not wrapped letter by letter; the full text stays in the
  // DOM (screen readers read it), in the tooltip, and in the node metrics panel behind the marker.
  return (
    <span className="flex min-w-0 flex-col" style={{ paddingLeft: `${Math.min(row.depth, 6) * 12}px` }}>
      <span title={side.label} className={`line-clamp-2 font-mono text-[13px] break-words ${strike ? "text-muted line-through" : ""}`}>{side.label}</span>
      {where ? <span title={where} className="truncate font-mono text-[11px] text-muted">{where}</span> : null}
      {children}
    </span>
  );
}

function StatusChip({
  row,
  open,
  controls,
  register,
  onToggle,
}: {
  row: DiffRow;
  open: boolean;
  controls: string;
  register: (el: HTMLButtonElement | null) => void;
  onToggle: () => void;
}) {
  const s = STATUS[row.status];
  return (
    <button
      ref={register}
      type="button"
      aria-expanded={open}
      aria-controls={open ? controls : undefined}
      aria-label={`${row.label}, ${chipText(row)}: show recorded metrics`}
      onClick={onToggle}
      className={`inline-flex min-h-6 items-center gap-1 rounded px-1.5 font-mono text-xs whitespace-nowrap hover:bg-hover pointer-coarse:min-h-10 ${s.tone} ${open ? "ring-1 ring-border-strong" : ""}`}
    >
      <span aria-hidden="true">{s.glyph}</span>
      {chipText(row)}
    </button>
  );
}

const selfText = (s: DiffSide | null) => (s ? formatMs(s.selfMs) : "—");

function SideBySide({ rows, chip }: { rows: DiffRow[]; chip: (r: DiffRow) => ReactNode }) {
  const num = `${WIDE} text-right font-mono text-xs text-muted`;
  return (
    <div className="overflow-x-auto rounded-lg border border-border" tabIndex={0} role="region" aria-label="Side-by-side plan nodes, baseline and candidate">
      <table className="w-full min-w-[300px] table-fixed text-left text-sm">
        <caption className="sr-only">Plan nodes side by side: baseline on the left, candidate on the right, change in the middle</caption>
        <colgroup>
          <col />
          <col className="w-0 @2xl/diff:w-20" />
          <col className="w-0 @2xl/diff:w-20" />
          <col className="w-[6.5rem] @2xl/diff:w-32" />
          <col />
          <col className="w-0 @2xl/diff:w-20" />
          <col className="w-0 @2xl/diff:w-20" />
        </colgroup>
        <thead className="bg-surface-2">
          <tr className="qc-eyebrow text-[11px]">
            <th scope="col" className="px-3 py-2">Baseline</th>
            <th scope="col" className={`${WIDE} text-right`}><Wide>Rows</Wide></th>
            <th scope="col" className={`${WIDE} text-right`}><Wide>Self</Wide></th>
            <th scope="col" className="border-x border-border px-2 py-2 text-center">Change</th>
            <th scope="col" className="px-3 py-2">Candidate</th>
            <th scope="col" className={`${WIDE} text-right`}><Wide>Rows</Wide></th>
            <th scope="col" className={`${WIDE} text-right`}><Wide>Self</Wide></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const tint = STATUS[r.status].row;
            const left = r.status === "added" ? "" : tint;
            const right = r.status === "removed" ? "" : tint;
            return (
              <tr key={r.key} className="border-t border-border align-top">
                <td className={`px-3 py-2 ${left}`}>
                  {r.from ? (
                    <NodeName side={r.from} row={r} strike={r.status === "removed"}>
                      <Figures rows={rowsText(r.from)} self={selfText(r.from)} className={NARROW} />
                    </NodeName>
                  ) : (
                    <span className="text-xs text-muted">not in baseline</span>
                  )}
                </td>
                <td className={`${num} ${left}`}><Wide>{r.from ? rowsText(r.from) : ""}</Wide></td>
                <td className={`${num} ${left}`}><Wide>{r.from ? selfText(r.from) : ""}</Wide></td>
                <td className="border-x border-border px-1 py-1.5 text-center">{chip(r)}</td>
                <td className={`px-3 py-2 ${right}`}>
                  {r.to ? (
                    <NodeName side={r.to} row={r}>
                      <Figures rows={rowsText(r.to)} self={selfText(r.to)} className={NARROW} />
                    </NodeName>
                  ) : (
                    <span className="text-xs text-muted">not in candidate</span>
                  )}
                </td>
                <td className={`${num} ${right}`}><Wide>{r.to ? rowsText(r.to) : ""}</Wide></td>
                <td className={`${num} ${right}`}><Wide>{r.to ? selfText(r.to) : ""}</Wide></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const pair = (a: string, b: string) => (a === b ? a : `${a} → ${b}`);

function Unified({ rows, chip }: { rows: DiffRow[]; chip: (r: DiffRow) => ReactNode }) {
  const num = `${WIDE} text-right font-mono text-xs whitespace-nowrap text-muted`;
  return (
    <div className="overflow-x-auto rounded-lg border border-border" tabIndex={0} role="region" aria-label="Unified plan nodes, baseline to candidate">
      <table className="w-full min-w-[280px] text-left text-sm">
        <caption className="sr-only">Plan nodes in one list; each figure reads baseline → candidate</caption>
        <thead className="bg-surface-2">
          <tr className="qc-eyebrow text-[11px]">
            <th scope="col" className="w-[6.5rem] px-2 py-2">Change</th>
            <th scope="col" className="px-2 py-2">Node</th>
            <th scope="col" className={num}><Wide>Rows</Wide></th>
            <th scope="col" className={num}><Wide>Self</Wide></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const shown = r.to ?? r.from;
            const rowsPair = pair(rowsText(r.from), rowsText(r.to));
            const selfPair = pair(selfText(r.from), selfText(r.to));
            const also = r.typeChanged ? r.changes.filter((c) => c !== "node type") : r.changes;
            return (
              <tr key={r.key} className={`border-t border-border align-top ${STATUS[r.status].row}`}>
                <td className="px-1 py-1.5">{chip(r)}</td>
                <td className="px-2 py-2">
                  {shown ? (
                    <NodeName side={{ ...shown, label: r.label }} row={r} strike={r.status === "removed"}>
                      {also.length ? <span className="mt-0.5 block text-[11px] text-inconclusive">{r.typeChanged ? "also: " : ""}{also.join(", ")} changed</span> : null}
                      <Figures rows={rowsPair} self={selfPair} className={NARROW} />
                    </NodeName>
                  ) : null}
                </td>
                <td className={num}><Wide>{rowsPair}</Wide></td>
                <td className={num}><Wide>{selfPair}</Wide></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function NodeMetrics({ row, id, onClose }: { row: DiffRow; id: string; onClose: () => void }) {
  const metrics = nodeMetricRows(row.node);
  const loc = (l: string | null) => l ?? "—";
  const n = row.node;
  const index = n.indexFrom === n.indexTo ? n.indexTo : `${n.indexFrom ?? "none"} → ${n.indexTo ?? "none"}`;
  return (
    <section id={id} aria-label={`Recorded metrics · ${row.label}`} className="@container/metrics flex min-w-0 flex-col gap-2 rounded-lg border border-border bg-surface-2/60 p-3">
      <header className="flex items-start gap-2">
        <div className="flex min-w-0 flex-col">
          <h4 className="text-sm font-semibold break-words">
            <span className="font-mono">{row.label}</span>
            <span className={`ml-2 font-mono text-xs font-normal ${STATUS[row.status].tone}`}>{chipText(row)}</span>
          </h4>
          <p className="font-mono text-[11px] break-all text-muted">
            node baseline {loc(row.node.fromLocator)} · candidate {loc(row.node.toLocator)}
          </p>
          {n.relation || index ? (
            <dl className="mt-1 grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 text-xs">
              {n.relation ? (
                <>
                  <dt className="text-muted">Relation</dt>
                  <dd className="font-mono break-all">{n.relation}</dd>
                </>
              ) : null}
              {index ? (
                <>
                  <dt className="text-muted">Index</dt>
                  <dd className="font-mono break-all">{index}</dd>
                </>
              ) : null}
            </dl>
          ) : null}
        </div>
        <button type="button" onClick={onClose} aria-label="Close node metrics" className="qc-btn-ghost qc-btn-sm ml-auto px-1.5 pointer-coarse:size-10">
          <Icon name="close" size={14} />
        </button>
      </header>
      {row.changes.length ? (
        <p className="text-xs">
          <span className="text-muted">Changed properties: </span>
          {row.changes.join(", ")}.{" "}
          <span className="text-muted">The diff records which properties differ, not their values.</span>
        </p>
      ) : null}
      {metrics.length ? (
        <ul aria-label={`Recorded metrics for ${row.label}`} className="flex flex-col gap-1.5 @md/metrics:hidden">
          {metrics.map((m) => (
            <li key={m.key} className="rounded-md border border-border bg-surface px-2.5 py-2">
              <div className="flex items-start justify-between gap-2">
                <span className="text-xs font-medium">{m.label}</span>
                <KindTag kind={m.kind} />
              </div>
              <dl className="mt-1.5 grid grid-cols-3 gap-2 text-xs">
                <div className="min-w-0">
                  <dt className="text-[11px] text-muted">Baseline</dt>
                  <dd className="font-mono whitespace-nowrap">{format(m.unit, m.from)}</dd>
                </div>
                <div className="min-w-0">
                  <dt className="text-[11px] text-muted">Candidate</dt>
                  <dd className="font-mono whitespace-nowrap">{format(m.unit, m.to)}</dd>
                </div>
                <div className="min-w-0">
                  <dt className="text-[11px] text-muted">Change</dt>
                  <dd className="font-mono text-muted">{ratioText(m.ratio) ?? "—"}</dd>
                </div>
              </dl>
            </li>
          ))}
        </ul>
      ) : null}
      {metrics.length ? (
        <div className="hidden overflow-x-auto @md/metrics:block" tabIndex={0} role="region" aria-label={`Metric table · ${row.label}`}>
          <table className="w-full min-w-[340px] text-left text-xs">
            <caption className="sr-only">Recorded metrics for {row.label}, baseline and candidate</caption>
            <thead className="qc-eyebrow text-[11px]">
              <tr>
                <th scope="col" className="py-1 pr-2">Metric</th>
                <th scope="col" className="py-1 pr-2 text-right">Baseline</th>
                <th scope="col" className="py-1 pr-2 text-right">Candidate</th>
                <th scope="col" className="py-1 pr-2">Change</th>
                <th scope="col" className="py-1">Source</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              {metrics.map((m) => (
                <tr key={m.key} className="border-t border-border">
                  <th scope="row" className="py-1 pr-2 font-sans font-normal">{m.label}</th>
                  <td className="py-1 pr-2 text-right">{format(m.unit, m.from)}</td>
                  <td className="py-1 pr-2 text-right">{format(m.unit, m.to)}</td>
                  <td className="py-1 pr-2 text-muted">{ratioText(m.ratio) ?? "—"}</td>
                  <td className="py-1">
                    <KindTag kind={m.kind} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-xs text-muted">No metrics were recorded for this node.</p>
      )}
    </section>
  );
}

/** Baseline → candidate on one line when the card has room; stacked and labelled when it does
 * not, so a value never breaks between its number and its unit. */
function Figure({ label, from, to, source, kind }: { label: string; from: string; to: string; source: string; kind: Provenance }) {
  return (
    <div className="@container/fig flex min-w-0 flex-col gap-1 rounded-lg border border-border bg-surface px-3 py-2.5">
      <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="qc-eyebrow text-[11px]">{label}</span>
        <KindTag kind={kind} />
      </span>
      <span className="hidden font-mono text-sm whitespace-nowrap @[16rem]/fig:block">
        {from} → {to}
      </span>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] items-baseline gap-x-2 @[16rem]/fig:hidden">
        <dt className="text-[11px] text-muted">baseline</dt>
        <dd className="font-mono text-sm whitespace-nowrap">{from}</dd>
        <dt className="text-[11px] text-muted">candidate</dt>
        <dd className="font-mono text-sm whitespace-nowrap">{to}</dd>
      </dl>
      <span className="text-[11px] text-muted">{source}</span>
    </div>
  );
}

const withUnit = (unit: MetricUnit, v: number | null) => (v !== null && unit === "blocks" ? `${format(unit, v)} blocks` : format(unit, v));

export function PlanDiffTable({
  diff,
  layout,
  onLayout,
  benchmark,
}: {
  diff: PlanDiff;
  layout?: DiffLayout;
  onLayout?: (l: DiffLayout) => void;
  benchmark?: BenchmarkMedians | null;
}) {
  const [ownLayout, setOwnLayout] = useState<DiffLayout>("side");
  const view = layout ?? ownLayout;
  const setView = onLayout ?? setOwnLayout;
  const rows = diffRows(diff);
  const figures = summaryFigures(diff);
  const actuals = recordedActuals(diff);
  const s = diff.summary;
  const [openKey, setOpenKey] = useState<string | null>(null);
  const chips = useRef(new Map<string, HTMLButtonElement>());
  const open = rows.find((r) => r.key === openKey) ?? null;
  const panelId = "plan-diff-node-metrics";
  const close = () => {
    const key = openKey;
    setOpenKey(null);
    if (key) chips.current.get(key)?.focus();
  };
  const chip = (r: DiffRow) => (
    <StatusChip
      row={r}
      open={openKey === r.key}
      controls={panelId}
      register={(el) => {
        if (el) chips.current.set(r.key, el);
        else chips.current.delete(r.key);
      }}
      onToggle={() => setOpenKey((k) => (k === r.key ? null : r.key))}
    />
  );

  return (
    <div className="@container/diff flex min-w-0 flex-col gap-3">
      <div className="grid grid-cols-2 gap-2 @2xl/diff:grid-cols-4">
        <div className="col-span-2 flex min-w-0 flex-col gap-1 rounded-lg border border-border bg-surface px-3 py-2.5 @2xl/diff:col-span-1 @2xl/diff:row-span-2">
          <span className="qc-eyebrow text-[11px]">What changed</span>
          <span className="text-sm [overflow-wrap:anywhere]">{diffSummary(diff)}</span>
          <span className="text-[11px] text-muted">
            Structural match · {s.changed} changed, {s.removed} removed, {s.added} added, {s.same} same
          </span>
        </div>
        {benchmark ? (
          <Figure
            label="Benchmark median"
            kind="measured"
            from={formatNs(benchmark.baselineNs)}
            to={formatNs(benchmark.candidateNs)}
            source={`Timed samples, n ${benchmark.nBaseline} / ${benchmark.nCandidate}; this decides the verdict`}
          />
        ) : null}
        {figures.map((f) => (
          <Figure key={f.key} label={f.label} kind={f.kind} from={withUnit(f.unit, f.from)} to={withUnit(f.unit, f.to)} source={f.source} />
        ))}
      </div>

      {!actuals.from || !actuals.to ? (
        <p role="note" className="flex gap-2 rounded-md border border-dashed border-border-strong px-3 py-2 text-xs text-muted">
          <Icon name="alert" size={14} className="mt-0.5 shrink-0" />
          {!actuals.from && !actuals.to
            ? "Neither plan has EXPLAIN ANALYZE actuals, so rows are planner estimates (marked ~) and no node times were recorded."
            : `The ${actuals.from ? "candidate" : "baseline"} plan has no EXPLAIN ANALYZE actuals; its rows are planner estimates (marked ~).`}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div role="group" aria-label="Diff layout" className="inline-flex rounded-md bg-surface-2 p-0.5">
          {(["side", "unified"] as const).map((l) => (
            <button
              key={l}
              type="button"
              aria-pressed={view === l}
              onClick={() => setView(l)}
              className={`h-7 rounded px-3 text-xs pointer-coarse:h-10 ${view === l ? "bg-surface text-ink shadow-sm" : "text-muted hover:text-ink"}`}
            >
              {l === "side" ? "Side by side" : "Unified"}
            </button>
          ))}
        </div>
        <ul aria-label="Legend" className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
          {(["changed", "removed", "added"] as const).map((k) => (
            <li key={k} className="inline-flex items-center gap-1.5">
              <span aria-hidden="true" className={`font-mono ${STATUS[k].tone}`}>{STATUS[k].glyph}</span>
              {k === "changed" ? "changed" : k === "removed" ? "only in baseline" : "only in candidate"}
            </li>
          ))}
          <li>~ before a row count: planner estimate</li>
        </ul>
      </div>

      {view === "side" ? <SideBySide rows={rows} chip={chip} /> : <Unified rows={rows} chip={chip} />}
      <p className="text-[11px] text-muted">Select a change marker to see every metric recorded for that node.</p>
      <div aria-live="polite">{open ? <NodeMetrics row={open} id={panelId} onClose={close} /> : null}</div>
    </div>
  );
}

export function PlanDiffView({
  runId,
  from,
  to,
  layout,
  onLayout,
  benchmark,
}: {
  runId: string;
  from: string;
  to: string;
  layout?: DiffLayout;
  onLayout?: (l: DiffLayout) => void;
  benchmark?: BenchmarkMedians | null;
}) {
  const diff = useQuery({
    queryKey: reportKeys.planDiff(runId, from, to),
    queryFn: ({ signal }) => getPlanDiff(runId, from, to, signal),
  });
  if (diff.error) return <ErrorNotice error={diff.error} />;
  if (!diff.data) return <Skeleton label="Comparing plans" lines={4} />;
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <PlanDiffTable diff={diff.data.diff} layout={layout} onLayout={onLayout} benchmark={benchmark} />
      <p className="font-mono text-[11px] break-all text-muted">
        sha256 baseline {diff.data.fromSha256.slice(0, 12)}… → candidate {diff.data.toSha256.slice(0, 12)}…
      </p>
    </div>
  );
}
