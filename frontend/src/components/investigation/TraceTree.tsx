"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore, type KeyboardEvent } from "react";
import { Icon, type IconName } from "@/components/ui/Icon";
import { StatusIcon, type Tone } from "@/components/ui/StatusPill";
import type { RunEvent } from "@/lib/api/types";
import { describe } from "@/lib/events/describe";
import { traceStats, type Span, type SpanStatus } from "@/lib/events/trace";
import { formatDuration } from "@/lib/format";
import { ancestorIds, traceRows, treeKey } from "@/lib/investigation/links";
import type { StreamState } from "@/lib/trace/activity";
import { axisBreaks, breakLabel, compressAxis, spacedTicks, eventPosition, longWaits, spanSegments, timeTicks, traceBounds, zoomWindow, type SegmentKind } from "@/lib/trace/waterfall";

const ANNOUNCE_EVERY_MS = 5000;
const ZOOMS = [1, 2, 4, 8, 16];

export const STATUS_TONE: Record<SpanStatus, Tone | null> = {
  running: "running",
  ok: "success",
  error: "failed",
  warning: "warning",
  approval: "approval",
  info: null,
  unfinished: "neutral",
};

export const STATUS_WORD: Record<SpanStatus, string> = {
  running: "running",
  ok: "done",
  error: "failed",
  warning: "warning",
  approval: "approval required",
  info: "",
  unfinished: "did not finish",
};

const EVENT_ICON: Record<string, IconName> = {
  "agent.summary": "message",
  "finding.created": "sparkles",
  "hypothesis.created": "circleDashed",
  "candidate.created": "flask",
  "approval.requested": "hand",
  "approval.decided": "hand",
  "benchmark.progress": "gauge",
  "verification.completed": "checkCircle",
  "report.ready": "report",
  "run.concluded": "checkCircle",
  "run.status_changed": "arrowRight",
  "replay.status_changed": "replay",
  "replay.compared": "replay",
  "evidence.created": "database",
  "budget.warning": "alert",
  error: "xCircle",
};

export function kindIcon(s: Span): IconName {
  if (s.kind === "run") return "play";
  if (s.kind === "node") return s.agent ? "bot" : "node";
  if (s.kind === "tool") return "wrench";
  return EVENT_ICON[s.events[0]?.type ?? ""] ?? "circle";
}

export function SpanGlyph({ span }: { span: Span }) {
  const tone = STATUS_TONE[span.status];
  // The status this glyph shows is also written out for screen readers (never color alone).
  if (tone && tone !== "success" && tone !== "neutral") return <StatusIcon tone={tone} size={14} />;
  return <Icon name={kindIcon(span)} size={14} className={span.kind === "event" ? "text-faint" : "text-muted"} />;
}

const SEGMENT_CLASS: Record<SegmentKind, string> = {
  run: "top-[5px] bottom-[5px] bg-border-strong",
  agent: "top-0.5 bottom-0.5 bg-hypothesis",
  step: "top-0.5 bottom-0.5 bg-border-strong",
  tool: "top-[3px] bottom-[3px] bg-accent",
  wait: "top-0.5 bottom-0.5 qc-seg-wait",
  live: "top-0.5 bottom-0.5 qc-seg-live",
  failed: "top-0.5 bottom-0.5 bg-rejected",
  unfinished: "top-0.5 bottom-0.5 qc-seg-unfinished",
};

export const LEGEND: { kind: SegmentKind; label: string }[] = [
  { kind: "step", label: "Deterministic step" },
  { kind: "agent", label: "Agent step (model + tools)" },
  { kind: "tool", label: "Tool call" },
  { kind: "wait", label: "Waiting on you" },
  { kind: "live", label: "Live now" },
  { kind: "unfinished", label: "No end recorded" },
];

/** Ticks once a second while the run is live, so open spans grow from recorded start times. */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [active]);
  return now;
}

const subscribe = () => () => {};

/** The waterfall trace (UI_UX §3.6, prototype "Layout 1 · Trace"): the run and its steps as a
 * WAI-ARIA tree with roving focus, each row with its recorded latency bar on a shared time axis.
 * Selection is owned by the caller and follows focus. Right-click, Shift+F10 or the context-menu
 * key open the row's actions through `onMenu`. */
