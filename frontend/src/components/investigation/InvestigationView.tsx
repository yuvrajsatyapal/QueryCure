"use client";

import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { ErrorNotice } from "@/components/common/ErrorNotice";
import { NodeDetails } from "@/components/plan/NodeDetails";
import { PlanExplorer, type PlanView } from "@/components/plan/PlanExplorer";
import { stopsEarly } from "@/lib/plan/analysis";
import {
  cancelRun,
  getEvidence,
  getFindings,
  getInvestigation,
  getRun,
  getRunPlans,
  investigationKeys,
} from "@/lib/api/investigations";
import { ApiError } from "@/lib/api/client";
import { getApprovals, getCandidates, getExperiments, optimizationKeys } from "@/lib/api/optimization";
import type { EvidenceDetail } from "@/lib/api/types";
import { ReportPanel } from "@/components/report/ReportPanel";
import { ResultSummary } from "@/components/report/ResultSummary";
import { SUPPORTED_REPORT_SCHEMAS, getReport, reportKeys } from "@/lib/api/reports";
import type { ReportV1 } from "@/lib/report/types";
import { ApprovalCard } from "@/components/tournament/ApprovalCard";
import { TournamentPanel } from "@/components/tournament/TournamentPanel";
import { buildTrace } from "@/lib/events/trace";
import { runRefetchInterval } from "@/lib/events/runEvents";
import { useRunEvents } from "@/lib/events/useRunEvents";
import {
  citationsByNode,
  citedEvidenceIds,
  findSpan,
  indexClaimSpans,
  planTargetOfEvidence,
  stepForClaim,
} from "@/lib/investigation/links";
import { useContextCommands, type Command } from "@/components/command/CommandProvider";
import { Icon } from "@/components/ui/Icon";
import { Skeleton } from "@/components/ui/Skeleton";
import { RunStatusPill } from "@/components/ui/StatusPill";
import { BudgetMeter } from "./BudgetMeter";
import { FindingsPanel } from "./FindingsPanel";
import { runKindLabel } from "./RunPicker";
import { RunSelector } from "./RunSelector";
import { StepDetails } from "./StepDetails";
import { TraceTree } from "./TraceTree";

type Tab = "plan" | "findings" | "tournament" | "report";
const ACTIVE = new Set(["queued", "running", "awaiting_approval", "cancelling"]);
const RUN_ROW = "run";
const NO_COMMANDS: Command[] = [];
// Underlined tabs for the results area (Linear), pill segments for the small plan-view switch.
const tabClass = (active: boolean) =>
  `-mb-px border-b-2 px-1 pb-2 text-sm ${active ? "border-accent font-medium text-ink" : "border-transparent text-muted hover:text-ink"}`;

/** `requestedRunId` comes from `?run=` so a selected run (an older run, a replay) is linkable.
 * Layout (UI_UX §3.6): sticky header, then a split trace: the step tree on the left, details of
 * the selected row on the right. The run row (the default) shows the run results tabs. */
