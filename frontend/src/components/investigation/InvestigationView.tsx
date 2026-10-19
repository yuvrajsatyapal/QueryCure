"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ErrorNotice } from "@/components/common/ErrorNotice";
import { NodeDetails } from "@/components/plan/NodeDetails";
import { PlanGraph } from "@/components/plan/PlanGraph";
import { PlanTreeTable } from "@/components/plan/PlanTreeTable";
import {
  cancelRun,
  getEvidence,
  getFindings,
  getInvestigation,
  getRun,
  getRunPlans,
  investigationKeys,
} from "@/lib/api/investigations";
import { getApprovals, getCandidates, getExperiments, optimizationKeys } from "@/lib/api/optimization";
import type { EvidenceDetail } from "@/lib/api/types";
import { ReportPanel } from "@/components/report/ReportPanel";
import { ApprovalCard } from "@/components/tournament/ApprovalCard";
import { TournamentPanel } from "@/components/tournament/TournamentPanel";
import { runRefetchInterval } from "@/lib/events/runEvents";
import { useRunEvents } from "@/lib/events/useRunEvents";
import { Icon } from "@/components/ui/Icon";
import { RunStatusPill } from "@/components/ui/StatusPill";
import { BudgetMeter } from "./BudgetMeter";
import { FindingsPanel } from "./FindingsPanel";
import { RunPicker, runKindLabel, runRelation } from "./RunPicker";
import { TraceView } from "./TraceView";

type Tab = "plan" | "findings" | "tournament" | "report";
const ACTIVE = new Set(["queued", "running", "awaiting_approval", "cancelling"]);
// Underlined tabs for the results area (Linear), pill segments for the small plan-view switch.
const tabClass = (active: boolean) =>
  `-mb-px border-b-2 px-1 pb-2 text-sm ${active ? "border-accent font-medium text-ink" : "border-transparent text-muted hover:text-ink"}`;
const segmentClass = (active: boolean) =>
  `rounded px-2.5 py-1 text-xs ${active ? "bg-surface font-medium text-ink shadow-sm" : "text-muted hover:text-ink"}`;