export function TraceTree({
  trace,
  events,
  runLabel,
  live,
  stream,
  active,
  selectedId,
  onSelect,
  onActivate,
  onMenu,
  focusRequest = false,
  onFocusDone,
}: {
  trace: Span;
  events: RunEvent[];
  runLabel: string;
  live: boolean;
  stream?: StreamState;
  active: boolean;
  selectedId: string;
  onSelect: (spanId: string) => void;
  /** Click, Enter or Space on a row (arrow keys only select). */
  onActivate?: (spanId: string) => void;
  onMenu?: (spanId: string, at: { x: number; y: number }) => void;
  /** Move focus to the selected row, e.g. after "Show in waterfall"; `onFocusDone` acknowledges it. */
  focusRequest?: boolean;
  onFocusDone?: () => void;
}) {
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set());
  const [showLogs, setShowLogs] = useState(true);
  const [zoom, setZoom] = useState(1);
  // Linear elapsed time is the default; compression is opt-in and labelled wherever it shows.
  const [compress, setCompress] = useState(false);
  const list = useRef<HTMLOListElement>(null);
  const axis = useRef<HTMLDivElement>(null);
  const [axisPx, setAxisPx] = useState(0);
  // The axis row mounts with the first event.
  const hasEvents = events.length > 0;
  useLayoutEffect(() => {
    const el = axis.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setAxisPx(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, [hasEvents]);
  const focusAfterSelect = useRef(false);
  const mounted = useSyncExternalStore(subscribe, () => true, () => false);
  const now = useNow(active && mounted);

  const [announcement, setAnnouncement] = useState("");
  const latest = useRef("");
  const last = events.at(-1);
  const lastText = last ? describe(last).text : "";
  useEffect(() => {
    latest.current = lastText;
  }, [lastText]);
  useEffect(() => {
    // Screen readers get at most one update every 5 s (DESIGN_SYSTEM §9).
    const timer = setInterval(() => setAnnouncement(latest.current), ANNOUNCE_EVERY_MS);
    return () => clearInterval(timer);
  }, []);

  // A row selected from elsewhere (a finding's "Show step") is revealed even inside a collapsed node.
  const effective = useMemo(() => {
    const reveal = new Set(ancestorIds(trace, selectedId));
    return new Set([...collapsed].filter((id) => !reveal.has(id)));
  }, [collapsed, trace, selectedId]);
  const rows = traceRows(trace, effective).filter((r) => showLogs || r.span.kind !== "event" || r.span.id === selectedId);
  const stats = traceStats(trace);
  // Before hydration the clock is not read, so server and client render the same bars.
  const clock = mounted ? now : Date.parse(trace.endTs ?? trace.startTs);
  const bounds = traceBounds(trace, clock);
  const selectedRow = rows.find((r) => r.span.id === selectedId)?.span;
  const focus = selectedRow && selectedRow.kind !== "run" ? (Date.parse(selectedRow.startTs) + Date.parse(selectedRow.endTs ?? selectedRow.startTs)) / 2 : undefined;
  const waits = longWaits(trace, bounds, clock);
  const compressed = compress && waits.length > 0;
  const win = zoomWindow(compressed ? compressAxis(bounds, waits) : bounds, zoom, focus);
  const breaks = axisBreaks(win);
  // Before the axis is measured (and in tests) only the first and last ticks are labelled.
  const allTicks = timeTicks(win, bounds.startMs, 5);
  const ticks = axisPx ? spacedTicks(allTicks, breaks, axisPx) : allTicks.filter((_, i) => i === 0 || i === allTicks.length - 1);
  const elapsed = trace.durationMs ?? (events.length && mounted ? bounds.endMs - bounds.startMs : undefined);
  const parents = trace.children.filter((c) => c.children.length);
  const nowPct = active && !trace.endTs && clock >= win.startMs && clock <= win.endMs ? ((clock - win.startMs) / (win.endMs - win.startMs)) * 100 : null;
  const streamWord = stream === "reconnecting" ? "Reconnecting…" : stream === "offline" ? "Not live" : live ? "Live" : active ? "Connecting…" : "Recorded";

  useEffect(() => {
    if (!focusRequest) return;
    list.current?.querySelector<HTMLElement>(`[data-span="${CSS.escape(selectedId)}"]`)?.focus();
    onFocusDone?.();
  }, [focusRequest, selectedId, onFocusDone]);

  useEffect(() => {
    const el = list.current?.querySelector<HTMLElement>(`[data-span="${CSS.escape(selectedId)}"]`);
    if (!el) return;
    el.scrollIntoView?.({ block: "nearest" });
    if (focusAfterSelect.current) {
      focusAfterSelect.current = false;
      el.focus();
    }
  }, [selectedId]);

  const toggle = (id: string, open?: boolean) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      const shouldOpen = open ?? next.has(id);
      if (shouldOpen) next.delete(id);
      else next.add(id);
      return next;
    });

  function onKeyDown(e: KeyboardEvent<HTMLOListElement>) {
    if (onMenu && (e.key === "ContextMenu" || (e.key === "F10" && e.shiftKey))) {
      e.preventDefault();
      const el = list.current?.querySelector<HTMLElement>(`[data-span="${CSS.escape(selectedId)}"]`);
      const r = el?.getBoundingClientRect();
      onMenu(selectedId, { x: (r?.left ?? 0) + 24, y: r?.bottom ?? 0 });
      return;
    }
    if (onActivate && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      onActivate(selectedId);
      return;
    }
    const action = treeKey(rows, selectedId, e.key, effective);
    if (!action) return;
    e.preventDefault();
    if ("select" in action) {
      focusAfterSelect.current = true;
      onSelect(action.select);
    } else if ("expand" in action) toggle(action.expand, true);
    else toggle(action.collapse, false);
  }

  const zi = ZOOMS.indexOf(zoom);
  const cols = "grid grid-cols-[minmax(0,1fr)_minmax(56px,24%)_48px] @2xl:grid-cols-[minmax(200px,260px)_minmax(0,1fr)_68px]";

  return (
    <section aria-label="Agent timeline" className="@container qc-panel flex min-h-0 min-w-0 flex-1 flex-col">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border px-3 py-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <Icon name="node" size={14} className="text-muted" />
          Trace
        </h2>
        <span className={`flex items-center gap-1.5 text-xs ${live ? "text-running" : "text-muted"}`}>
          <span aria-hidden="true" className={`size-1.5 rounded-full ${live ? "qc-pulse bg-running" : "bg-faint"}`} />
          {streamWord}
        </span>
        <p className="font-mono text-xs text-muted tabular-nums">
          {stats.nodes} nodes · {stats.tools} tool calls{stats.errors ? ` · ${stats.errors} errors` : ""}
          {elapsed !== undefined ? ` · ${formatDuration(elapsed)}` : ""}
        </p>
        <div className="ml-auto flex flex-wrap items-center justify-end gap-1">
          <button type="button" onClick={() => setShowLogs((v) => !v)} aria-pressed={!showLogs} className="qc-btn-ghost qc-btn-sm px-2">
            {showLogs ? "Hide logs" : "Show logs"}
          </button>
          {parents.length ? (
            <button
              type="button"
              onClick={() => setCollapsed(collapsed.size ? new Set() : new Set(parents.map((p) => p.id)))}
              className="qc-btn-ghost qc-btn-sm px-2"
            >
              {collapsed.size ? "Expand all" : "Collapse all"}
            </button>
          ) : null}
          {waits.length ? (
            <>
              <span className="mx-1 hidden h-4 w-px bg-border @md:block" aria-hidden="true" />
              <div role="group" aria-label="Time scale" className="inline-flex rounded-md bg-surface-2 p-0.5">
                {([false, true] as const).map((on) => (
                  <button
                    key={String(on)}
                    type="button"
                    aria-pressed={compress === on}
                    onClick={() => setCompress(on)}
                    className={`h-6 rounded px-2 text-xs whitespace-nowrap pointer-coarse:h-10 ${compress === on ? "bg-surface text-ink shadow-sm" : "text-muted hover:text-ink"}`}
                  >
                    {on ? "Compress waits" : "Linear"}
                  </button>
                ))}
              </div>
            </>
          ) : null}
          <span className="mx-1 hidden h-4 w-px bg-border @md:block" aria-hidden="true" />
          <div role="group" aria-label="Time zoom" className="flex items-center gap-1">
            <button type="button" aria-label="Zoom out" disabled={zi <= 0} onClick={() => setZoom(ZOOMS[zi - 1] ?? 1)} className="qc-btn-secondary size-7 p-0 pointer-coarse:size-10">
              −
            </button>
            <button type="button" onClick={() => setZoom(1)} aria-pressed={zoom === 1} className="qc-btn-secondary h-7 px-2 font-mono text-xs pointer-coarse:h-10">
              {zoom === 1 ? "Fit" : `${zoom}×`}
            </button>
            <button type="button" aria-label="Zoom in" disabled={zi >= ZOOMS.length - 1} onClick={() => setZoom(ZOOMS[zi + 1] ?? zoom)} className="qc-btn-secondary size-7 p-0 pointer-coarse:size-10">
              +
            </button>
          </div>
        </div>
      </header>
      <p className="sr-only" aria-live="polite">
        {announcement}
      </p>
      {compressed ? (
        <p role="note" className="flex flex-wrap items-start gap-x-1.5 gap-y-0.5 border-b border-border bg-approval/8 px-3 py-1.5 text-xs text-ink">
          <span aria-hidden="true" className="font-mono font-semibold text-approval">≈</span>
          <span className="font-medium">Compressed time.</span>
          {/* Narrow panes keep the warning, in one line: the axis is not linear across a break. */}
          <span className="@xl:hidden">Not to scale across ≈ breaks; the Time column is real.</span>
          <span className="hidden @xl:inline">
            {waits.length === 1 ? "An approval wait" : `${waits.length} approval waits`} longer than a quarter of the run {waits.length === 1 ? "is" : "are"} drawn at a
            fixed width. Distances across a break are not elapsed time; the Time column is.
          </span>
        </p>
      ) : null}
      {events.length === 0 ? (
        <p className="px-3 py-6 text-sm text-muted">Waiting for the worker to pick up the run…</p>
      ) : (
        <>
          <div aria-hidden="true" className={`${cols} items-center border-b border-border px-3 py-1.5`}>
            <span className="qc-eyebrow">Step</span>
            <div ref={axis} className="relative h-4 font-mono text-[11px] text-muted">
              {breaks.map((b) => {
                const centre = (b.startPct + b.endPct) / 2;
                return (
                  <span
                    key={`break-${b.startPct}`}
                    className={`absolute top-0 whitespace-nowrap text-approval ${centre > 85 ? "" : "-translate-x-1/2"}`}
                    style={centre > 85 ? { right: 0 } : { left: `${centre}%` }}
                  >
                    {breakLabel(b.ms)}
                  </span>
                );
              })}
              {ticks.map((t) => (
                <span
                  key={t.label}
                  className="absolute top-0 whitespace-nowrap"
                  style={t.pct > 85 ? { right: `${100 - t.pct}%` } : { left: `${t.pct}%` }}
                >
                  {t.label}
                </span>
              ))}
            </div>
            <span className="qc-eyebrow text-right">Time</span>
          </div>
          <ol ref={list} role="tree" aria-label="Run steps" onKeyDown={onKeyDown} className="min-h-0 flex-1 overflow-y-auto py-1">
            {rows.map(({ span, depth }) => {
              const selected = span.id === selectedId;
              const expandable = depth > 0 && span.children.length > 0;
              const isOpen = !effective.has(span.id);
              const offset = Date.parse(span.startTs) - bounds.startMs;
              const duration = span.durationMs ?? (span.status === "running" && mounted ? clock - Date.parse(span.startTs) : undefined);
              const word = STATUS_WORD[span.status];
              const tone = span.events[0] ? describe(span.events[0]).tone : "normal";
              const nameClass =
                span.kind === "run"
                  ? "font-medium text-ink"
                  : span.kind === "event"
                    ? span.status === "error"
                      ? "text-rejected"
                      : tone === "muted"
                        ? "text-muted"
                        : "text-ink"
                    : "font-mono text-[13px] text-ink";
              const name = span.kind === "run" ? runLabel : span.resumed ? `${span.name} · resumed` : span.name;
              const point = span.kind === "event" ? eventPosition(span, win) : null;
              return (
                <li
                  key={span.id}
                  data-span={span.id}
                  role="treeitem"
                  aria-level={depth + 1}
                  aria-selected={selected}
                  aria-expanded={expandable ? isOpen : undefined}
                  tabIndex={selected ? 0 : -1}
                  onClick={() => {
                    onSelect(span.id);
                    onActivate?.(span.id);
                  }}
                  onContextMenu={
                    onMenu
                      ? (e) => {
                          e.preventDefault();
                          onSelect(span.id);
                          onMenu(span.id, { x: e.clientX, y: e.clientY });
                        }
                      : undefined
                  }
                  className={`${cols} min-h-[34px] cursor-default items-center px-3 outline-offset-[-2px] pointer-coarse:min-h-11 ${
                    selected ? "bg-accent-tint shadow-[inset_2px_0_0_var(--accent)]" : "hover:bg-hover"
                  }`}
                >
                  <span className="flex min-w-0 items-center gap-1 pr-2">
                    <span aria-hidden="true" style={{ width: Math.max(0, depth - 1) * 14 }} className="shrink-0" />
                    {expandable ? (
                      <span
                        aria-hidden="true"
                        onClick={(e) => {
                          e.stopPropagation();
                          toggle(span.id);
                        }}
                        className="flex size-5 shrink-0 cursor-pointer items-center justify-center rounded text-muted hover:text-ink"
                      >
                        <Icon name={isOpen ? "chevronDown" : "chevronRight"} size={12} />
                      </span>
                    ) : (
                      <span aria-hidden="true" className="size-5 shrink-0" />
                    )}
                    <span className="flex min-w-0 flex-1 items-center gap-2 py-1">
                      {span.kind === "run" ? <Icon name="play" size={14} className="text-accent" /> : <SpanGlyph span={span} />}
                      <span className={`min-w-0 truncate text-sm ${nameClass}`} title={name}>
                        {name}
                      </span>
                      {word && span.kind !== "event" && span.kind !== "run" && span.status !== "ok" ? <span className="sr-only">({word})</span> : null}
                      {span.evidenceIds.length ? (
                        <span className="ml-auto shrink-0 font-mono text-[11px] text-muted">{span.evidenceIds.length} ev</span>
                      ) : null}
                    </span>
                  </span>
                  <span aria-hidden="true" className="relative block h-3.5">
                    {breaks.map((b) => (
                      <span
                        key={`break-${b.startPct}`}
                        className="qc-axis-break absolute -top-2.5 -bottom-2.5"
                        style={{ left: `${b.startPct}%`, width: `${b.endPct - b.startPct}%` }}
                      />
                    ))}
                    {span.kind === "event" ? (
                      point !== null ? (
                        <span
                          className={`absolute top-1/2 size-1.5 -translate-x-1/2 -translate-y-1/2 rotate-45 ${span.status === "error" ? "bg-rejected" : span.status === "approval" ? "bg-approval" : "bg-faint"}`}
                          style={{ left: `${point}%` }}
                        />
                      ) : null
                    ) : (
                      spanSegments(span, win, clock).map((g, i) => (
                        <span
                          key={i}
                          className={`absolute ${SEGMENT_CLASS[g.kind]} ${g.clipStart ? "" : "rounded-l-[3px]"} ${g.clipEnd ? "" : "rounded-r-[3px]"}`}
                          style={{ left: `${g.leftPct}%`, width: `${g.widthPct}%` }}
                        />
                      ))
                    )}
                    {nowPct !== null ? <span className="absolute -top-2 -bottom-2 w-px bg-running/70" style={{ left: `${nowPct}%` }} /> : null}
                  </span>
                  <span className={`text-right font-mono text-xs tabular-nums ${span.status === "running" ? "text-running" : "text-muted"}`}>
                    {span.kind === "event" ? (
                      <time dateTime={span.startTs} title={span.startTs}>
                        {formatDuration(offset)}
                      </time>
                    ) : span.kind === "run" ? (
                      elapsed !== undefined ? formatDuration(elapsed) : ""
                    ) : span.status === "unfinished" ? (
                      "—"
                    ) : duration !== undefined ? (
                      formatDuration(duration)
                    ) : (
                      ""
                    )}
                  </span>
                </li>
              );
            })}
          </ol>
          <ul aria-label="Legend" className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-border px-3 py-2 text-xs text-muted">
            {LEGEND.map((l) => (
              <li key={l.kind} className="flex items-center gap-1.5">
                <span aria-hidden="true" className={`relative h-2 w-4 overflow-hidden rounded-sm ${SEGMENT_CLASS[l.kind].replace(/top-\S+|bottom-\S+/g, "")}`} />
                {l.label}
              </li>
            ))}
            <li className="flex items-center gap-1.5">
              <span aria-hidden="true" className="size-1.5 rotate-45 bg-faint" />
              Logged event
            </li>
            {compressed ? (
              <li className="flex items-center gap-1.5">
                <span aria-hidden="true" className="qc-axis-break relative h-3 w-4" />
                Compressed wait, not to scale
              </li>
            ) : null}
          </ul>
        </>
      )}
    </section>
  );
}
