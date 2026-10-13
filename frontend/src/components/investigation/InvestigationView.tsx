"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
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
import { useRunEvents } from "@/lib/events/useRunEvents";
import { BudgetMeter } from "./BudgetMeter";
import { FindingsPanel } from "./FindingsPanel";
import { Timeline } from "./Timeline";

type Tab = "plan" | "findings" | "tournament" | "report";
const ACTIVE = new Set(["queued", "running", "awaiting_approval", "cancelling"]);
const tabClass = (active: boolean) =>
  `rounded-md px-3 py-1.5 text-sm ${active ? "bg-accent-tint font-medium text-ink" : "text-muted hover:text-ink"}`;

export function InvestigationView({ id }: { id: string }) {
  const client = useQueryClient();
  const [tab, setTab] = useState<Tab>("findings");
  const [view, setView] = useState<"tree" | "graph">("tree");
  const [planSha, setPlanSha] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [evidence, setEvidence] = useState<EvidenceDetail | null>(null);

  const investigation = useQuery({ queryKey: investigationKeys.detail(id), queryFn: ({ signal }) => getInvestigation(id, signal) });
  const runId = investigation.data?.latestRun?.id ?? null;
  const run = useQuery({ queryKey: investigationKeys.run(runId ?? ""), queryFn: ({ signal }) => getRun(runId ?? "", signal), enabled: runId !== null });
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

  return (
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1.5fr_minmax(300px,0.8fr)]">
      <section aria-label="Investigation" className="flex min-w-0 flex-col gap-4">
        <div>
          <p className="font-mono text-xs uppercase tracking-wider text-muted">
            Investigation · run {r?.runNumber ?? "…"}
          </p>
          <h1 className="text-2xl font-semibold">{investigation.data.title}</h1>
          <p className="text-sm text-muted">{investigation.data.objective}</p>
        </div>
        <div role="tablist" aria-label="Results" className="flex gap-2">
          <button role="tab" aria-selected={tab === "findings"} className={tabClass(tab === "findings")} onClick={() => setTab("findings")}>
            Findings
          </button>
          <button role="tab" aria-selected={tab === "plan"} className={tabClass(tab === "plan")} onClick={() => setTab("plan")}>
            Plan
          </button>
          {sandbox ? (
            <button role="tab" aria-selected={tab === "tournament"} className={tabClass(tab === "tournament")} onClick={() => setTab("tournament")}>
              Tournament
            </button>
          ) : null}
          <button role="tab" aria-selected={tab === "report"} className={tabClass(tab === "report")} onClick={() => setTab("report")}>
            Report
          </button>
        </div>
        {pending && runId && r?.status === "awaiting_approval" ? <ApprovalCard key={pending.id} approval={pending} runId={runId} /> : null}
        {evidence ? (
          <aside aria-label="Selected evidence" className="rounded-md border border-border bg-surface-2 p-3 text-sm">
            <p className="font-mono text-xs text-muted">
              {evidence.evidence.id} · {evidence.evidence.kind} · {evidence.evidence.provenance}
            </p>
            <p>{evidence.evidence.summary}</p>
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
              <p className="font-mono text-xs uppercase tracking-wider text-muted">
                {currentPlan.role === "context.plan" ? "live EXPLAIN" : "uploaded plan"} · {currentPlan.sha256.slice(0, 12)}
              </p>
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
              <PlanTreeTable plan={currentPlan.plan} metrics={currentPlan.metrics} onSelect={setSelected} selectedId={selected} />
            ) : (
              <PlanGraph plan={currentPlan.plan} metrics={currentPlan.metrics} onSelect={setSelected} selectedId={selected} />
            )}
            {selectedNode ? <NodeDetails node={selectedNode} metrics={currentPlan.metrics.find((m) => m.nodeId === selectedNode.id)} /> : null}
          </div>
        ) : (
          <p className="rounded-lg border border-border bg-surface p-6 text-muted">No plan for this run yet.</p>
        )}
      </section>
      <aside aria-label="Run" className="flex min-w-0 flex-col gap-4">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm">
            Status: <span className="font-medium">{r?.status ?? "…"}</span>
            {r?.outcome ? <span className="text-muted"> · {r.outcome.replaceAll("_", " ")}</span> : null}
          </p>
          {r && ACTIVE.has(r.status) && r.status !== "cancelling" ? (
            <button type="button" onClick={() => cancel.mutate()} disabled={cancel.isPending} className="rounded-md border border-rejected px-3 py-1 text-sm text-rejected">
              Cancel run
            </button>
          ) : null}
        </div>
        {r?.errorCode ? <p className="text-sm text-rejected">Stopped: {r.errorCode}</p> : null}
        {r && !ACTIVE.has(r.status) ? (
          <Link href={`/app/replay/${r.id}`} className="text-sm text-link">
            Reproducibility & replay
          </Link>
        ) : null}
        <ErrorNotice error={cancel.error} />
        {r ? <BudgetMeter run={r} /> : null}
        <Timeline events={events} live={live} />
      </aside>
    </div>
  );
}
