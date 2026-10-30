"use client";

import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";
import { StatusOrb } from "@/components/ui/StatusPill";
import type { Span } from "@/lib/events/trace";
import { formatDuration } from "@/lib/format";
import { ANALYST_GROUP, CANVAS, END, GRAPH_LAYOUT, NODE_H, REPORT, START, TOPOLOGY, edgePath, graphRun, nodeWidth, type GraphNode, type NodeState } from "@/lib/trace/graph";

const STATE_WORD: Record<NodeState, string> = {
  done: "done",
  running: "running",
  approval: "waiting on you",
  failed: "failed",
  unfinished: "did not finish",
  not_reached: "not reached",
};
const STATE_BAR: Record<NodeState, string> = {
  done: "bg-verified",
  running: "bg-running",
  approval: "bg-approval",
  failed: "bg-rejected",
  unfinished: "bg-faint",
  not_reached: "bg-border-strong",
};
const ZOOMS = [0.5, 0.67, 0.8, 0.9, 1, 1.15, 1.25, 1.5];
// Fit never shrinks the 12px labels below about 10px; past that the canvas scrolls instead.
const FIT = { min: 0.85, max: 1.15, pad: 24 };
// Reading order on the canvas (row by row), which is also the keyboard order.
const ORDER = TOPOLOGY.nodes.filter((n) => n !== START && n !== END).sort((a, b) => GRAPH_LAYOUT[a]!.y - GRAPH_LAYOUT[b]!.y || GRAPH_LAYOUT[a]!.x - GRAPH_LAYOUT[b]!.x);

function meta(name: string, g: GraphNode, active: boolean): string {
  if (g.state === "not_reached") return active ? "no events recorded" : "not reached in this run";
  const parts: string[] = [];
  if (g.visits.length > 1) parts.push(`${g.visits.length} runs`);
  if (g.waitMs) parts.push(`waited ${formatDuration(g.waitMs)}`);
  else if (g.state === "running") parts.push("running");
  else if (g.durationMs) parts.push(formatDuration(g.durationMs));
  if (g.toolCalls) parts.push(`${g.toolCalls} tool${g.toolCalls === 1 ? "" : "s"}`);
  if (g.evidence) parts.push(`${g.evidence} ev`);
  if (name === REPORT && g.state === "done") parts.push("sealed");
  return parts.join(" · ") || STATE_WORD[g.state];
}

/** The graph view (UI_UX §3.6a, prototype "Layout 2 · Graph"): the compiled LangGraph topology
 * with each node's recorded state. Edges the run took are solid; others are dashed, and the
 * conditional stop exits to write_report are hidden unless asked for. Nodes are buttons in
 * graph order; arrow keys move between them. Fit scales the canvas to the pane (to its height
 * too when `fillHeight`), never below 85%; the panel is no taller than the drawn graph. Drag the
 * background or scroll to pan. */