/** `requestedRunId` comes from `?run=` so a selected run (an older run, a replay) is linkable. */
export function InvestigationView({ id, requestedRunId }: { id: string; requestedRunId?: string }) {
  const client = useQueryClient();
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("findings");
  const [view, setView] = useState<"tree" | "graph">("tree");
  const [planSha, setPlanSha] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [evidence, setEvidence] = useState<EvidenceDetail | null>(null);

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

  async function openEvidence(evidenceId: string) {
    if (!runId) return;
    const detail = await client.fetchQuery({
      queryKey: investigationKeys.evidence(runId, evidenceId),
      queryFn: ({ signal }) => getEvidence(runId, evidenceId, signal),
    });
    setEvidence(detail);
    const nodeId = (detail.evidence.data as { nodeId?: unknown }).nodeId;
    const plan = plans.data?.items.find((p) => p.sha256 === detail.artifact?.sha256);
    if (detail.evidence.kind === "plan_node" && plan && typeof nodeId === "number") {
      setPlanSha(plan.sha256);
      setSelected(nodeId);
      setTab("plan");
    }
  }

  if (investigation.error) return <ErrorNotice error={investigation.error} />;
  if (!investigation.data) return <p className="text-muted">Loading investigation…</p>;

  const r = run.data;
  const currentPlan = plans.data?.items.find((p) => p.sha256 === planSha) ?? plans.data?.items[0];
  const selectedNode = currentPlan?.plan.nodes.find((n) => n.id === selected);

  const active = r ? ACTIVE.has(r.status) : true;
  const tabs: { id: Tab; label: string }[] = [
    { id: "findings", label: "Findings" },
    { id: "plan", label: "Plan" },
    ...(sandbox ? [{ id: "tournament" as const, label: "Tournament" }] : []),
    { id: "report", label: "Report" },
  ];

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-col gap-3">
        <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-xs text-muted">
          <Link href="/app/history" className="hover:text-ink">
            Investigations
          </Link>
          <Icon name="chevronRight" size={12} />
          <span className="truncate text-ink">{investigation.data.title}</span>
        </nav>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-semibold tracking-tight">{investigation.data.title}</h1>
              {r ? <RunStatusPill status={r.status} /> : null}
              {r?.outcome ? <span className="text-xs text-muted">{r.outcome.replaceAll("_", " ")}</span> : null}
            </div>
            <p className="font-mono text-[11px] text-muted">
              Investigation · run {r?.runNumber ?? "…"}
              {summary ? ` · ${runKindLabel(summary.kind)}` : null}
              {summary && runRelation(summary, runs) ? ` ${runRelation(summary, runs)}` : null}
            </p>
            <p className="max-w-3xl text-sm text-muted">{investigation.data.objective}</p>
            {parent ? (
              <button type="button" onClick={() => selectRun(parent.id)} className="w-fit text-sm text-link">
                Go to run #{parent.runNumber} ({runKindLabel(parent.kind).toLowerCase()})
              </button>
            ) : null}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {r && !active ? (
              <Link href={`/app/replay/${r.id}`} className="qc-btn-secondary">
                <Icon name="replay" size={14} />
                Reproducibility & replay
              </Link>
            ) : null}
            {r && active && r.status !== "cancelling" ? (
              <button
                type="button"
                onClick={() => cancel.mutate()}
                disabled={cancel.isPending}
                className="qc-btn border border-rejected/40 text-rejected hover:bg-rejected/10"
              >
                Cancel run
              </button>
            ) : null}
          </div>
        </div>
        {r?.errorCode ? (
          <p role="status" className="flex items-start gap-2 rounded-md border border-rejected/30 bg-rejected/10 px-3 py-2 text-sm text-rejected">
            <Icon name="xCircle" size={14} className="mt-0.5" />
            <span>
              {r.status === "completed" ? "Problem" : "Stopped"}: {r.errorMessage ?? r.errorCode}
            </span>
          </p>
        ) : null}
        <ErrorNotice error={cancel.error} />
      </header>
      {missingRun ? (
        <p role="status" className="rounded-md border border-border bg-surface-2 p-3 text-sm">
          That run is not part of this investigation (it may have been deleted). Showing run {r?.runNumber ?? "…"} instead.
        </p>
      ) : null}
      {pending && runId && r?.status === "awaiting_approval" ? <ApprovalCard key={pending.id} approval={pending} runId={runId} /> : null}
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(380px,460px)]">
        <section aria-label="Investigation" className="flex min-w-0 flex-col gap-4">
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
            <FindingsPanel data={findings.data} onEvidence={(e) => void openEvidence(e)} activeEvidence={evidence?.evidence.id ?? null} />
          ) : currentPlan ? (
            <div className="flex flex-col gap-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="qc-eyebrow">
                  {currentPlan.role === "context.plan" ? "live EXPLAIN" : "uploaded plan"} · {currentPlan.sha256.slice(0, 12)}
                </p>
                <div role="tablist" aria-label="Plan view" className="flex gap-0.5 rounded-md border border-border bg-surface-2 p-0.5">
                  <button role="tab" aria-selected={view === "tree"} className={segmentClass(view === "tree")} onClick={() => setView("tree")}>
                    Tree
                  </button>
                  <button role="tab" aria-selected={view === "graph"} className={segmentClass(view === "graph")} onClick={() => setView("graph")}>
                    Graph
                  </button>
                </div>
              </div>
              {view === "tree" ? (
                <PlanTreeTable plan={currentPlan.plan} metrics={currentPlan.metrics} onSelect={setSelected} selectedId={selected} />
              ) : (
                <PlanGraph plan={currentPlan.plan} metrics={currentPlan.metrics} onSelect={setSelected} selectedId={selected} />
              )}
              {selectedNode ? <NodeDetails node={selectedNode} metrics={currentPlan.metrics.find((m) => m.nodeId === selectedNode.id)} /> : null}
            </div>
          ) : (
            <p className="qc-panel p-6 text-sm text-muted">No plan for this run yet.</p>
          )}
        </section>
        <aside aria-label="Run" className="flex min-w-0 flex-col gap-4">
          <RunPicker runs={runs} selectedId={runId} onSelect={selectRun} />
          <TraceView events={events} live={live} active={active} onEvidence={(e) => void openEvidence(e)} />
          {r ? <BudgetMeter run={r} /> : null}
        </aside>
      </div>
    </div>
  );
}