export function InvestigationView({ id, requestedRunId }: { id: string; requestedRunId?: string }) {
  const client = useQueryClient();
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("findings");
  const tabRef = useRef(tab);
  useEffect(() => {
    tabRef.current = tab;
  }, [tab]);
  const [view, setView] = useState<PlanView>("tree");
  const [planSha, setPlanSha] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [evidence, setEvidence] = useState<EvidenceDetail | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [step, setStep] = useState<string>(RUN_ROW);
  const header = useRef<HTMLElement>(null);
  const page = useRef<HTMLDivElement>(null);

  const investigation = useQuery({ queryKey: investigationKeys.detail(id), queryFn: ({ signal }) => getInvestigation(id, signal) });
  const runs = investigation.data?.runs ?? [];
  const requested = requestedRunId ? runs.find((x) => x.id === requestedRunId) : undefined;
  const missingRun = Boolean(requestedRunId && investigation.data && !requested);
  const runId = requested?.id ?? investigation.data?.latestRun?.id ?? null;
  const summary = runs.find((x) => x.id === runId);
  const parent = summary?.parentRunId ? runs.find((x) => x.id === summary.parentRunId) : undefined;
  function selectRun(next: string) {
    setPlanSha(null);
    setSelected(null);
    setEvidence(null);
    setNotice(null);
    setStep(RUN_ROW);
    router.replace(`/app/investigations/${id}?run=${next}`, { scroll: false });
  }
  const run = useQuery({ queryKey: investigationKeys.run(runId ?? ""), queryFn: ({ signal }) => getRun(runId ?? "", signal), enabled: runId !== null, refetchInterval: (q) => runRefetchInterval(q.state.data?.status) });
  const findings = useQuery({ queryKey: investigationKeys.findings(runId ?? ""), queryFn: ({ signal }) => getFindings(runId ?? "", signal), enabled: runId !== null });
  const plans = useQuery({ queryKey: investigationKeys.plans(runId ?? ""), queryFn: ({ signal }) => getRunPlans(runId ?? "", signal), enabled: runId !== null });
  const sandbox = investigation.data?.modes.includes("sandbox_benchmark") ?? false;
  const candidates = useQuery({ queryKey: optimizationKeys.candidates(runId ?? ""), queryFn: ({ signal }) => getCandidates(runId ?? "", signal), enabled: runId !== null && sandbox });
  const approvals = useQuery({ queryKey: optimizationKeys.approvals(runId ?? ""), queryFn: ({ signal }) => getApprovals(runId ?? "", signal), enabled: runId !== null && sandbox });
  const experiments = useQuery({ queryKey: optimizationKeys.experiments(runId ?? ""), queryFn: ({ signal }) => getExperiments(runId ?? "", signal), enabled: runId !== null && sandbox });
  const pending = approvals.data?.items.find((a) => a.status === "pending") ?? null;
  const { events, live } = useRunEvents(runId);
  const cancel = useMutation({
    mutationFn: () => cancelRun(runId ?? ""),
    onSuccess: (r) => client.setQueryData(investigationKeys.run(r.id), r),
  });

  const r = run.data;
  const active = r ? ACTIVE.has(r.status) : true;
  // Same query as the Report tab, so the sealed report is fetched once (FINAL_UI_POLISH §2.1).
  const sealed = useQuery({
    queryKey: reportKeys.report(runId ?? ""),
    queryFn: ({ signal }) => getReport(runId ?? "", signal),
    enabled: runId !== null && r !== undefined && !active,
    retry: false,
  });
  const sealedReport = sealed.data && SUPPORTED_REPORT_SCHEMAS.includes(sealed.data.reportSchemaVersion) ? (sealed.data.report as unknown as ReportV1) : null;
  const trace = useMemo(() => buildTrace(events, { active }), [events, active]);
  const claimIndex = useMemo(() => indexClaimSpans(trace), [trace]);
  const selectedSpan = step === RUN_ROW ? undefined : findSpan(trace, step);

  // Plan citations resolve each cited evidence ID once (immutable, cached), only while the Plan tab is open.
  const claims = findings.data;
  const citedIds = useMemo(() => (claims ? citedEvidenceIds(claims.findings, claims.hypotheses) : []), [claims]);
  const resolved = useQueries({
    queries: citedIds.map((ev) => ({
      queryKey: investigationKeys.evidence(runId ?? "", ev),
      queryFn: ({ signal }: { signal: AbortSignal }) => getEvidence(runId ?? "", ev, signal),
      enabled: runId !== null && tab === "plan" && step === RUN_ROW,
      staleTime: Infinity,
      retry: false,
    })),
    combine: (results) => {
      const map = new Map<string, EvidenceDetail | "error">();
      results.forEach((q, i) => {
        if (q.data) map.set(citedIds[i]!, q.data);
        else if (q.isError) map.set(citedIds[i]!, "error");
      });
      return map;
    },
  });

  // The sticky header (md and up; on phones it is too tall to pin) offsets the sticky trace column,
  // so neither covers the other.
  useEffect(() => {
    const el = header.current;
    const host = page.current;
    if (!el || !host || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => host.style.setProperty("--qc-sticky", `${el.offsetHeight}px`));
    ro.observe(el);
    return () => ro.disconnect();
  }, [investigation.data]);

  async function openEvidence(evidenceId: string) {
    if (!runId) return;
    let detail: EvidenceDetail;
    try {
      detail = await client.fetchQuery({
        queryKey: investigationKeys.evidence(runId, evidenceId),
        queryFn: ({ signal }) => getEvidence(runId, evidenceId, signal),
        staleTime: Infinity,
      });
    } catch (error) {
      setNotice(`Evidence ${evidenceId} could not be loaded${error instanceof ApiError ? `: ${error.message}` : "."}`);
      return;
    }
    setEvidence(detail);
    const target = planTargetOfEvidence(detail, plans.data?.items ?? []);
    if (target.status === "found") {
      setNotice(null);
      setStep(RUN_ROW);
      setPlanSha(target.planSha);
      setSelected(target.nodeId);
      setView("tree");
      setTab("plan");
    } else if (target.status === "plan_unavailable") {
      setNotice(`${evidenceId} cites a plan that is not available for this run.`);
    } else if (target.status === "node_unavailable") {
      setNotice(`${evidenceId} cites a plan node that is not in this run's plan.`);
    } else {
      setNotice(null);
    }
  }

  function showClaim(key: string) {
    const match = stepForClaim(claimIndex, key);
    if (match.status === "found") setStep(match.spanId);
    else setNotice(`No trace step recorded ${key}.`);
  }

  // Palette entries and `[` `]` / `g f` `g p` `g t` `g r` for the result tabs (UI_UX §3.15).
  const tabCommands = useMemo<Command[]>(() => {
    const ids: Tab[] = ["findings", "plan", ...(sandbox ? (["tournament"] as const) : []), "report"];
    const labels: Record<Tab, string> = { findings: "Findings", plan: "Plan", tournament: "Tournament", report: "Report" };
    const show = (t: Tab) => {
      setStep(RUN_ROW);
      setEvidence(null);
      setTab(t);
    };
    const shift = (by: number) => {
      const i = ids.indexOf(tabRef.current);
      show(ids[(i + by + ids.length) % ids.length] ?? tabRef.current);
    };
    return [
      ...ids.map((t) => ({ id: `tab-${t}`, label: `Show ${labels[t]} tab`, group: "This investigation" as const, keys: ["g", t.charAt(0)], run: () => show(t) })),
      { id: "tab-prev", label: "Previous result tab", group: "This investigation", keys: ["["], run: () => shift(-1) },
      { id: "tab-next", label: "Next result tab", group: "This investigation", keys: ["]"], run: () => shift(1) },
    ];
  }, [sandbox]);
  useContextCommands("investigation", investigation.data ? tabCommands : NO_COMMANDS);

  if (investigation.error) return <ErrorNotice error={investigation.error} />;
  if (!investigation.data) return <Skeleton label="Loading investigation" lines={3} className="max-w-xl" />;

  const currentPlan = plans.data?.items.find((p) => p.sha256 === planSha) ?? plans.data?.items[0];
  const selectedNode = currentPlan?.plan.nodes.find((n) => n.id === selected);
  const citations = currentPlan && claims ? citationsByNode(claims.findings, claims.hypotheses, resolved, currentPlan.sha256) : null;
  const citationCounts = citations
    ? new Map([...citations.byNode].map(([node, c]) => [node, c.findings.length + c.hypotheses.length]))
    : undefined;
  const claimLabels = new Map<string, string>([
    ...(claims?.findings.map((f) => [f.key, f.title] as [string, string]) ?? []),
    ...(claims?.hypotheses.map((h) => [h.key, h.statement] as [string, string]) ?? []),
  ]);
  const tabs: { id: Tab; label: string }[] = [
    { id: "findings", label: "Findings" },
    { id: "plan", label: "Plan" },
    ...(sandbox ? [{ id: "tournament" as const, label: "Tournament" }] : []),
    { id: "report", label: "Report" },
  ];

  return (
    <div ref={page} className="flex flex-col gap-4 [--qc-sticky:0px]">
      <header
        ref={header}
        className="-mx-4 -mt-5 flex flex-col gap-2 border-b border-border bg-bg/95 px-4 pt-4 pb-3 backdrop-blur-sm md:sticky md:top-0 md:z-20 md:-mx-8 md:-mt-7 md:px-8"
      >
        <div className="flex items-center justify-between gap-3">
          <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 text-xs text-muted">
            <Link href="/app/history" className="shrink-0 hover:text-ink">
              Investigations
            </Link>
            <Icon name="chevronRight" size={12} />
            <span className="truncate text-ink">{investigation.data.title}</span>
          </nav>
          <div className="flex shrink-0 items-center gap-2">
            {r && !active ? (
              <Link href={`/app/replay/${r.id}`} className="qc-btn-secondary py-1 text-xs">
                <Icon name="replay" size={13} />
                Reproducibility & replay
              </Link>
            ) : null}
            {r && active && r.status !== "cancelling" ? (
              <button
                type="button"
                onClick={() => cancel.mutate()}
                disabled={cancel.isPending}
                className="qc-btn border border-rejected/40 py-1 text-xs text-rejected hover:bg-rejected/10"
              >
                Cancel run
              </button>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
          <div className="flex min-w-0 flex-col gap-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-semibold tracking-tight">{investigation.data.title}</h1>
              {r ? <RunStatusPill status={r.status} /> : null}
              {r?.outcome ? <span className="text-xs text-muted">{r.outcome.replaceAll("_", " ")}</span> : null}
            </div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <RunSelector runs={runs} selectedId={runId} onSelect={selectRun} />
              {!summary && r ? <span className="font-mono text-[11px] text-muted">run {r.runNumber}</span> : null}
              <span className="font-mono text-[11px] text-muted">
                {r ? (r.llmModel ? `${r.llmModel} via ${r.llmProvider}` : "model not assigned yet") : ""}
              </span>
            </div>
          </div>
          {r ? <BudgetMeter run={r} /> : null}
        </div>
      </header>

      <div className="flex flex-col gap-2">
        <p className="max-w-3xl text-sm text-muted">{investigation.data.objective}</p>
        {parent ? (
          <button type="button" onClick={() => selectRun(parent.id)} className="w-fit text-sm text-link">
            Go to run #{parent.runNumber} ({runKindLabel(parent.kind).toLowerCase()})
          </button>
        ) : null}
        {r?.errorCode ? (
          <p role="status" className="flex items-start gap-2 rounded-md border border-rejected/30 bg-rejected/10 px-3 py-2 text-sm text-rejected">
            <Icon name="xCircle" size={14} className="mt-0.5" />
            <span>
              {r.status === "completed" ? "Problem" : "Stopped"}: {r.errorMessage ?? r.errorCode}
            </span>
          </p>
        ) : null}
        <ErrorNotice error={cancel.error} />
        {missingRun ? (
          <p role="status" className="rounded-md border border-border bg-surface-2 p-3 text-sm">
            That run is not part of this investigation (it may have been deleted). Showing run {r?.runNumber ?? "…"} instead.
          </p>
        ) : null}
        {notice ? (
          <p role="status" className="flex items-start gap-2 rounded-md border border-inconclusive/30 bg-inconclusive/10 px-3 py-2 text-sm">
            <Icon name="alert" size={14} className="mt-0.5 text-inconclusive" />
            <span className="flex-1">{notice}</span>
            <button type="button" onClick={() => setNotice(null)} aria-label="Dismiss notice" className="text-muted hover:text-ink">
              <Icon name="close" size={14} />
            </button>
          </p>
        ) : null}
      </div>

      {sealedReport && !active ? (
        <ResultSummary
          report={sealedReport}
          onReport={() => {
            setStep(RUN_ROW);
            setTab("report");
          }}
          onBenchmark={
            sandbox
              ? () => {
                  setStep(RUN_ROW);
                  setTab("tournament");
                }
              : undefined
          }
        />
      ) : null}

      {pending && runId && r?.status === "awaiting_approval" ? <ApprovalCard key={pending.id} approval={pending} runId={runId} /> : null}

      <div className="grid grid-cols-1 items-start gap-5 xl:grid-cols-[minmax(340px,420px)_minmax(0,1fr)]">
        <div className="flex min-w-0 flex-col xl:sticky xl:top-[calc(var(--qc-sticky)+1rem)] xl:max-h-[calc(100vh-var(--qc-sticky)-2rem)] max-xl:max-h-[60vh]">
          <TraceTree
            trace={trace}
            events={events}
            runLabel={r ? `Run #${r.runNumber}` : "Run"}
            live={live}
            active={active}
            selectedId={selectedSpan ? step : RUN_ROW}
            onSelect={setStep}
          />
        </div>

        {selectedSpan && runId ? (
          <StepDetails span={selectedSpan} runId={runId} onBack={() => setStep(RUN_ROW)} onSelect={setStep} onOpenEvidence={(e) => void openEvidence(e)} />
        ) : (
          <section aria-label="Selection details" className="flex min-w-0 flex-col gap-4">
            <div role="tablist" aria-label="Results" className="flex gap-5 border-b border-border">
              {tabs.map((t) => (
                <button key={t.id} role="tab" aria-selected={tab === t.id} className={tabClass(tab === t.id)} onClick={() => setTab(t.id)}>
                  {t.label}
                </button>
              ))}
            </div>
            {evidence ? (
              <aside aria-label="Selected evidence" className="flex items-start gap-2 rounded-md border border-accent/30 bg-accent-tint p-3 text-sm">
                <Icon name="database" size={14} className="mt-0.5 text-accent" />
                <div className="min-w-0 flex-1">
                  <p className="font-mono text-xs text-muted">
                    {evidence.evidence.id} · {evidence.evidence.kind} · {evidence.evidence.provenance}
                  </p>
                  <p>{evidence.evidence.summary}</p>
                </div>
                <button type="button" onClick={() => setEvidence(null)} aria-label="Close evidence" className="text-muted hover:text-ink">
                  <Icon name="close" size={14} />
                </button>
              </aside>
            ) : null}
            {tab === "report" && runId ? (
              <ReportPanel
                runId={runId}
                onPlanNode={(sha, node) => {
                  setPlanSha(sha);
                  setSelected(node);
                  setTab("plan");
                }}
              />
            ) : tab === "tournament" ? (
              <TournamentPanel experiments={experiments.data?.items ?? []} candidates={candidates.data?.items ?? []} runId={runId ?? undefined} />
            ) : tab === "findings" ? (
              <FindingsPanel
                data={findings.data}
                onEvidence={(e) => void openEvidence(e)}
                activeEvidence={evidence?.evidence.id ?? null}
                stepFor={(key) => stepForClaim(claimIndex, key)}
                onShowStep={setStep}
              />
            ) : currentPlan ? (
              <PlanExplorer
                plan={currentPlan.plan}
                metrics={currentPlan.metrics}
                selectedId={selected}
                onSelect={setSelected}
                view={view}
                onViewChange={setView}
                citationCounts={citationCounts}
                label={`${currentPlan.role === "context.plan" ? "live EXPLAIN" : "uploaded plan"} · ${currentPlan.sha256.slice(0, 12)}`}
                details={
                  selectedNode ? (
                    <NodeDetails
                      node={selectedNode}
                      stoppedEarly={stopsEarly(currentPlan.plan, selectedNode.id)}
                      metrics={currentPlan.metrics.find((m) => m.nodeId === selectedNode.id)}
                      citations={
                        citations
                          ? {
                              citation: citations.byNode.get(selectedNode.id),
                              labels: claimLabels,
                              pending: citations.pending,
                              failed: citations.failed,
                              onClaim: showClaim,
                            }
                          : undefined
                      }
                    />
                  ) : null
                }
              />
            ) : (
              <p className="qc-panel p-6 text-sm text-muted">No plan for this run yet.</p>
            )}
          </section>
        )}
      </div>
    </div>
  );
}