export function TraceGraph({
  trace,
  active,
  live = false,
  selectedNode,
  onSelectNode,
  fillHeight = false,
  focusRequest = false,
  onFocusDone,
  note,
}: {
  trace: Span;
  active: boolean;
  /** The stream is confirmed live: a running node is executing now and its orb may move. */
  live?: boolean;
  selectedNode: string | null;
  onSelectNode: (node: string) => void;
  /** The pane has a fixed height (the split): fit to it as well as to the width. */
  fillHeight?: boolean;
  /** Move focus to the selected node (or the first one), e.g. after "Show in graph", whether the
   * graph is already shown or mounts with the request; `onFocusDone` acknowledges it. */
  focusRequest?: boolean;
  onFocusDone?: () => void;
  /** Why the graph is empty when that is expected (an experiment replay runs no agents). */
  note?: string;
}) {
  const { nodes, taken } = graphRun(trace);
  const [zoom, setZoom] = useState<number | "fit">("fit");
  const [fit, setFit] = useState(1);
  const [exits, setExits] = useState(false);
  const section = useRef<HTMLElement>(null);
  const head = useRef<HTMLElement>(null);
  const legend = useRef<HTMLUListElement>(null);
  const caption = useRef<HTMLParagraphElement>(null);
  // Touch users get a one-time hint that the canvas pans; it goes once they have scrolled it.
  const [explored, setExplored] = useState(false);
  const [overflows, setOverflows] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLDivElement>(null);
  // The point of the canvas at the centre of the view, kept there across a zoom.
  const centre = useRef<{ x: number; y: number } | null>(null);

  useLayoutEffect(() => {
    const el = box.current;
    const host = section.current?.parentElement;
    if (!el || !host || typeof ResizeObserver === "undefined") return;
    const measure = () => {
      const w = (el.clientWidth - FIT.pad) / CANVAS.width;
      const room = host.clientHeight - (head.current?.offsetHeight ?? 0) - (caption.current?.offsetHeight ?? 0) - (legend.current?.offsetHeight ?? 0) - 2;
      const h = fillHeight ? (room - FIT.pad) / CANVAS.height : Infinity;
      setFit(Math.max(FIT.min, Math.min(FIT.max, w, h)));
    };
    const ro = new ResizeObserver(() => {
      measure();
      setOverflows(el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1);
    });
    ro.observe(el);
    ro.observe(host);
    return () => ro.disconnect();
  }, [fillHeight]);
  const scale = zoom === "fit" ? fit : zoom;

  useLayoutEffect(() => {
    const el = box.current;
    const c = centre.current;
    if (!el || !c) return;
    centre.current = null;
    el.scrollLeft = c.x * scale + FIT.pad / 2 - el.clientWidth / 2;
    el.scrollTop = c.y * scale + FIT.pad / 2 - el.clientHeight / 2;
  }, [scale]);

  useEffect(() => {
    if (!selectedNode) return;
    canvas.current?.querySelector<HTMLElement>(`[data-node="${selectedNode}"]`)?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [selectedNode]);

  useEffect(() => {
    if (!focusRequest) return;
    const el = canvas.current?.querySelector<HTMLElement>(`[data-node="${selectedNode ?? "intake"}"]`) ?? canvas.current?.querySelector<HTMLElement>("[data-node]");
    el?.focus({ preventScroll: true });
    el?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
    onFocusDone?.();
  }, [focusRequest, selectedNode, onFocusDone]);

  const rememberCentre = () => {
    const el = box.current;
    if (el)
      centre.current = {
        x: (el.scrollLeft + el.clientWidth / 2 - FIT.pad / 2) / scale,
        y: (el.scrollTop + el.clientHeight / 2 - FIT.pad / 2) / scale,
      };
  };
  const step = (by: number) => {
    const next = by > 0 ? ZOOMS.find((v) => v > scale + 0.01) : [...ZOOMS].reverse().find((v) => v < scale - 0.01);
    if (!next) return;
    rememberCentre();
    setZoom(next);
  };

  // Drag the background to pan (mouse only; touch scrolls natively).
  function onPanStart(e: ReactPointerEvent<HTMLDivElement>) {
    const el = box.current;
    if (!el || e.pointerType !== "mouse" || e.button !== 0 || (e.target as HTMLElement).closest("button")) return;
    e.preventDefault();
    const from = {
      x: e.clientX,
      y: e.clientY,
      left: el.scrollLeft,
      top: el.scrollTop,
    };
    el.setPointerCapture(e.pointerId);
    el.dataset.panning = "";
    const move = (ev: PointerEvent) => {
      el.scrollLeft = from.left - (ev.clientX - from.x);
      el.scrollTop = from.top - (ev.clientY - from.y);
    };
    const up = () => {
      delete el.dataset.panning;
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
    };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
  }

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (!["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp", "Home", "End"].includes(e.key)) return;
    const i = ORDER.indexOf(selectedNode ?? "");
    const to = e.key === "Home" ? 0 : e.key === "End" ? ORDER.length - 1 : e.key === "ArrowRight" || e.key === "ArrowDown" ? i + 1 : i - 1;
    const name = ORDER[Math.max(0, Math.min(ORDER.length - 1, to))];
    if (!name) return;
    e.preventDefault();
    onSelectNode(name);
    canvas.current?.querySelector<HTMLElement>(`[data-node="${name}"]`)?.focus();
  }

  const picked = selectedNode ? nodes.get(selectedNode) : undefined;
  const edges = TOPOLOGY.edges.filter(
    (e) => exits || taken.has(`${e.source}->${e.target}`) || e.target !== REPORT || e.source === "synthesize_hypotheses" || e.source === "benchmark_auditor",
  );

  return (
    <section ref={section} aria-label="Agent graph" className="qc-panel flex min-h-0 min-w-0 flex-col">
      <header ref={head} className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border px-3 py-2">
        <h2 className="text-sm font-semibold">Graph</h2>
        <span className="text-xs text-muted">LangGraph topology · states from recorded events</span>
        <div className="ml-auto flex flex-wrap items-center gap-1">
          <button type="button" aria-pressed={exits} onClick={() => setExits((v) => !v)} className="qc-btn-ghost qc-btn-sm px-2">
            {exits ? "Hide stop exits" : "Show stop exits"}
          </button>
          <span className="mx-1 h-4 w-px bg-border" aria-hidden="true" />
          <div role="group" aria-label="Graph zoom" className="flex items-center gap-1">
            <button type="button" aria-label="Zoom out" onClick={() => step(-1)} className="qc-btn-secondary size-7 p-0 pointer-coarse:size-10">
              −
            </button>
            <button
              type="button"
              aria-pressed={zoom === "fit"}
              aria-label={zoom === "fit" ? `Fit, ${Math.round(scale * 100)}%` : `Zoom ${Math.round(scale * 100)}%, fit to pane`}
              onClick={() => {
                rememberCentre();
                setZoom("fit");
              }}
              className="qc-btn-secondary h-7 px-2 font-mono text-xs pointer-coarse:h-10"
            >
              {zoom === "fit" ? `Fit · ${Math.round(scale * 100)}%` : `${Math.round(scale * 100)}%`}
            </button>
            <button type="button" aria-label="Zoom in" onClick={() => step(1)} className="qc-btn-secondary size-7 p-0 pointer-coarse:size-10">
              +
            </button>
          </div>
        </div>
      </header>
      {note ? (
        <p role="note" className="border-b border-border px-3 py-2 text-xs text-muted">
          {note}
        </p>
      ) : null}
      <div
        ref={box}
        tabIndex={-1}
        onPointerDown={onPanStart}
        onScroll={() => setExplored(true)}
        style={{ height: CANVAS.height * scale + FIT.pad }}
        className="min-h-0 cursor-grab overflow-auto bg-bg bg-[radial-gradient(var(--border)_1px,transparent_1px)] [background-size:16px_16px] data-panning:cursor-grabbing data-panning:select-none"
      >
        <div
          style={{
            width: CANVAS.width * scale + FIT.pad,
            height: CANVAS.height * scale + FIT.pad,
          }}
          className="relative mx-auto"
        >
          <div
            ref={canvas}
            role="group"
            aria-label="Investigation graph nodes"
            onKeyDown={onKeyDown}
            className="absolute top-3 left-3 origin-top-left"
            style={{
              width: CANVAS.width,
              height: CANVAS.height,
              transform: `scale(${scale})`,
            }}
          >
            <div
              aria-hidden="true"
              className="absolute rounded-xl border border-dashed border-border-strong bg-surface/50"
              style={{
                left: ANALYST_GROUP.x,
                top: ANALYST_GROUP.y,
                width: ANALYST_GROUP.width,
                height: ANALYST_GROUP.height,
              }}
            >
              <span className="absolute inset-x-3 bottom-1 flex items-center justify-between font-mono text-[11px] text-muted">
                <span>fan-out</span>
                <span>in parallel</span>
              </span>
            </div>
            <svg aria-hidden="true" width={CANVAS.width} height={CANVAS.height} className="absolute inset-0 overflow-visible">
              {edges.map((e) => {
                const on = taken.has(`${e.source}->${e.target}`);
                const live = on && nodes.get(e.target)?.state === "running";
                return (
                  <path
                    key={`${e.source}-${e.target}`}
                    d={edgePath(e.source, e.target)}
                    fill="none"
                    strokeWidth={on ? 1.75 : 1.25}
                    stroke={on ? (live ? "var(--running)" : "var(--verified)") : "var(--border-strong)"}
                    strokeDasharray={on ? undefined : e.target === REPORT ? "2 5" : "4 5"}
                  />
                );
              })}
              <circle cx={GRAPH_LAYOUT[START]!.x} cy={GRAPH_LAYOUT[START]!.y} r={5} fill={taken.has(`${START}->intake`) ? "var(--verified)" : "var(--border-strong)"} />
              <circle
                cx={GRAPH_LAYOUT[END]!.x}
                cy={GRAPH_LAYOUT[END]!.y}
                r={5}
                fill="none"
                strokeWidth={1.5}
                stroke={taken.has(`${REPORT}->${END}`) ? "var(--verified)" : "var(--border-strong)"}
              />
            </svg>
            {ORDER.map((name) => {
              const g = nodes.get(name)!;
              const p = GRAPH_LAYOUT[name]!;
              const selected = selectedNode === name;
              const reached = g.state !== "not_reached";
              return (
                <button
                  key={name}
                  type="button"
                  data-node={name}
                  tabIndex={selected || (!selectedNode && name === "intake") ? 0 : -1}
                  aria-pressed={selected}
                  aria-label={`${name}, ${STATE_WORD[g.state]}${reached ? `, ${meta(name, g, active)}` : ""}`}
                  title={`${name} · ${meta(name, g, active)}`}
                  onClick={() => onSelectNode(name)}
                  className={`absolute flex cursor-pointer flex-col justify-center gap-0.5 overflow-hidden rounded-[9px] border pr-3 pl-3.5 text-left ${
                    reached ? "border-border bg-surface" : "border-dashed border-border-strong bg-transparent"
                  } ${selected ? "border-accent shadow-[0_0_0_1px_var(--accent)]" : "hover:border-border-strong"} ${g.state === "running" ? "border-running/60" : ""}`}
                  style={{
                    left: p.x,
                    top: p.y,
                    width: nodeWidth(name),
                    height: NODE_H,
                  }}
                >
                  <span aria-hidden="true" className={`absolute inset-y-0 left-0 w-[3px] ${STATE_BAR[g.state]}`} />
                  {g.state === "running" ? <StatusOrb tone="running" live={live} size={12} className="absolute top-1 right-1" /> : null}
                  <span className={`flex items-center gap-1.5 font-mono text-xs leading-4 font-medium whitespace-nowrap ${reached ? "text-ink" : "text-muted"}`}>{name}</span>
                  <span className="truncate text-xs leading-4 text-muted">{meta(name, g, active)}</span>
                </button>
              );
            })}
          </div>
        </div>
      </div>
      <p
        ref={caption}
        role="status"
        aria-label="Selected node"
        className="flex min-h-9 flex-wrap items-baseline gap-x-2 gap-y-0.5 border-t border-border px-3 py-1.5 text-xs text-muted"
      >
        {selectedNode && picked ? (
          <>
            <span className="font-mono font-medium break-all text-ink">{selectedNode}</span>
            <span>{STATE_WORD[picked.state]}</span>
            {picked.state !== "not_reached" ? <span className="text-ink">{meta(selectedNode, picked, active)}</span> : null}
          </>
        ) : (
          <span>Select a node for its full name and details.</span>
        )}
        {/* Touch only, until the canvas is first scrolled: it pans, and nothing says so otherwise. */}
        {explored ? null : (
          <span aria-hidden="true" className={`ml-auto hidden items-center gap-1 ${overflows ? "pointer-coarse:flex" : ""}`}>
            <svg width="12" height="12" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
              <path d="M7 1.5v11M1.5 7h11M5 3.5 7 1.5l2 2M5 10.5l2 2 2-2M3.5 5 1.5 7l2 2M10.5 5l2 2-2 2" />
            </svg>
            Drag to explore
          </span>
        )}
      </p>
      <ul ref={legend} aria-label="Legend" className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-border px-3 py-2 text-xs text-muted">
        {(["done", "running", "approval", "failed", "not_reached"] as const).map((s) => (
          <li key={s} className="flex items-center gap-1.5">
            <span aria-hidden="true" className={`h-3 w-[3px] ${STATE_BAR[s]}`} />
            {STATE_WORD[s]}
          </li>
        ))}
        <li className="flex items-center gap-1.5">
          <svg aria-hidden="true" width="18" height="6">
            <path d="M0 3 H18" stroke="var(--verified)" strokeWidth="1.75" />
          </svg>
          edge taken
        </li>
      </ul>
    </section>
  );
}
