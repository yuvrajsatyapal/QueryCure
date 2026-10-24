"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useState, type KeyboardEvent } from "react";
import { ErrorNotice } from "@/components/common/ErrorNotice";
import { SqlEditor } from "@/components/editor/SqlEditor";
import { ParamSetsEditor, parseParamSets, type ParamSetRow } from "@/components/investigation/ParamSetsEditor";
import { NodeDetails } from "@/components/plan/NodeDetails";
import { PlanExplorer, type PlanView } from "@/components/plan/PlanExplorer";
import { stopsEarly } from "@/lib/plan/analysis";
import { connectionKeys, explainOnConnection, listConnections } from "@/lib/api/connections";
import { inspectPlan, inspectSql } from "@/lib/api/inspect";
import { createInvestigation, getModels, investigationKeys } from "@/lib/api/investigations";
import { listWorkloads, optimizationKeys } from "@/lib/api/optimization";
import type { CreateInvestigationInput, NodeMetrics, PlanTree, SqlAnalysis } from "@/lib/api/types";
import { suggestTitle } from "@/lib/investigations/title";
import { buildCreateInput, modeOptions, resolveMode, type Mode, type PlanSource } from "@/lib/investigations/wizard";
import { PlanSourceStep, type WorkloadPick } from "./PlanSourceStep";
import { WizardStep, type StepState } from "./WizardStep";

interface PlanResult {
  plan: PlanTree;
  metrics: NodeMetrics[];
  origin: string;
  source: PlanSource;
  /** What the plan was produced from (plan text, or connection + SQL): a later edit makes it stale. */
  input: string;
  artifactSha256?: string;
}

const STEPS = ["SQL query", "Plan source", "Investigation mode", "Review & start"] as const;
const SOURCE_LABEL: Record<PlanSource, string> = {
  upload: "Uploaded plan",
  live: "Live EXPLAIN",
  workload: "Demo workload",
  none: "No plan",
};
const MODE_COPY: Record<Mode, { label: string; detail: string }> = {
  offline: { label: "Offline", detail: "Agents analyse the SQL and any uploaded plan. Nothing is executed or benchmarked." },
  live_inspection: {
    label: "Live inspection",
    detail: "Plain EXPLAIN and catalog reads on your connection in a read-only transaction. The query is never executed.",
  },
  sandbox_benchmark: {
    label: "Sandbox benchmark",
    detail: "Candidates are benchmarked in a disposable sandbox copy of the demo workload, only after you approve their exact SQL.",
  },
};
const isMac = () => typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

