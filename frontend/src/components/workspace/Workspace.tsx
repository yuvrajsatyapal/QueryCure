"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type ChangeEvent } from "react";
import { ErrorNotice } from "@/components/common/ErrorNotice";
import { SqlEditor } from "@/components/editor/SqlEditor";
import { NodeDetails } from "@/components/plan/NodeDetails";
import { PlanGraph } from "@/components/plan/PlanGraph";
import { PlanTreeTable } from "@/components/plan/PlanTreeTable";
import { connectionKeys, explainOnConnection, listConnections } from "@/lib/api/connections";
import { inspectPlan } from "@/lib/api/inspect";
import type { NodeMetrics, PlanTree } from "@/lib/api/types";

type Source = "upload" | "live";
type View = "tree" | "graph";
interface PlanResult {
  plan: PlanTree;
  metrics: NodeMetrics[];
  origin: string;
}

const MAX_PLAN_CHARS = 5 * 1024 * 1024;
const tabClass = (active: boolean) =>
  `rounded-md px-3 py-1.5 text-sm ${active ? "bg-accent-tint font-medium text-ink" : "text-muted hover:text-ink"}`;

export function Workspace() {
  const [query, setQuery] = useState(
    "SELECT * FROM orders WHERE customer_id = 1024 ORDER BY created_at DESC LIMIT 20",
  );
  const [source, setSource] = useState<Source>("upload");
  const [planText, setPlanText] = useState("");
  const [connectionId, setConnectionId] = useState("");
  const [result, setResult] = useState<PlanResult | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [view, setView] = useState<View>("tree");

  const connections = useQuery({
    queryKey: connectionKeys.all,
    queryFn: ({ signal }) => listConnections(signal),
    enabled: source === "live",
  });

  const show = (plan: PlanTree, metrics: NodeMetrics[], origin: string) => {
    setResult({ plan, metrics, origin });
    setSelected(null);
  };
  const analyze = useMutation({
    mutationFn: () => inspectPlan(planText),
    onSuccess: (r) => show(r.plan, r.metrics, `uploaded plan · artifact ${r.artifactSha256.slice(0, 12)}`),
  });
  const explain = useMutation({
    mutationFn: () => explainOnConnection(connectionId, query),
    onSuccess: (r) => show(r.plan, r.metrics, r.genericPlan ? "live EXPLAIN · generic plan" : "live EXPLAIN"),
  });

  async function onFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) setPlanText(await file.text());
  }

  const selectedNode = result?.plan.nodes.find((n) => n.id === selected);
  const error = source === "upload" ? analyze.error : explain.error;

  return (
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(360px,0.9fr)_1.4fr]">
      <section aria-label="Query and plan source" className="flex min-w-0 flex-col gap-4">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold">Workspace</h1>
          <button
            type="button"
            disabled
            title="Investigations arrive in Phase 2"
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-fg opacity-50"
          >
            Start investigation
          </button>
        </div>
        <p className="text-sm text-muted">
          Multi-agent investigations arrive in Phase 2. Today you can inspect a plan from an upload or a
          live, read-only EXPLAIN.
        </p>
        <SqlEditor value={query} onChange={setQuery} />
        <div role="tablist" aria-label="Plan source" className="flex gap-2">
          <button role="tab" aria-selected={source === "upload"} className={tabClass(source === "upload")} onClick={() => setSource("upload")}>
            Upload plan
          </button>
          <button role="tab" aria-selected={source === "live"} className={tabClass(source === "live")} onClick={() => setSource("live")}>
            Live EXPLAIN
          </button>
        </div>
        {source === "upload" ? (
          <div className="flex flex-col gap-2">
            <label className="text-sm text-muted" htmlFor="plan-json">
              Plan JSON
            </label>
            <textarea
              id="plan-json"
              aria-label="Plan JSON"
              value={planText}
              onChange={(e) => setPlanText(e.target.value)}
              rows={8}
              spellCheck={false}
              placeholder='Paste EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) output: [{"Plan": …}]'
              className="w-full rounded-md border border-border-strong bg-surface p-3 font-mono text-xs"
            />
            <div className="flex flex-wrap items-center gap-3">
              <input type="file" accept=".json,application/json" onChange={onFile} aria-label="Plan file" className="text-sm" />
              <button
                type="button"
                onClick={() => analyze.mutate()}
                disabled={analyze.isPending || planText.trim() === "" || planText.length > MAX_PLAN_CHARS}
                className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-fg disabled:opacity-60"
              >
                {analyze.isPending ? "Analyzing…" : "Analyze plan"}
              </button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            <label className="text-sm text-muted" htmlFor="connection">
              Connection
            </label>
            <select
              id="connection"
              value={connectionId}
              onChange={(e) => setConnectionId(e.target.value)}
              className="rounded-md border border-border-strong bg-surface px-3 py-2 text-sm"
            >
              <option value="">Choose a connection…</option>
              {(connections.data?.items ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} ({c.environment})
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => explain.mutate()}
              disabled={explain.isPending || connectionId === "" || query.trim() === ""}
              className="w-fit rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-fg disabled:opacity-60"
            >
              {explain.isPending ? "Running EXPLAIN…" : "Run EXPLAIN"}
            </button>
            <p className="text-xs text-muted">Plain EXPLAIN only: the query is planned, never executed.</p>
          </div>
        )}
        <ErrorNotice error={error} />
      </section>
      <section aria-label="Plan" className="flex min-w-0 flex-col gap-4">
        {result ? (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="font-mono text-xs uppercase tracking-wider text-muted">{result.origin}</p>
              <div role="tablist" aria-label="Plan view" className="flex gap-2">
                <button role="tab" aria-selected={view === "tree"} className={tabClass(view === "tree")} onClick={() => setView("tree")}>
                  Tree
                </button>
                <button role="tab" aria-selected={view === "graph"} className={tabClass(view === "graph")} onClick={() => setView("graph")}>
                  Graph
                </button>
              </div>
            </div>
            {view === "tree" ? (
              <PlanTreeTable plan={result.plan} metrics={result.metrics} onSelect={setSelected} selectedId={selected} />
            ) : (
              <PlanGraph plan={result.plan} metrics={result.metrics} onSelect={setSelected} selectedId={selected} />
            )}
            {selectedNode ? (
              <NodeDetails node={selectedNode} metrics={result.metrics.find((m) => m.nodeId === selectedNode.id)} />
            ) : (
              <p className="text-sm text-muted">Select a node to see its details.</p>
            )}
          </>
        ) : (
          <p className="rounded-lg border border-border bg-surface p-6 text-muted">
            No plan yet. Paste EXPLAIN (FORMAT JSON) output, or run a live EXPLAIN on a connection.
          </p>
        )}
      </section>
    </div>
  );
}
