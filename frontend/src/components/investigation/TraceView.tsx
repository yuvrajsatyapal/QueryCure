"use client";

import { Fragment, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { Icon, type IconName } from "@/components/ui/Icon";
import { StatusIcon, type Tone } from "@/components/ui/StatusPill";
import type { RunEvent } from "@/lib/api/types";
import { describe } from "@/lib/events/describe";
import { buildTrace, flattenTrace, traceStats, type Span, type SpanStatus } from "@/lib/events/trace";
import { formatDuration } from "@/lib/format";

const ANNOUNCE_EVERY_MS = 5000;

const STATUS_TONE: Record<SpanStatus, Tone | null> = {
  running: "running",
  ok: "success",
  error: "failed",
  warning: "warning",
  approval: "approval",
  info: null,
  unfinished: "neutral",
};

const STATUS_WORD: Record<SpanStatus, string> = {
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

function kindIcon(s: Span): IconName {
  if (s.kind === "node") return s.agent ? "bot" : "node";
  if (s.kind === "tool") return "wrench";
  return EVENT_ICON[s.events[0]?.type ?? ""] ?? "circle";
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

function SpanGlyph({ span }: { span: Span }) {
  const tone = STATUS_TONE[span.status];
  // Status the glyph shows is also written out for screen readers (never color alone).
  if (span.kind !== "event" && tone && tone !== "success" && tone !== "neutral") return <StatusIcon tone={tone} size={14} />;
  if (span.kind === "event" && tone && tone !== "success") return <StatusIcon tone={tone} size={14} />;
  return <Icon name={kindIcon(span)} size={14} className={span.kind === "event" ? "text-faint" : "text-muted"} />;
}

function SpanDetails({ span, onEvidence }: { span: Span; onEvidence?: (id: string) => void }) {
  const tone = STATUS_TONE[span.status];
  return (
    <div className="flex flex-col gap-3 border-l-2 border-border bg-surface-2 px-3 py-3 text-xs">
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
        <dt className="text-muted">Type</dt>
        <dd className="font-mono">{span.kind === "event" ? (span.events[0]?.type ?? "event") : span.kind}</dd>
        {span.agent ? (
          <>
            <dt className="text-muted">Agent</dt>
            <dd className="font-mono">{span.agent}</dd>
          </>
        ) : null}
        {tone ? (
          <>
            <dt className="text-muted">Status</dt>
            <dd>{STATUS_WORD[span.status]}</dd>
          </>
        ) : null}
        <dt className="text-muted">Started</dt>
        <dd className="font-mono">
          <time dateTime={span.startTs}>{new Date(span.startTs).toLocaleTimeString()}</time>
        </dd>
        {span.durationMs !== undefined ? (
          <>
            <dt className="text-muted">Latency</dt>
            <dd className="font-mono tabular-nums">{formatDuration(span.durationMs)}</dd>
          </>
        ) : null}
      </dl>
      {span.evidenceIds.length ? (
        <div className="flex flex-col gap-1">
          <p className="qc-eyebrow">Evidence ({span.evidenceIds.length})</p>
          <div className="flex flex-wrap gap-1">
            {span.evidenceIds.map((id) =>
              onEvidence ? (
                <button
                  key={id}
                  type="button"
                  onClick={() => onEvidence(id)}
                  className="rounded border border-border bg-surface px-1.5 py-0.5 font-mono text-[11px] text-link hover:border-border-strong"
                >
                  {id}
                </button>
              ) : (
                <span key={id} className="rounded border border-border bg-surface px-1.5 py-0.5 font-mono text-[11px]">
                  {id}
                </span>
              ),
            )}
          </div>
        </div>
      ) : null}
      <details>
        <summary className="cursor-pointer text-muted hover:text-ink">Raw events ({span.events.length})</summary>
        <pre className="mt-2 max-h-64 overflow-auto rounded border border-border bg-surface p-2 font-mono text-[11px] leading-relaxed">
          {JSON.stringify(
            span.events.map((e) => ({ seq: e.seq, ts: e.ts, type: e.type, payload: e.payload })),
            null,
            2,
          )}
        </pre>
      </details>
    </div>
  );
}

/** LangSmith-style trace of one run: a collapsible span tree with a latency waterfall, where any
 * row expands into its details. Replaces the flat timeline; the region keeps its name. */
export function TraceView({
  events,
  live,
  active,
  onEvidence,
}: {
  events: RunEvent[];
  live: boolean;
  active: boolean;
  onEvidence?: (evidenceId: string) => void;
}) {
  const trace = useMemo(() => buildTrace(events, { active }), [events, active]);
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set());
  const [open, setOpen] = useState<string | null>(null);
  const [showEvents, setShowEvents] = useState(true);
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

  const rows = flattenTrace(trace, collapsed).filter((r) => showEvents || r.span.kind !== "event");
  const stats = traceStats(trace);
  const start = Date.parse(trace.startTs);
  const end = trace.endTs ? Date.parse(trace.endTs) : mounted ? Math.max(now, start + 1) : start + 1;
  const total = Math.max(end - start, 1);
  const elapsed = trace.durationMs ?? (events.length && mounted ? end - start : undefined);

  const toggle = (id: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const parents = trace.children.filter((c) => c.children.length);

  return (
    <section aria-label="Agent timeline" className="qc-panel flex min-w-0 flex-col">
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
            <button type="button" onClick={() => setShowEvents((v) => !v)} aria-pressed={!showEvents} className="qc-btn-ghost px-2 py-0.5 text-xs">
              {showEvents ? "Hide logs" : "Show logs"}
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
        <ol className="max-h-[70vh] overflow-y-auto py-1">
          {rows.map(({ span, depth }) => {
            const isOpen = open === span.id;
            const spanStart = Date.parse(span.startTs) - start;
            const duration = span.durationMs ?? (span.status === "running" && mounted ? now - Date.parse(span.startTs) : undefined);
            const word = STATUS_WORD[span.status];
            const tone = describe(span.events[0] as RunEvent).tone;
            const nameClass =
              span.kind === "event"
                ? span.status === "error"
                  ? "text-rejected"
                  : tone === "muted"
                    ? "text-muted"
                    : "text-ink"
                : "font-mono text-[13px] text-ink";
            return (
              <Fragment key={span.id}>
                <li className={`group flex min-w-0 items-center gap-1 pr-3 ${isOpen ? "bg-accent-tint" : "hover:bg-hover"}`}>
                  <span aria-hidden="true" style={{ width: depth * 16 + 4 }} className="shrink-0" />
                  {span.children.length ? (
                    <button
                      type="button"
                      onClick={() => toggle(span.id)}
                      aria-expanded={!collapsed.has(span.id)}
                      aria-label={`${collapsed.has(span.id) ? "Expand" : "Collapse"} ${span.name}`}
                      className="flex size-5 items-center justify-center rounded text-muted hover:text-ink"
                    >
                      <Icon name={collapsed.has(span.id) ? "chevronRight" : "chevronDown"} size={12} />
                    </button>
                  ) : (
                    <span aria-hidden="true" className="size-5 shrink-0" />
                  )}
                  <button
                    type="button"
                    onClick={() => setOpen(isOpen ? null : span.id)}
                    aria-expanded={isOpen}
                    className="flex min-w-0 flex-1 items-center gap-2 py-1.5 text-left"
                  >
                    <SpanGlyph span={span} />
                    <span className={`min-w-0 truncate text-sm ${nameClass}`} title={span.name}>
                      {span.name}
                    </span>
                    {span.kind === "tool" && span.agent ? <span className="hidden truncate text-xs text-muted sm:inline">{span.agent}</span> : null}
                    {word && span.kind !== "event" && span.status !== "ok" ? <span className="sr-only">({word})</span> : null}
                    {span.evidenceIds.length ? (
                      <span className="shrink-0 rounded border border-border px-1 font-mono text-[10px] text-muted">{span.evidenceIds.length} ev</span>
                    ) : null}
                  </button>
                  {span.kind !== "event" ? (
                    <span className="hidden w-16 shrink-0 sm:block" aria-hidden="true">
                      <span className="relative block h-1.5 rounded-full bg-surface-2">
                        <span
                          className={`absolute top-0 h-1.5 rounded-full ${
                            span.status === "error" ? "bg-rejected" : span.status === "running" ? "bg-running" : span.kind === "tool" ? "bg-faint" : "bg-accent"
                          }`}
                          style={{
                            left: `${Math.min(98, (spanStart / total) * 100)}%`,
                            width: `${Math.max(2, ((duration ?? 0) / total) * 100)}%`,
                          }}
                        />
                      </span>
                    </span>
                  ) : null}
                  <span className="w-14 shrink-0 text-right font-mono text-[11px] text-muted tabular-nums">
                    {span.kind === "event" ? (
                      <time dateTime={span.startTs} title={span.startTs}>
                        {formatDuration(Date.parse(span.startTs) - start)}
                      </time>
                    ) : duration !== undefined ? (
                      formatDuration(duration)
                    ) : (
                      ""
                    )}
                  </span>
                </li>
                {isOpen ? (
                  <li style={{ paddingLeft: depth * 16 + 28 }} className="pr-3 pb-1">
                    <SpanDetails span={span} onEvidence={onEvidence} />
                  </li>
                ) : null}
              </Fragment>
            );
          })}
        </ol>
      )}
    </section>
  );
}
