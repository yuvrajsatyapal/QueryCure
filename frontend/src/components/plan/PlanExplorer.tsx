"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useModal } from "@/components/command/useModal";
import { Icon } from "@/components/ui/Icon";
import type { NodeMetrics, PlanTree } from "@/lib/api/types";
import { formatMs } from "@/lib/format";
import { ESTIMATE_WARN } from "@/lib/plan/estimate";
import { ESTIMATE_MIN_ROWS, ESTIMATE_SEVERE, EXPENSIVE_SHARE, planSummary } from "@/lib/plan/analysis";
import { PlanGraph } from "./PlanGraph";
import { PlanTreeTable } from "./PlanTreeTable";
import { usePlanCollapse, type PlanCollapse } from "./usePlanCollapse";

export type PlanView = "tree" | "graph";

const segment = (active: boolean) =>
  `rounded px-2.5 py-1 text-xs ${active ? "bg-surface font-medium text-ink shadow-sm" : "text-muted hover:text-ink"}`;
const plural = (k: number, word: string) => `${k} ${word}${k === 1 ? "" : "s"}`;

function Summary({ plan, metrics }: { plan: PlanTree; metrics: NodeMetrics[] }) {
  const s = useMemo(() => planSummary(plan, metrics), [plan, metrics]);
  const parts = [
    plural(s.nodes, "node"),
    s.analyzed ? "EXPLAIN ANALYZE" : "plain EXPLAIN (estimates only)",
    s.planningTimeMs != null ? `planning ${formatMs(s.planningTimeMs)}` : null,
    s.executionTimeMs != null ? `execution ${formatMs(s.executionTimeMs)}` : null,
    s.analyzed && !s.hasBuffers ? "no buffer counts" : null,
  ].filter(Boolean);
  return (
    <div role="group" aria-label="Plan summary" className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[12px] text-muted tabular-nums">
      <span>{parts.join(" · ")}</span>
      {s.hasTiming ? <span className={s.expensive ? "text-inconclusive" : ""}>{s.expensive} expensive</span> : null}
      {s.analyzed ? <span className={s.misestimates ? "text-inconclusive" : ""}>{plural(s.misestimates, "row misestimate")}</span> : null}
    </div>
  );
}

function Legend() {
  return (
    <details className="text-xs text-muted">
      <summary className="cursor-pointer select-none hover:text-ink">How nodes are flagged</summary>
      <ul className="mt-1.5 flex list-disc flex-col gap-1 pl-5">
        <li>
          Hottest: the one node with the largest self time. Expensive: self time at least {EXPENSIVE_SHARE * 100}% of the whole
          query. Only plans with timing (EXPLAIN ANALYZE) are flagged.
        </li>
        <li>
          Estimate: the larger of estimated and actual rows per loop divided by the smaller, with its direction. Significant at {ESTIMATE_WARN}×,
          severe at {ESTIMATE_SEVERE}×. Not flagged when the larger side is under {ESTIMATE_MIN_ROWS} rows across all loops, or when the node
          never executed. Fewer rows than estimated below a LIMIT is not flagged (&ldquo;LIMIT above&rdquo;): the LIMIT stopped the node
          early, unless a Sort, Hash or hashed aggregate between them read its whole input.
        </li>
        <li>Row counts and times are per loop, as PostgreSQL reports them. Plain EXPLAIN plans show the planner&apos;s cumulative cost instead.</li>
        <li>These are display thresholds; no benchmark verdict uses them.</li>
      </ul>
    </details>
  );
}

function Body({
  plan,
  metrics,
  view,
  selectedId,
  onSelect,
  citationCounts,
  collapse,
  details,
  wide,
}: {
  plan: PlanTree;
  metrics: NodeMetrics[];
  view: PlanView;
  selectedId: number | null;
  onSelect: (id: number) => void;
  citationCounts?: ReadonlyMap<number, number>;
  collapse: PlanCollapse;
  details?: ReactNode;
  wide: boolean;
}) {
  const main =
    view === "tree" ? (
      <PlanTreeTable plan={plan} metrics={metrics} onSelect={onSelect} selectedId={selectedId} citationCounts={citationCounts} collapse={collapse} />
    ) : (
      <PlanGraph plan={plan} metrics={metrics} onSelect={onSelect} selectedId={selectedId} tall={wide} />
    );
  if (!wide) {
    return (
      <>
        {main}
        {details}
      </>
    );
  }
  return (
    <div className={`grid min-w-0 gap-4 ${details ? "xl:grid-cols-[minmax(0,1fr)_380px]" : ""}`}>
      <div className="min-w-0">{main}</div>
      {details ? <div className="min-w-0">{details}</div> : null}
    </div>
  );
}