export function Workspace() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [reached, setReached] = useState(0);
  const [moved, setMoved] = useState(false);

  const [query, setQuery] = useState("SELECT * FROM orders WHERE customer_id = 1024 ORDER BY created_at DESC LIMIT 20");
  const [checked, setChecked] = useState<{ query: string; analysis: SqlAnalysis } | null>(null);

  const [source, setSource] = useState<PlanSource>("upload");
  const [planText, setPlanText] = useState("");
  const [connectionId, setConnectionId] = useState("");
  const [workload, setWorkload] = useState<WorkloadPick>({ name: "", scale: "0.1", example: 0 });
  const [replacedQuery, setReplacedQuery] = useState(false);
  const [result, setResult] = useState<PlanResult | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [view, setView] = useState<PlanView>("tree");

  const [chosenMode, setChosenMode] = useState<Mode | null>(null);
  const [objective, setObjective] = useState("Why is this query slow, and what should change?");
  const [rows, setRows] = useState<ParamSetRow[]>([{ name: "", values: "" }]);
  const [preAuthorize, setPreAuthorize] = useState(false);
  const [title, setTitle] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  // One key per form instance: retries and double submits reuse it (API idempotency).
  const [idempotencyKey] = useState(() => crypto.randomUUID());

  const workloads = useQuery({
    queryKey: optimizationKeys.workloads,
    queryFn: ({ signal }) => listWorkloads(signal),
    enabled: source === "workload",
  });
  const connections = useQuery({
    queryKey: connectionKeys.all,
    queryFn: ({ signal }) => listConnections(signal),
    enabled: source === "live",
  });
  const models = useQuery({ queryKey: investigationKeys.models, queryFn: ({ signal }) => getModels(signal) });

  const spec = workloads.data?.items.find((w) => w.name === workload.name);
  const workloadId = spec ? `${spec.id}:sf=${workload.scale}:seed=${spec.defaultSeed}` : undefined;
  const choice = {
    source,
    connectionId: connectionId || undefined,
    workloadId: source === "workload" ? workloadId : undefined,
  };
  const mode = resolveMode(chosenMode, choice);
  const analysis = checked !== null && checked.query === query ? checked.analysis : null;
  const fresh = analysis !== null;
  const suggestion = suggestTitle(query);

  const check = useMutation({
    mutationFn: (sql: string) => inspectSql(sql),
    onSuccess: (analysis, sql) => setChecked({ query: sql, analysis }),
  });
  const show = (plan: PlanTree, metrics: NodeMetrics[], origin: string, from: PlanSource, input: string, artifactSha256?: string) => {
    setResult({ plan, metrics, origin, source: from, input, artifactSha256 });
    setSelected(null);
    setFormError(null);
  };
  const liveInput = (id: string, sql: string) => `${id}\n${sql}`;
  const analyze = useMutation({
    mutationFn: (text: string) => inspectPlan(text),
    onSuccess: (r, text) =>
      show(r.plan, r.metrics, `uploaded plan · artifact ${r.artifactSha256.slice(0, 12)}`, "upload", text, r.artifactSha256),
  });
  const explain = useMutation({
    mutationFn: (v: { connectionId: string; query: string }) => explainOnConnection(v.connectionId, v.query),
    onSuccess: (r, v) =>
      show(r.plan, r.metrics, r.genericPlan ? "live EXPLAIN · generic plan" : "live EXPLAIN", "live", liveInput(v.connectionId, v.query)),
  });
  const start = useMutation({
    mutationFn: (input: CreateInvestigationInput) => createInvestigation(input, idempotencyKey),
    onSuccess: (r) => router.push(`/app/investigations/${r.investigation.id}`),
  });

  // Review never starts on a stale check: the SQL may have changed since step 1 (a workload example).
  const { mutate: runCheck, isPending: checking, isError: checkFailed } = check;
  useEffect(() => {
    if (step === 3 && !fresh && !checking && !checkFailed && query.trim() !== "") runCheck(query);
  }, [step, fresh, checking, checkFailed, query, runCheck]);

  // `shown` is what the plan panel displays; `current` is the plan for the inputs as they are now. A response
  // that arrives after the plan text, connection or SQL changed is displayed but never counts as ready.
  const shown = result && result.source === source ? result : null;
  const sourceInput = source === "upload" ? planText : liveInput(connectionId, query);
  const current = shown && shown.input === sourceInput ? shown : null;
  const sourcePending = (source === "upload" && analyze.isPending) || (source === "live" && explain.isPending);
  const sourceReady =
    source === "none" ||
    (source === "workload" && Boolean(workloadId)) ||
    (source === "upload" && current !== null) ||
    (source === "live" && connectionId !== "" && current !== null);
  const sourceBlocker = sourceReady
    ? null
    : source === "upload"
      ? shown
        ? "The plan changed since it was analyzed: analyze it again, or choose No plan."
        : "Analyze a plan first, or choose No plan."
      : source === "live"
        ? shown
          ? "The connection or SQL changed since EXPLAIN ran: run EXPLAIN again."
          : "Choose a connection and run EXPLAIN first."
        : "Choose a demo workload.";

  function go(next: number) {
    setMoved(true);
    setFormError(null);
    setStep(next);
    setReached((r) => Math.max(r, next));
  }

  function onQueryChange(sql: string) {
    setQuery(sql);
    if (check.isError) check.reset();
  }

  function pickWorkload(name: string, index = 0) {
    const chosen = workloads.data?.items.find((w) => w.name === name);
    setWorkload((w) => ({ ...w, name, example: index }));
    const picked = chosen?.exampleQueries[index];
    if (picked) {
      setReplacedQuery(picked.sql !== query);
      setQuery(picked.sql);
      setRows(picked.paramSets.map((p) => ({ name: p.name, values: JSON.stringify(p.values), edgeCase: p.edgeCase })));
    }
  }

  function continueFromSql() {
    if (query.trim() === "") return setFormError("Enter the SQL query to investigate.");
    if (fresh) return go(1);
    check.mutate(query, { onSuccess: () => go(1) });
  }

  function continueFromSource() {
    // The keyboard shortcut bypasses the disabled button: a pending analysis neither advances nor errors.
    if (sourcePending) return;
    if (sourceBlocker) return setFormError(sourceBlocker);
    go(2);
  }

  function continueFromMode() {
    if (objective.trim() === "") return setFormError("Describe the objective.");
    const { error } = parseParamSets(rows);
    if (error) return setFormError(error);
    go(3);
  }

  function submit() {
    const finalTitle = title.trim() || suggestion;
    if (!finalTitle) return setFormError("Give the investigation a title.");
    if (!fresh) return setFormError("The SQL query has not passed the check yet.");
    const { sets, error } = parseParamSets(rows);
    if (error) return setFormError(error);
    setFormError(null);
    start.mutate(
      buildCreateInput({
        title: finalTitle,
        objective: objective.trim(),
        query,
        paramSets: sets,
        mode,
        source: choice,
        planArtifactSha256: current?.artifactSha256,
        preAuthorize,
      }),
    );
  }

  const advance = [continueFromSql, continueFromSource, continueFromMode, submit][step] ?? submit;

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    // CodeMirror keeps its own Mod-Enter (insert blank line); everywhere else it advances the flow.
    const mod = isMac() ? event.metaKey : event.ctrlKey;
    if (event.key !== "Enter" || !mod || event.defaultPrevented) return;
    if (event.target instanceof HTMLElement && event.target.closest(".cm-editor")) return;
    event.preventDefault();
    advance();
  }

  const state = (i: number): StepState => (i === step ? "active" : i <= reached ? "done" : "upcoming");
  const parsedSets = parseParamSets(rows);
  const paramCount = analysis ? analysis.metadata.parameterCount : null;
  const tables = analysis ? analysis.metadata.tables.map((t) => t.name) : [];
  const selectedNode = shown?.plan.nodes.find((n) => n.id === selected);
  const continueButton = (label: string, pending?: boolean, pendingLabel?: string, blocked?: string | null) => (
    <div className="flex flex-wrap items-center gap-3">
      <button
        type="button"
        onClick={advance}
        disabled={pending || Boolean(blocked)}
        aria-describedby={blocked ? (formError ? "wizard-error" : "wizard-hint") : undefined}
        className="qc-btn-primary"
      >
        {pending ? pendingLabel : label}
      </button>
      {blocked && !pending && !formError ? (
        <span id="wizard-hint" className="text-xs text-muted">
          {blocked}
        </span>
      ) : null}
      <span className="hidden text-xs text-muted sm:inline">
        <kbd className="font-mono">{isMac() ? "⌘" : "Ctrl"}</kbd>+<kbd className="font-mono">Enter</kbd>
      </span>
    </div>
  );
  const alert = formError ? (
    <p id="wizard-error" role="alert" className="text-sm text-rejected">
      {formError}
    </p>
  ) : null;

  return (
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(380px,0.95fr)_1.35fr]">
      <div className="flex min-w-0 flex-col gap-4" onKeyDown={onKeyDown}>
        <div>
          <h1 className="text-xl font-semibold tracking-tight">New investigation</h1>
          <p className="mt-1 text-sm text-muted">
            Four steps: the query, where its plan comes from, what agents may do, then review. Agents cite evidence;
            demo workloads can be benchmarked in the sandbox.
          </p>
        </div>
        <ol aria-label="New investigation steps" className="flex flex-col">
          <WizardStep
            index={0}
            title={STEPS[0]}
            state={state(0)}
            focusOnOpen={moved}
            onEdit={() => go(0)}
            summary={
              <span className="flex flex-col gap-1">
                <code className="block truncate font-mono text-xs text-ink">{query.trim().split("\n")[0]}</code>
                {analysis ? (
                  <span>
                    {analysis.statementType.toUpperCase()} · {tables.join(", ") || "no tables"} · {paramCount} parameter
                    {paramCount === 1 ? "" : "s"}
                  </span>
                ) : (
                  <span className="text-inconclusive">Changed since the check: it runs again before you start.</span>
                )}
              </span>
            }
          >
            <div className="overflow-hidden rounded-md border border-border">
              <SqlEditor value={query} onChange={onQueryChange} />
            </div>
            <p className="text-xs text-muted">
              One SELECT statement. It is checked with the same rules the server applies when the investigation starts.
              Press <kbd className="font-mono">Tab</kbd> to leave the editor.
            </p>
            {analysis ? (
              <p role="status" className="text-xs text-verified">
                Checked: {analysis.statementType.toUpperCase()} on {tables.join(", ") || "no tables"} · {paramCount} parameter
                {paramCount === 1 ? "" : "s"}
              </p>
            ) : null}
            <ErrorNotice error={check.error} />
            {alert}
            {continueButton("Check and continue", check.isPending, "Checking…")}
          </WizardStep>

          <WizardStep
            index={1}
            title={STEPS[1]}
            state={state(1)}
            focusOnOpen={moved}
            onEdit={() => go(1)}
            summary={
              <span>
                {SOURCE_LABEL[source]}
                {source === "workload" && workloadId ? <span className="font-mono"> · {workloadId}</span> : null}
                {source === "live" ? ` · ${connections.data?.items.find((c) => c.id === connectionId)?.name ?? "connection"}` : null}
                {current ? ` · ${current.plan.nodes.length} plan nodes` : null}
              </span>
            }
          >
            <PlanSourceStep
              source={source}
              onSource={(s) => {
                setSource(s);
                setFormError(null);
              }}
              planText={planText}
              onPlanText={setPlanText}
              onAnalyze={() => analyze.mutate(planText)}
              analyzing={analyze.isPending}
              analyzeFailed={analyze.isError && analyze.variables === planText}
              connectionId={connectionId}
              onConnection={setConnectionId}
              connections={connections.data}
              connectionsLoading={connections.isPending}
              onExplain={() => explain.mutate({ connectionId, query })}
              explaining={explain.isPending}
              explainFailed={explain.isError && explain.variables?.connectionId === connectionId && explain.variables.query === query}
              queryBlank={query.trim() === ""}
              workloads={workloads.data}
              workloadsLoading={workloads.isPending}
              workload={workload}
              onPickWorkload={pickWorkload}
              onScale={(scale) => setWorkload((w) => ({ ...w, scale }))}
              replacedQuery={replacedQuery}
              error={source === "upload" ? analyze.error : source === "live" ? explain.error : workloads.error}
            />
            {alert}
            {continueButton("Continue", sourcePending, source === "live" ? "Running EXPLAIN…" : "Analyzing plan…", sourceBlocker)}
          </WizardStep>

          <WizardStep
            index={2}
            title={STEPS[2]}
            state={state(2)}
            focusOnOpen={moved}
            onEdit={() => go(2)}
            summary={
              <span>
                {MODE_COPY[mode].label} · {parsedSets.sets.length} parameter set{parsedSets.sets.length === 1 ? "" : "s"}
              </span>
            }
          >
            <fieldset className="flex flex-col gap-2">
              <legend className="mb-2 text-sm text-muted">What may agents do?</legend>
              {modeOptions(choice).map((o) => (
                <label
                  key={o.mode}
                  className={`flex gap-2.5 rounded-md border p-3 text-sm has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent ${
                    !o.available
                      ? "cursor-not-allowed border-border opacity-70"
                      : mode === o.mode
                        ? "cursor-pointer border-accent bg-accent-tint"
                        : "cursor-pointer border-border bg-surface hover:border-border-strong"
                  }`}
                >
                  <input
                    type="radio"
                    name="investigation-mode"
                    value={o.mode}
                    checked={mode === o.mode}
                    disabled={!o.available}
                    onChange={() => setChosenMode(o.mode)}
                    aria-describedby={`mode-${o.mode}`}
                    className="mt-0.5 accent-[var(--accent)]"
                  />
                  <span className="flex flex-col gap-0.5">
                    <span className="font-medium text-ink">{MODE_COPY[o.mode].label}</span>
                    <span id={`mode-${o.mode}`} className="text-xs text-muted">
                      {o.available ? MODE_COPY[o.mode].detail : o.reason}
                    </span>
                  </span>
                </label>
              ))}
            </fieldset>
            <label className="flex flex-col gap-1 text-sm">
              Objective
              <textarea value={objective} onChange={(e) => setObjective(e.target.value)} maxLength={2000} rows={2} className="qc-input" />
            </label>
            {paramCount !== null && paramCount > 0 ? (
              <p className="text-xs text-muted">
                The query has {paramCount} placeholder{paramCount === 1 ? "" : "s"}: each parameter set needs {paramCount} value
                {paramCount === 1 ? "" : "s"}.
              </p>
            ) : null}
            <ParamSetsEditor rows={rows} onChange={setRows} />
            {mode === "sandbox_benchmark" ? (
              <label className="flex items-center gap-2 text-xs">
                <input type="checkbox" checked={preAuthorize} onChange={(e) => setPreAuthorize(e.target.checked)} />
                Pre-authorize sandbox experiments for this demo workload (an approval record is still kept)
              </label>
            ) : null}
            {alert}
            {continueButton("Continue")}
          </WizardStep>

          <WizardStep index={3} title={STEPS[3]} state={state(3)} focusOnOpen={moved}>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 rounded-md border border-border bg-surface p-3 text-sm">
              {(
                [
                  ["SQL", <code key="sql" className="block truncate font-mono text-xs">{query.trim().split("\n")[0]}</code>, 0],
                  ["Plan source", `${SOURCE_LABEL[source]}${current ? ` · ${current.origin}` : ""}${source === "workload" && workloadId ? ` · ${workloadId}` : ""}`, 1],
                  ["Mode", MODE_COPY[mode].label, 2],
                  ["Objective", objective.trim(), 2],
                  ["Parameter sets", parsedSets.sets.map((s) => s.name).join(", ") || "none", 2],
                ] as const
              ).map(([label, value, target]) => (
                <div key={label} className="contents">
                  <dt className="text-muted">{label}</dt>
                  <dd className="flex min-w-0 items-start justify-between gap-2">
                    <span className="min-w-0 break-words">{value}</span>
                    <button type="button" onClick={() => go(target)} className="qc-btn-ghost shrink-0 px-2 py-0.5 text-xs" aria-label={`Edit ${label}`}>
                      Edit
                    </button>
                  </dd>
                </div>
              ))}
            </dl>
            <p className="text-xs text-muted">
              {MODE_COPY[mode].detail}
              {mode === "sandbox_benchmark" && preAuthorize ? " Sandbox experiments are pre-authorized; an approval record is still kept." : ""}
            </p>
            <label className="flex flex-col gap-1 text-sm" htmlFor="investigation-title">
              Title
              <input
                id="investigation-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                maxLength={200}
                placeholder={suggestion ?? "Name this investigation"}
                aria-describedby="title-hint"
                className="qc-input"
              />
            </label>
            <p id="title-hint" className="-mt-2 flex flex-wrap items-center gap-x-2 text-xs text-muted">
              {suggestion ? (
                <>
                  <span>
                    Suggested from the SQL: <span className="font-mono text-ink">{suggestion}</span>. Leave blank to use it.
                  </span>
                  {title === "" ? (
                    <button type="button" onClick={() => setTitle(suggestion)} className="text-link underline underline-offset-2">
                      Edit suggestion
                    </button>
                  ) : null}
                </>
              ) : (
                "No title could be suggested from this SQL; enter one."
              )}
            </p>
            {models.data ? (
              <p className={`text-xs ${models.data.configured ? "text-muted" : "text-inconclusive"}`}>
                {models.data.configured
                  ? `Model: ${models.data.model} (free, via ${models.data.provider})`
                  : `No API key configured for ${models.data.provider}: the run will stop with a configuration error.`}
              </p>
            ) : null}
            {check.isPending ? <p role="status" className="text-xs text-muted">Checking the SQL again…</p> : null}
            {step === 3 ? <ErrorNotice error={check.error} /> : null}
            {alert}
            <ErrorNotice error={start.error} />
            {continueButton("Start investigation", start.isPending || !fresh, start.isPending ? "Starting…" : "Start investigation")}
          </WizardStep>
        </ol>
      </div>

      <section aria-label="Plan" className="flex min-w-0 flex-col gap-4">
        {shown ? (
          <PlanExplorer
            plan={shown.plan}
            metrics={shown.metrics}
            selectedId={selected}
            onSelect={setSelected}
            view={view}
            onViewChange={setView}
            label={shown.origin}
            details={
              selectedNode ? (
                <NodeDetails node={selectedNode} stoppedEarly={stopsEarly(shown.plan, selectedNode.id)} metrics={shown.metrics.find((m) => m.nodeId === selectedNode.id)} />
              ) : (
                <p className="text-sm text-muted">Select a node to see its details.</p>
              )
            }
          />
        ) : analyze.isPending || explain.isPending ? (
          <div className="qc-panel p-4">
            <p className="sr-only" role="status">Loading the plan…</p>
            <div aria-hidden="true" className="flex flex-col gap-2">
              {[0, 1, 2, 3].map((i) => (
                <span key={i} className="qc-pulse block h-6 rounded bg-surface-2" style={{ marginLeft: `${i * 16}px` }} />
              ))}
            </div>
          </div>
        ) : (
          <p className="qc-panel p-6 text-muted">
            {source === "workload"
              ? "No plan preview for a demo workload."
              : source === "none"
                ? "No plan: agents work from the SQL text."
                : "No plan yet. In Plan source, paste EXPLAIN (FORMAT JSON) output or run a live EXPLAIN on a connection."}
          </p>
        )}
      </section>
    </div>
  );
}
