"use client";

import type { ChangeEvent } from "react";
import { ErrorNotice } from "@/components/common/ErrorNotice";
import { Skeleton } from "@/components/ui/Skeleton";
import type { ConnectionSummary, WorkloadCatalog } from "@/lib/api/types";
import type { PlanSource } from "@/lib/investigations/wizard";

export const MAX_PLAN_CHARS = 5 * 1024 * 1024;

export interface WorkloadPick {
  name: string;
  scale: string;
  example: number;
}

const SOURCES: { id: PlanSource; label: string; hint: string }[] = [
  { id: "upload", label: "Upload plan", hint: "Paste EXPLAIN (FORMAT JSON) output or choose a file." },
  { id: "live", label: "Live EXPLAIN", hint: "Plan the query on a registered read-only connection. It is never executed." },
  { id: "workload", label: "Demo workload", hint: "Use a demo dataset that can be benchmarked in the sandbox." },
  { id: "none", label: "No plan", hint: "Agents work from the SQL text alone." },
];

export function PlanSourceStep(props: {
  source: PlanSource;
  onSource: (source: PlanSource) => void;
  planText: string;
  onPlanText: (text: string) => void;
  onAnalyze: () => void;
  analyzing: boolean;
  connectionId: string;
  onConnection: (id: string) => void;
  connections: { items: ConnectionSummary[] } | undefined;
  connectionsLoading: boolean;
  onExplain: () => void;
  explaining: boolean;
  queryBlank: boolean;
  workloads: WorkloadCatalog | undefined;
  workloadsLoading: boolean;
  workload: WorkloadPick;
  onPickWorkload: (name: string, example?: number) => void;
  onScale: (scale: string) => void;
  replacedQuery: boolean;
  error: unknown;
}) {
  const { source, workloads, workload } = props;
  const spec = workloads?.items.find((w) => w.name === workload.name);

  async function onFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) props.onPlanText(await file.text());
  }

  return (
    <div className="flex flex-col gap-4">
      <fieldset className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <legend className="sr-only">Plan source</legend>
        {SOURCES.map((s) => (
          <label
            key={s.id}
            className={`flex cursor-pointer gap-2.5 rounded-md border p-3 text-sm has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent ${
              source === s.id ? "border-accent bg-accent-tint" : "border-border bg-surface hover:border-border-strong"
            }`}
          >
            <input
              type="radio"
              name="plan-source"
              value={s.id}
              checked={source === s.id}
              onChange={() => props.onSource(s.id)}
              className="mt-0.5 accent-[var(--accent)]"
            />
            <span className="flex flex-col gap-0.5">
              <span className="font-medium text-ink">{s.label}</span>
              <span className="text-xs text-muted">{s.hint}</span>
            </span>
          </label>
        ))}
      </fieldset>

      {source === "upload" ? (
        <div className="flex flex-col gap-2">
          <label className="text-sm text-muted" htmlFor="plan-json">
            Plan JSON
          </label>
          <textarea
            id="plan-json"
            aria-label="Plan JSON"
            value={props.planText}
            onChange={(e) => props.onPlanText(e.target.value)}
            rows={7}
            spellCheck={false}
            placeholder='Paste EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) output: [{"Plan": …}]'
            className="w-full rounded-md border border-border-strong bg-surface p-3 font-mono text-xs"
          />
          <div className="flex flex-wrap items-center gap-3">
            <input type="file" accept=".json,application/json" onChange={onFile} aria-label="Plan file" className="min-w-0 text-sm" />
            <button
              type="button"
              onClick={props.onAnalyze}
              disabled={props.analyzing || props.planText.trim() === "" || props.planText.length > MAX_PLAN_CHARS}
              className="qc-btn-secondary"
            >
              {props.analyzing ? "Analyzing…" : "Analyze plan"}
            </button>
          </div>
        </div>
      ) : source === "live" ? (
        <div className="flex flex-col gap-2">
          <label className="text-sm text-muted" htmlFor="connection">
            Connection
          </label>
          {props.connectionsLoading ? (
            <Skeleton label="Loading connections" />
          ) : (
            <select id="connection" value={props.connectionId} onChange={(e) => props.onConnection(e.target.value)} className="qc-input">
              <option value="">Choose a connection…</option>
              {(props.connections?.items ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} ({c.environment})
                </option>
              ))}
            </select>
          )}
          {!props.connectionsLoading && (props.connections?.items.length ?? 0) === 0 ? (
            <p className="text-xs text-muted">
              No connections yet. <a href="/app/connections">Add a read-only connection</a> first.
            </p>
          ) : null}
          <button
            type="button"
            onClick={props.onExplain}
            disabled={props.explaining || props.connectionId === "" || props.queryBlank}
            className="w-fit qc-btn-secondary"
          >
            {props.explaining ? "Running EXPLAIN…" : "Run EXPLAIN"}
          </button>
          <p className="text-xs text-muted">Plain EXPLAIN only: the query is planned, never executed.</p>
        </div>
      ) : source === "workload" ? (
        <div className="flex flex-col gap-2">
          <label className="text-sm text-muted" htmlFor="workload">
            Workload
          </label>
          {props.workloadsLoading ? (
            <Skeleton label="Loading demo workloads" />
          ) : (
            <select id="workload" value={workload.name} onChange={(e) => props.onPickWorkload(e.target.value)} className="qc-input">
              <option value="">Choose a demo workload…</option>
              {(workloads?.items ?? []).map((w) => (
                <option key={w.id} value={w.name}>
                  {w.name} — {w.description}
                </option>
              ))}
            </select>
          )}
          {spec ? (
            <>
              <p className="text-xs text-muted">Injected problem: {spec.injectedProblem}</p>
              <div className="flex flex-wrap gap-3">
                <label className="flex items-center gap-2 text-sm">
                  Scale
                  <select
                    aria-label="Scale factor"
                    value={workload.scale}
                    onChange={(e) => props.onScale(e.target.value)}
                    className="rounded-md border border-border-strong bg-surface px-2 py-1 text-sm"
                  >
                    {spec.scaleFactors.map((sf) => (
                      <option key={sf} value={String(sf)}>
                        sf={sf}
                      </option>
                    ))}
                  </select>
                </label>
                {spec.exampleQueries.length > 1 ? (
                  <label className="flex items-center gap-2 text-sm">
                    Query
                    <select
                      aria-label="Example query"
                      value={workload.example}
                      onChange={(e) => props.onPickWorkload(spec.name, Number(e.target.value))}
                      className="rounded-md border border-border-strong bg-surface px-2 py-1 text-sm"
                    >
                      {spec.exampleQueries.map((q, i) => (
                        <option key={q.name} value={i}>
                          {q.name}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}
              </div>
              {props.replacedQuery ? (
                <p role="status" className="text-xs text-muted">
                  The SQL query was replaced with this workload&apos;s example. Edit it in step 1 if needed; it is checked again before you start.
                </p>
              ) : null}
              <p className="text-xs text-muted">
                {spec.availability === "live"
                  ? "Benchmarks run live in the local sandbox after you approve the SQL."
                  : "This deployment has no live sandbox: benchmark results are prerecorded."}
              </p>
            </>
          ) : null}
        </div>
      ) : null}
      <ErrorNotice error={props.error} />
    </div>
  );
}