/** Execution-plan viewer (UI_UX §3.16): tree or graph, controls, summary, full-width dialog. */
export function PlanExplorer({
  plan,
  metrics,
  selectedId,
  onSelect,
  view: controlledView,
  onViewChange,
  citationCounts,
  details,
  label,
}: {
  plan: PlanTree;
  metrics: NodeMetrics[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  view?: PlanView;
  onViewChange?: (view: PlanView) => void;
  citationCounts?: ReadonlyMap<number, number>;
  /** Node details for the current selection, shown below (or beside, in full width). */
  details?: ReactNode;
  /** Where the plan came from ("live EXPLAIN · 3f2a…"). */
  label?: ReactNode;
}) {
  const [ownView, setOwnView] = useState<PlanView>("tree");
  const view = controlledView ?? ownView;
  const setView = (v: PlanView) => (onViewChange ? onViewChange(v) : setOwnView(v));
  const collapse = usePlanCollapse(plan, selectedId);
  const hottestId = useMemo(() => planSummary(plan, metrics).hottestId, [plan, metrics]);
  const [wide, setWide] = useState(false);

  const controls = (
    <div className="flex flex-wrap items-center gap-2">
      <div role="tablist" aria-label="Plan view" className="flex gap-0.5 rounded-md border border-border bg-surface-2 p-0.5">
        <button role="tab" aria-selected={view === "tree"} className={segment(view === "tree")} onClick={() => setView("tree")}>
          Tree
        </button>
        <button role="tab" aria-selected={view === "graph"} className={segment(view === "graph")} onClick={() => setView("graph")}>
          Graph
        </button>
      </div>
      {view === "tree" ? (
        <>
          <button type="button" className="qc-btn-ghost py-1 text-xs" onClick={collapse.expandAll}>
            Expand all
          </button>
          <button type="button" className="qc-btn-ghost py-1 text-xs" onClick={collapse.collapseAll}>
            Collapse all
          </button>
        </>
      ) : null}
      {hottestId !== null ? (
        <button type="button" className="qc-btn-ghost py-1 text-xs" onClick={() => onSelect(hottestId)} aria-label="Jump to hottest node">
          Hottest node
        </button>
      ) : null}
    </div>
  );

  return (
    <section aria-label="Plan explorer" className="flex min-w-0 flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {label ? <p className="qc-eyebrow">{label}</p> : <span />}
        <div className="flex flex-wrap items-center gap-2">
          {controls}
          <FullWidthButton open={() => setWide(true)} />
        </div>
      </div>
      <Summary plan={plan} metrics={metrics} />
      <Legend />
      {wide ? (
        <WideDialog close={() => setWide(false)} label={label} controls={controls} summary={<Summary plan={plan} metrics={metrics} />}>
          <Body plan={plan} metrics={metrics} view={view} selectedId={selectedId} onSelect={onSelect} citationCounts={citationCounts} collapse={collapse} details={details} wide />
        </WideDialog>
      ) : (
        <Body plan={plan} metrics={metrics} view={view} selectedId={selectedId} onSelect={onSelect} citationCounts={citationCounts} collapse={collapse} details={details} wide={false} />
      )}
    </section>
  );
}

function FullWidthButton({ open }: { open: () => void }) {
  return (
    <button type="button" className="qc-btn-secondary py-1 text-xs" onClick={open}>
      <Icon name="expand" size={13} />
      Full width
    </button>
  );
}

function WideDialog({
  close,
  label,
  controls,
  summary,
  children,
}: {
  close: () => void;
  label?: ReactNode;
  controls: ReactNode;
  summary: ReactNode;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  useModal(ref, close);
  // After useModal has recorded the opener, so Esc and Close return focus to it.
  useEffect(() => closeButton.current?.focus(), []);
  return (
    <div
      ref={ref}
      role="dialog"
      aria-modal="true"
      aria-label="Execution plan, full width"
      className="fixed inset-0 z-50 flex flex-col gap-3 overflow-auto bg-bg px-4 py-4 md:px-8"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h2 className="text-sm font-semibold">Execution plan</h2>
          {label ? <p className="qc-eyebrow">{label}</p> : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {controls}
          <button ref={closeButton} type="button" className="qc-btn-secondary py-1 text-xs" onClick={close}>
            <Icon name="close" size={13} />
            Close
          </button>
        </div>
      </div>
      {summary}
      {children}
    </div>
  );
}
