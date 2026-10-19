"use client";

import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Icon } from "@/components/ui/Icon";
import { StatusPill } from "@/components/ui/StatusPill";
import { ApiError } from "@/lib/api/client";
import { getEvidence, investigationKeys } from "@/lib/api/investigations";
import type { Span } from "@/lib/events/trace";
import { formatDuration } from "@/lib/format";
import { evidenceIdsOfSpan } from "@/lib/investigation/links";
import { STATUS_TONE, STATUS_WORD, SpanGlyph } from "./TraceTree";

type Tab = "input" | "output" | "metadata" | "evidence";
type Payload = Record<string, unknown>;

const TAB_LABEL: Record<Tab, string> = { input: "Input", output: "Output", metadata: "Metadata", evidence: "Evidence" };

/** A field the browser does not have, said plainly with the reason (never filled in). */
function Unavailable({ label, reason }: { label: string; reason: string }) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-dashed border-border px-3 py-2 text-xs">
      <Icon name="minusCircle" size={13} className="mt-0.5 text-faint" />
      <p>
        <span className="font-medium text-ink">{label}:</span> <span className="text-muted">{reason}</span>
      </p>
    </div>
  );
}

function Fields({ rows }: { rows: [string, ReactNode][] }) {
  const shown = rows.filter(([, v]) => v !== null && v !== undefined && v !== "");
  if (!shown.length) return null;
  return (
    <dl className="grid grid-cols-[minmax(96px,auto)_1fr] gap-x-4 gap-y-1.5 text-sm">
      {shown.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="min-w-0 font-mono text-[13px] break-words">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function value(v: unknown): ReactNode {
  if (v === null || v === undefined) return "null";
  if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") return String(v);
  return <pre className="font-mono text-[12px] whitespace-pre-wrap">{JSON.stringify(v, null, 2)}</pre>;
}

const time = (iso: string | undefined) => (iso ? new Date(iso).toLocaleTimeString(undefined, { hour12: false }) : null);

function EvidenceItem({ runId, id, onOpenEvidence }: { runId: string; id: string; onOpenEvidence: (id: string) => void }) {
  const q = useQuery({
    queryKey: investigationKeys.evidence(runId, id),
    queryFn: ({ signal }) => getEvidence(runId, id, signal),
    staleTime: Infinity,
    retry: false,
  });
  return (
    <li className="flex flex-col gap-1 border-b border-border px-3 py-2 last:border-b-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs">{id}</span>
        {q.data ? (
          <>
            <span className="rounded border border-border px-1.5 text-[11px] text-muted">{q.data.evidence.kind.replaceAll("_", " ")}</span>
            <span className="text-[11px] text-muted">{q.data.evidence.provenance}</span>
          </>
        ) : null}
        {q.data?.evidence.kind === "plan_node" ? (
          <button type="button" onClick={() => onOpenEvidence(id)} className="qc-btn-ghost ml-auto px-2 py-0.5 text-xs text-link">
            Show in plan
            <Icon name="arrowRight" size={12} />
          </button>
        ) : null}
      </div>
      {q.isPending ? <p className="text-xs text-muted">Resolving…</p> : null}
      {q.data ? <p className="text-sm">{q.data.evidence.summary}</p> : null}
      {q.error ? (
        <p role="alert" className="text-xs text-rejected">
          Could not load this evidence{q.error instanceof ApiError ? `: ${q.error.message}` : "."}
        </p>
      ) : null}
    </li>
  );
}

/** The right half of the split trace for any selected step (UI_UX §3.6). Shows only what the
 * run's events recorded; prompts, tool arguments and raw model output are named as unavailable. */
export function StepDetails({
  span,
  runId,
  onBack,
  onSelect,
  onOpenEvidence,
}: {
  span: Span;
  runId: string;
  onBack: () => void;
  onSelect: (spanId: string) => void;
  onOpenEvidence: (evidenceId: string) => void;
}) {
  const [tab, setTab] = useState<Tab>("input");
  const first = span.events[0];
  const lastEvent = span.events.at(-1);
  const start = (first?.payload ?? {}) as Payload;
  const end = (lastEvent?.payload ?? {}) as Payload;
  const tone = STATUS_TONE[span.status];
  const evidence = evidenceIdsOfSpan(span);
  const kindLabel = span.kind === "event" ? (first?.type ?? "event") : span.kind === "node" ? "graph step" : "tool call";
  const isAgent = span.kind === "node" && Boolean(span.agent);

  return (
    <section aria-label="Selection details" className="qc-panel flex min-w-0 flex-col">
      <header className="flex flex-col gap-2 border-b border-border px-4 pt-3">
        <button type="button" onClick={onBack} className="flex w-fit items-center gap-1 text-xs text-muted hover:text-ink">
          <Icon name="chevronRight" size={12} className="rotate-180" />
          Back to run results
        </button>
        <div className="flex flex-wrap items-center gap-2">
          <SpanGlyph span={span} />
          <h2 className={`min-w-0 text-base font-semibold break-words ${span.kind === "event" ? "" : "font-mono"}`}>{span.name}</h2>
          {tone ? <StatusPill tone={tone} label={STATUS_WORD[span.status]} /> : null}
          <span className="text-xs text-muted">{kindLabel}</span>
          {span.durationMs !== undefined ? <span className="ml-auto font-mono text-xs text-muted tabular-nums">{formatDuration(span.durationMs)}</span> : null}
        </div>
        <div role="tablist" aria-label="Step details" className="flex gap-5">
          {(Object.keys(TAB_LABEL) as Tab[]).map((t) => (
            <button
              key={t}
              role="tab"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              className={`-mb-px border-b-2 px-1 pb-2 text-sm ${tab === t ? "border-accent font-medium text-ink" : "border-transparent text-muted hover:text-ink"}`}
            >
              {TAB_LABEL[t]}
              {t === "evidence" && evidence.length ? <span className="ml-1 font-mono text-[11px] text-muted">{evidence.length}</span> : null}
            </button>
          ))}
        </div>
      </header>

      <div role="tabpanel" aria-label={TAB_LABEL[tab]} className="flex flex-col gap-3 p-4">
        {tab === "input" ? (
          span.kind === "node" ? (
            <>
              <Fields rows={[["Node", start.node as string], ["Agent", span.agent ?? "none recorded"], ["Attempt", start.attempt as number]]} />
              {isAgent ? (
                <Unavailable label="Model prompt" reason="not recorded. Only the prompt version is stored, server-side, and it is not sent to the browser." />
              ) : null}
            </>
          ) : span.kind === "tool" ? (
            <>
              <Fields rows={[["Tool", span.name], ["Called by", span.agent ?? "none recorded"], ["Started", time(span.startTs)]]} />
              <Unavailable label="Arguments" reason="stored redacted on the server and not exposed to the browser." />
            </>
          ) : (
            <p className="text-sm text-muted">A log event has no input. Its recorded fields are under Output.</p>
          )
        ) : null}

        {tab === "output" ? (
          span.kind === "event" ? (
            <Fields rows={Object.entries(start).map(([k, v]) => [k, value(v)] as [string, ReactNode])} />
          ) : (
            <>
              <Fields
                rows={[
                  ["Status", span.kind === "tool" && typeof end.status === "string" && span.endTs ? end.status : STATUS_WORD[span.status] || "done"],
                  ["Latency", span.durationMs !== undefined ? formatDuration(span.durationMs) : span.status === "running" ? "still running" : "not recorded"],
                  ["Evidence", span.kind === "tool" ? `${evidence.length} item${evidence.length === 1 ? "" : "s"}` : null],
                ]}
              />
              {span.children.length ? (
                <div className="flex flex-col gap-1">
                  <p className="qc-eyebrow">Recorded during this step ({span.children.length})</p>
                  <ul className="flex flex-col">
                    {span.children.map((c) => (
                      <li key={c.id}>
                        <button
                          type="button"
                          onClick={() => onSelect(c.id)}
                          className="flex w-full min-w-0 items-center gap-2 rounded px-2 py-1 text-left text-sm hover:bg-hover"
                        >
                          <SpanGlyph span={c} />
                          <span className={`min-w-0 truncate ${c.kind === "event" ? "" : "font-mono text-[13px]"}`}>{c.name}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <p className="text-sm text-muted">No tool calls or log events were recorded inside this step.</p>
              )}
              {isAgent ? <Unavailable label="Raw model output" reason="stored server-side as an artifact and not exposed to the browser." /> : null}
              {span.kind === "tool" ? <Unavailable label="Reply to the model" reason="not recorded in the event stream; the evidence it produced is under Evidence." /> : null}
            </>
          )
        ) : null}

        {tab === "metadata" ? (
          <>
            <Fields
              rows={[
                ["Kind", kindLabel],
                ["Span", span.id],
                ["Agent", span.agent],
                ["Status", STATUS_WORD[span.status] || "logged"],
                ["Started", time(span.startTs)],
                ["Ended", time(span.endTs)],
                ["Latency", span.durationMs !== undefined ? formatDuration(span.durationMs) : null],
                ["Attempt", typeof start.attempt === "number" ? start.attempt : null],
                ["Event seq", span.events.map((e) => e.seq).join(", ")],
              ]}
            />
            <details>
              <summary className="cursor-pointer text-xs text-muted hover:text-ink">Raw events ({span.events.length})</summary>
              <pre className="mt-2 max-h-80 overflow-auto rounded border border-border bg-surface-2 p-2 font-mono text-[11px] leading-relaxed">
                {JSON.stringify(
                  span.events.map((e) => ({ seq: e.seq, ts: e.ts, type: e.type, payload: e.payload })),
                  null,
                  2,
                )}
              </pre>
            </details>
          </>
        ) : null}

        {tab === "evidence" ? (
          evidence.length ? (
            <ul className="overflow-hidden rounded-md border border-border">
              {evidence.map((id) => (
                <EvidenceItem key={id} runId={runId} id={id} onOpenEvidence={onOpenEvidence} />
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">This step recorded no evidence IDs.</p>
          )
        ) : null}
      </div>
    </section>
  );
}
