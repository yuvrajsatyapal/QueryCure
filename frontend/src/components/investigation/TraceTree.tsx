"use client";

import { useEffect, useMemo, useRef, useState, useSyncExternalStore, type KeyboardEvent } from "react";
import { Icon, type IconName } from "@/components/ui/Icon";
import { StatusIcon, type Tone } from "@/components/ui/StatusPill";
import type { RunEvent } from "@/lib/api/types";
import { describe } from "@/lib/events/describe";
import { traceStats, type Span, type SpanStatus } from "@/lib/events/trace";
import { formatDuration } from "@/lib/format";
import { ancestorIds, traceRows, treeKey } from "@/lib/investigation/links";

const ANNOUNCE_EVERY_MS = 5000;

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

/** Ticks once a second while the run is live, so open spans show a growing duration. */
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

/** The left half of the split trace (UI_UX §3.6): the run and its steps as a WAI-ARIA tree with
 * roving focus. Selection is owned by the caller and follows focus. */
export function TraceTree({
  trace,
  events,
  runLabel,
  live,
  active,
  selectedId,
  onSelect,
}: {
  trace: Span;
  events: RunEvent[];
  runLabel: string;
  live: boolean;
  active: boolean;
  selectedId: string;
  onSelect: (spanId: string) => void;
}) {
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set());
  const [showLogs, setShowLogs] = useState(true);
  const list = useRef<HTMLOListElement>(null);
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
  const start = Date.parse(trace.startTs);
  const end = trace.endTs ? Date.parse(trace.endTs) : mounted ? Math.max(now, start + 1) : start + 1;
  const total = Math.max(end - start, 1);
  const elapsed = trace.durationMs ?? (events.length && mounted ? end - start : undefined);
  const parents = trace.children.filter((c) => c.children.length);

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
    const action = treeKey(rows, selectedId, e.key, effective);
    if (!action) return;
    e.preventDefault();
    if ("select" in action) {
      focusAfterSelect.current = true;
      onSelect(action.select);
    } else if ("expand" in action) toggle(action.expand, true);
    else toggle(action.collapse, false);
  }

  return (
    <section aria-label="Agent timeline" className="qc-panel flex min-h-0 min-w-0 flex-col">
      <header className="flex flex-col gap-2 border-b border-border px-3 py-2.5">
        <div className="flex items-center justify-between gap-2">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <Icon name="node" size={14} className="text-muted" />
            Trace
          </h2>
          <span className={`flex items-center gap-1.5 text-xs ${live ? "text-running" : "text-muted"}`}>
            <span aria-hidden="true" className={`size-1.5 rounded-full ${live ? "qc-pulse bg-running" : "bg-faint"}`} />
            {live ? "Live" : "Not streaming"}
          </span>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="font-mono text-[11px] text-muted tabular-nums">
            {stats.nodes} nodes · {stats.tools} tool calls{stats.errors ? ` · ${stats.errors} errors` : ""}
            {elapsed !== undefined ? ` · ${formatDuration(elapsed)}` : ""}
          </p>
          <div className="flex items-center gap-1">
            <button type="button" onClick={() => setShowLogs((v) => !v)} aria-pressed={!showLogs} className="qc-btn-ghost px-2 py-0.5 text-xs">
              {showLogs ? "Hide logs" : "Show logs"}
            </button>
            {parents.length ? (
              <button
                type="button"
                onClick={() => setCollapsed(collapsed.size ? new Set() : new Set(parents.map((p) => p.id)))}
                className="qc-btn-ghost px-2 py-0.5 text-xs"
              >
                {collapsed.size ? "Expand all" : "Collapse all"}
              </button>
            ) : null}
          </div>
        </div>
      </header>
      <p className="sr-only" aria-live="polite">
        {announcement}
      </p>
      {events.length === 0 ? (
        <p className="px-3 py-6 text-sm text-muted">Waiting for the worker to pick up the run…</p>
      ) : (
        <ol ref={list} role="tree" aria-label="Run steps" onKeyDown={onKeyDown} className="min-h-0 flex-1 overflow-y-auto py-1">
          {rows.map(({ span, depth }) => {
            const selected = span.id === selectedId;
            const expandable = depth > 0 && span.children.length > 0;
            const isOpen = !effective.has(span.id);
            const offset = Date.parse(span.startTs) - start;
            const duration = span.durationMs ?? (span.status === "running" && mounted ? now - Date.parse(span.startTs) : undefined);
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
            const name = span.kind === "run" ? runLabel : span.name;
            return (
              <li
                key={span.id}
                data-span={span.id}
                role="treeitem"
                aria-level={depth + 1}
                aria-selected={selected}
                aria-expanded={expandable ? isOpen : undefined}
                tabIndex={selected ? 0 : -1}
                onClick={() => onSelect(span.id)}
                className={`flex min-w-0 cursor-default items-center gap-1 pr-3 outline-offset-[-2px] ${
                  selected ? "bg-accent-tint shadow-[inset_2px_0_0_var(--accent)]" : "hover:bg-hover"
                }`}
              >
                <span aria-hidden="true" style={{ width: Math.max(0, depth - 1) * 16 + 4 }} className="shrink-0" />
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
                <span className="flex min-w-0 flex-1 items-center gap-2 py-1.5">
                  {span.kind === "run" ? <Icon name="play" size={14} className="text-accent" /> : <SpanGlyph span={span} />}
                  <span className={`min-w-0 truncate text-sm ${nameClass}`} title={name}>
                    {name}
                  </span>
                  {span.kind === "tool" && span.agent ? <span className="hidden truncate text-xs text-muted sm:inline">{span.agent}</span> : null}
                  {word && span.kind !== "event" && span.kind !== "run" && span.status !== "ok" ? <span className="sr-only">({word})</span> : null}
                  {span.evidenceIds.length ? (
                    <span className="shrink-0 rounded border border-border px-1 font-mono text-[10px] text-muted">{span.evidenceIds.length} ev</span>
                  ) : null}
                </span>
                {span.kind === "node" || span.kind === "tool" ? (
                  <span className="hidden w-16 shrink-0 sm:block" aria-hidden="true">
                    <span className="relative block h-1.5 rounded-full bg-surface-2">
                      <span
                        className={`absolute top-0 h-1.5 rounded-full ${
                          span.status === "error" ? "bg-rejected" : span.status === "running" ? "bg-running" : span.kind === "tool" ? "bg-faint" : "bg-accent"
                        }`}
                        style={{
                          left: `${Math.min(98, (offset / total) * 100)}%`,
                          width: `${Math.max(2, ((duration ?? 0) / total) * 100)}%`,
                        }}
                      />
                    </span>
                  </span>
                ) : null}
                <span className="w-14 shrink-0 text-right font-mono text-[11px] text-muted tabular-nums">
                  {span.kind === "event" ? (
                    <time dateTime={span.startTs} title={span.startTs}>
                      {formatDuration(offset)}
                    </time>
                  ) : span.kind === "run" ? (
                    elapsed !== undefined ? formatDuration(elapsed) : ""
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
      )}
    </section>
  );
}
