"use client";

import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode, type RefObject } from "react";
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
import { getApprovals, getCandidates, getExperiment, getExperiments, optimizationKeys } from "@/lib/api/optimization";
import type { EvidenceDetail, Verification } from "@/lib/api/types";
import { EvidenceExplorer } from "@/components/evidence/EvidenceExplorer";
import type { GraphNode as EvidenceNode } from "@/lib/evidence/graph";
import type { AuditCheck, AuditConcern } from "@/lib/report/types";
import { ReportPanel } from "@/components/report/ReportPanel";
import { ResultSummary } from "@/components/report/ResultSummary";
import { replayReportMeta, sealedReplayRuns, type ReplayReportMeta } from "@/lib/report/replay";
import { SUPPORTED_REPORT_SCHEMAS, getReport, getVerifications, reportKeys } from "@/lib/api/reports";
import type { ReportV1 } from "@/lib/report/types";
import { ApprovalReview } from "@/components/tournament/ApprovalReview";
import { armsWithPlans } from "@/components/tournament/PlanCompare";
import { TournamentPanel, type SectionFocus } from "@/components/tournament/TournamentPanel";
import { buildRunScopeItems, type RunScopeTarget } from "@/lib/command/runScope";
import { runModelLabel } from "@/lib/investigation/model";
import { buildTrace } from "@/lib/events/trace";
import { runRefetchInterval } from "@/lib/events/runEvents";
import { useRunEvents } from "@/lib/events/useRunEvents";
import {
  ancestorIds,
  citationsByNode,
  citedEvidenceIds,
  findSpan,
  indexClaimSpans,
  indexEvidenceSpans,
  planTargetOfEvidence,
  stepForClaim,
} from "@/lib/investigation/links";
import { useContextCommands, usePaletteOpen, useRunScope, type Command, type PickSource, type RunScope } from "@/components/command/CommandProvider";
import { BottomSheet } from "@/components/ui/BottomSheet";
import { ContextMenu, type MenuItem } from "@/components/ui/ContextMenu";
import { Icon } from "@/components/ui/Icon";
import { Skeleton } from "@/components/ui/Skeleton";
import { RunStatusPill, StatusOrb } from "@/components/ui/StatusPill";
import { activityOf } from "@/lib/trace/activity";
import { graphRun } from "@/lib/trace/graph";
import type { Span } from "@/lib/events/trace";
import { RunStats } from "./BudgetMeter";
import { FindingsPanel } from "./FindingsPanel";
import { runKindLabel } from "./RunPicker";
import { RunSelector } from "./RunSelector";
import { StepDetails } from "./StepDetails";
import { TraceGraph } from "./TraceGraph";
import { TraceTree } from "./TraceTree";

type Tab = "plan" | "findings" | "evidence" | "tournament" | "report";
type View = "waterfall" | "graph" | "results";
const VIEWS: { id: View; label: string }[] = [
  { id: "waterfall", label: "Waterfall" },
  { id: "graph", label: "Graph" },
  { id: "results", label: "Results" },
];
// The split (trace beside the inspector) needs this much width of its own container, so it
// follows the collapsed or expanded sidebar rather than the viewport.
const SPLIT_MIN_PX = 900;
const INSPECTOR = { min: 340, max: 640, share: 0.38, step: 24 };

/** `ref`'s own width (the workspace, so it follows the sidebar rail), or null until measured. */
function useWidth(ref: RefObject<HTMLElement | null>, ready: boolean): number | null {
  const [width, setWidth] = useState<number | null>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([entry]) => setWidth(Math.round(entry?.contentRect.width ?? 0)));
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref, ready]);
  return width;
}

/** A clock for open durations; null until mounted so server and client render the same. */
function useClock(active: boolean): number | null {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    const tick = () => setNow(Date.now());
    const first = setTimeout(tick, 0);
    const t = active ? setInterval(tick, 1000) : undefined;
    return () => {
      clearTimeout(first);
      clearInterval(t);
    };
  }, [active]);
  return now;
}

/** The graph node a trace row belongs to (itself, or the node that encloses it). */
function nodeOf(trace: Span, span: Span | undefined): string | null {
  if (!span || span.kind === "run") return null;
  if (span.kind === "node") return span.name;
  const outer = ancestorIds(trace, span.id)[0];
  const parent = outer ? findSpan(trace, outer) : undefined;
  return parent?.kind === "node" ? parent.name : null;
}
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
  // "Open in benchmark" from the evidence tab: the tournament selects this arm.
  const [focusArm, setFocusArm] = useState<string | null>(null);
  // A studio section to open and focus once the tournament renders (a plan diff from the palette).
  const [focusSection, setFocusSection] = useState<SectionFocus | null>(null);
  const sectionDone = useCallback(() => setFocusSection(null), []);
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
  const [mode, setMode] = useState<View>("waterfall");
  const [graphPick, setGraphPick] = useState<string | null>(null);
  const [menu, setMenu] = useState<{ spanId: string; at: { x: number; y: number } } | null>(null);
  const [sheet, setSheet] = useState(false);
  // The approval whose review drawer is open; it stays open after the decision is recorded.
  const [reviewing, setReviewing] = useState<string | null>(null);
  // Set when a menu switches views ("Show in graph"): the pane focuses its selection, then clears it.
  const [paneFocus, setPaneFocus] = useState(false);
  const focusDone = useCallback(() => setPaneFocus(false), []);
  // null: a share of the workspace until the user resizes it.
  const [resized, setResized] = useState<number | null>(null);
  const header = useRef<HTMLElement>(null);
  const page = useRef<HTMLDivElement>(null);
  const split = useRef<HTMLDivElement>(null);

  const investigation = useQuery({ queryKey: investigationKeys.detail(id), queryFn: ({ signal }) => getInvestigation(id, signal) });
  const width = useWidth(page, investigation.data !== undefined);
  // Assumed wide until measured, so the server render and tests get the split.
  const wide = width === null || width >= SPLIT_MIN_PX;
  const clampW = (w: number) => Math.max(INSPECTOR.min, Math.min(INSPECTOR.max, w));
  const inspectorW = resized ?? clampW(Math.round((width ?? 1200) * INSPECTOR.share));
  const setInspectorW = (next: number | ((w: number) => number)) => setResized(clampW(typeof next === "function" ? next(inspectorW) : next));
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
    setGraphPick(null);
    setMenu(null);
    setSheet(false);
    setReviewing(null);
    setFocusSection(null);
    router.replace(`/app/investigations/${id}?run=${next}`, { scroll: false });
  }
  const run = useQuery({ queryKey: investigationKeys.run(runId ?? ""), queryFn: ({ signal }) => getRun(runId ?? "", signal), enabled: runId !== null, refetchInterval: (q) => runRefetchInterval(q.state.data?.status) });
  const findings = useQuery({ queryKey: investigationKeys.findings(runId ?? ""), queryFn: ({ signal }) => getFindings(runId ?? "", signal), enabled: runId !== null });
  const plans = useQuery({ queryKey: investigationKeys.plans(runId ?? ""), queryFn: ({ signal }) => getRunPlans(runId ?? "", signal), enabled: runId !== null });
  const sandbox = investigation.data?.modes.includes("sandbox_benchmark") ?? false;
  const candidates = useQuery({ queryKey: optimizationKeys.candidates(runId ?? ""), queryFn: ({ signal }) => getCandidates(runId ?? "", signal), enabled: runId !== null && sandbox });
  const approvals = useQuery({ queryKey: optimizationKeys.approvals(runId ?? ""), queryFn: ({ signal }) => getApprovals(runId ?? "", signal), enabled: runId !== null && sandbox });
  const experiments = useQuery({ queryKey: optimizationKeys.experiments(runId ?? ""), queryFn: ({ signal }) => getExperiments(runId ?? "", signal), enabled: runId !== null && sandbox });
  const verifications = useQuery({ queryKey: reportKeys.verifications(runId ?? ""), queryFn: ({ signal }) => getVerifications(runId ?? "", signal), enabled: runId !== null && sandbox && tab === "evidence" });
  // The palette's plan-diff results need the latest round's plan captures: read (once, cached and
  // shared with the tournament tab) only while the palette is open.
  const paletteOpen = usePaletteOpen();
  const latestRound = (experiments.data?.items ?? []).filter((e) => e.replicate === 0).at(-1) ?? null;
  const roundDetail = useQuery({
    queryKey: optimizationKeys.experiment(latestRound?.id ?? ""),
    queryFn: ({ signal }) => getExperiment(latestRound?.id ?? "", signal),
    enabled: paletteOpen && latestRound !== null,
  });
  const pending = approvals.data?.items.find((a) => a.status === "pending") ?? null;
  const reviewed = reviewing ? (approvals.data?.items.find((a) => a.id === reviewing) ?? null) : null;
  const { events, live, stream } = useRunEvents(runId);
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
  // Sealed replays: their (immutable, cached) report gives the run selector the builder's replay
  // title, or marks a historical report-builder@1 replay (REPLAY_OUTCOME_AUDIT §13.3–§13.4).
  const replayKey = useQueries({
    queries: sealedReplayRuns(runs).map((c) => ({
      queryKey: reportKeys.report(c.id),
      queryFn: ({ signal }: { signal: AbortSignal }) => getReport(c.id, signal),
      staleTime: Infinity,
      retry: false,
    })),
    combine: (results) => JSON.stringify(results.flatMap((q) => (q.data ? [[q.data.runId, replayReportMeta(q.data)] as const] : []))),
  });
  const replayReports = useMemo(() => new Map<string, ReplayReportMeta>(JSON.parse(replayKey) as [string, ReplayReportMeta][]), [replayKey]);
  const sealedReport = sealed.data && SUPPORTED_REPORT_SCHEMAS.includes(sealed.data.reportSchemaVersion) ? (sealed.data.report as unknown as ReportV1) : null;
  const trace = useMemo(() => buildTrace(events, { active }), [events, active]);
  const claimIndex = useMemo(() => indexClaimSpans(trace), [trace]);
  const evidenceIndex = useMemo(() => indexEvidenceSpans(trace), [trace]);
  const selectedSpan = step === RUN_ROW ? undefined : findSpan(trace, step);
  const graph = useMemo(() => graphRun(trace), [trace]);
  const clock = useClock(active);
  const activity = activityOf({ status: r?.status ?? "queued", outcome: r?.outcome ?? null, errorMessage: r?.errorMessage ?? null, trace, events, stream: stream ?? (live ? "live" : "closed") });

  // Cited evidence resolves once per ID (immutable, cached), only while the Plan or Evidence tab is
  // open. The evidence tab also resolves what the Benchmark Auditor's checks cite.
  const claims = findings.data;
  const audits: Verification[] = useMemo(() => verifications.data?.items ?? [], [verifications.data]);
  const citedIds = useMemo(() => {
    const ids = claims ? citedEvidenceIds(claims.findings, claims.hypotheses) : [];
    const audited = audits.flatMap((v) => [
      ...(v.checks as unknown as AuditCheck[]).flatMap((c) => c.evidenceIds ?? []),
      ...(v.auditorConcerns as unknown as AuditConcern[]).flatMap((c) => c.evidenceIds ?? []),
    ]);
    return [...new Set([...ids, ...audited])];
  }, [claims, audits]);
  const resolved = useQueries({
    queries: citedIds.map((ev) => ({
      queryKey: investigationKeys.evidence(runId ?? "", ev),
      queryFn: ({ signal }: { signal: AbortSignal }) => getEvidence(runId ?? "", ev, signal),
      enabled: runId !== null && (tab === "plan" || tab === "evidence") && step === RUN_ROW,
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

  // Run-scoped palette results (UI_UX §3.15). Every input is keyed by `runId`, so a newly selected
  // run shows its loading state rather than the previous run's results.
  const scopeTarget = useRef<(target: RunScopeTarget, via: PickSource) => void>(() => {});
  const runLabel = summary ? `Run #${summary.runNumber}` : "This run";
  const roundData = latestRound ? roundDetail.data : undefined;
  const planArms = roundData ? (roundData.result ? armsWithPlans(roundData) : []) : null;
  const runScope = useMemo<RunScope | null>(() => {
    if (!investigation.data || !runId) return null;
    const notice = findings.isError
      ? `${runLabel}'s findings could not be loaded.`
      : sandbox && candidates.isError
        ? `${runLabel}'s candidates could not be loaded.`
        : undefined;
    const items = buildRunScopeItems({
      runId,
      findings: claims?.findings,
      hypotheses: claims?.hypotheses,
      candidates: sandbox ? candidates.data?.items : [],
      evidence: resolved,
      planArms,
    }).map((item) => ({ ...item, run: (via: PickSource) => scopeTarget.current(item.target, via) }));
    return { runId, label: runLabel, loading: findings.isPending || (sandbox && candidates.isPending), notice, items };
    // planArms is derived from roundData; listing it would rebuild the scope on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [investigation.data, runId, runLabel, findings.isError, findings.isPending, sandbox, candidates.isError, candidates.isPending, candidates.data, claims, resolved, roundData]);
  useRunScope(runScope);

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

  // After a decision the card (the drawer's opener) is gone, so focus goes to the page heading.
  function closeReview() {
    setReviewing(null);
    requestAnimationFrame(() => {
      if (document.activeElement === document.body || !document.activeElement) page.current?.querySelector<HTMLElement>("h1")?.focus();
    });
  }

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

  /** Select a trace row from elsewhere (a finding, a plan citation, the menu): the trace is shown,
   * and on narrow screens the details open in the sheet. */
  function showStep(spanId: string) {
    setGraphPick(null);
    setStep(spanId);
    if (mode === "results") setMode("waterfall");
    if (!wide) setSheet(true);
  }

  function showClaim(key: string) {
    const match = stepForClaim(claimIndex, key);
    if (match.status === "found") showStep(match.spanId);
    else setNotice(`No trace step recorded ${key}.`);
  }

  function selectNode(name: string) {
    const visits = graph.nodes.get(name)?.visits ?? [];
    const latest = visits.at(-1);
    if (latest) {
      setGraphPick(null);
      setStep(latest.id);
      if (!wide) setSheet(true);
    } else {
      setStep(RUN_ROW);
      setGraphPick(name);
    }
  }

  async function copy(text: string, what: string) {
    try {
      await navigator.clipboard.writeText(text);
      setNotice(`Copied ${what}.`);
    } catch {
      setNotice(`Could not copy ${what}: the browser refused clipboard access.`);
    }
  }

  function menuItems(spanId: string): MenuItem[] {
    const s = findSpan(trace, spanId);
    if (!s) return [];
    if (s.kind === "run") {
      return [
        { id: "results", label: "Open results full width", icon: "expand", onSelect: () => setMode("results") },
        { id: "graph", label: "Show in graph", icon: "node", onSelect: () => (setMode("graph"), setPaneFocus(true)) },
        { id: "copy-run", label: "Copy run ID", onSelect: () => void copy(runId ?? "", "the run ID") },
      ];
    }
    const node = nodeOf(trace, s);
    const seqs = s.events.map((e) => e.seq);
    return [
      { id: "inspect", label: "Inspect", icon: "arrowRight", onSelect: () => showStep(s.id) },
      mode === "graph"
        ? { id: "waterfall", label: "Show in waterfall", icon: "gauge", onSelect: () => (setMode("waterfall"), showStep(s.id), setPaneFocus(true)) }
        : { id: "graph", label: "Show in graph", icon: "node", disabled: !node, onSelect: () => (setMode("graph"), showStep(s.id), setPaneFocus(true)) },
      { id: "copy-name", label: s.kind === "event" ? "Copy event text" : "Copy step name", onSelect: () => void copy(s.name, s.kind === "event" ? "the event text" : "the step name") },
      { id: "copy-seq", label: `Copy event seq ${seqs.length > 1 ? `${seqs[0]}–${seqs.at(-1)}` : seqs[0]}`, onSelect: () => void copy(seqs.join(","), "the event sequence numbers") },
      { id: "run", label: "Back to run results", icon: "play", onSelect: () => setStep(RUN_ROW) },
    ];
  }

  function openBenchmark(arm: string | null) {
    setFocusArm(arm);
    setTab("tournament");
  }

  /** A palette result: show the run results with that item, and move focus to it. */
  function showTarget(target: RunScopeTarget, via: PickSource) {
    setStep(RUN_ROW);
    setGraphPick(null);
    setSheet(false);
    if (target.kind === "finding" || target.kind === "hypothesis") {
      setEvidence(null);
      setTab("findings");
      requestAnimationFrame(() => {
        const el = [...(page.current?.querySelectorAll<HTMLElement>("[data-claim]") ?? [])].find((x) => x.dataset.claim === target.key);
        el?.scrollIntoView?.({ block: "center" });
        el?.focus({ preventScroll: true });
      });
    } else if (target.kind === "evidence") {
      // Plan-node evidence moves on to the Plan tab, as an evidence chip does.
      setTab("evidence");
      void openEvidence(target.id);
    } else if (target.kind === "candidate") {
      openBenchmark(target.key);
      requestAnimationFrame(() => page.current?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')?.focus());
    } else {
      setFocusArm(target.arm);
      setFocusSection({ section: "plan-diff", arm: target.arm, via });
      setTab("tournament");
    }
  }
  useEffect(() => {
    scopeTarget.current = showTarget;
  });

  function evidenceActions(node: EvidenceNode): ReactNode {
    const btn = (label: string, run: () => void) => (
      <button key={label} type="button" onClick={run} className="qc-btn-secondary qc-btn-sm">
        {label}
      </button>
    );
    const stepButton = (spanId: string | undefined) => (spanId ? btn("Show step", () => showStep(spanId)) : null);
    if (node.column === "evidence") {
      const kind = node.detail?.evidence.kind;
      const data = (node.detail?.evidence.data ?? {}) as Record<string, unknown>;
      const arm = typeof data.arm === "string" ? data.arm : (node.detail?.evidence.locator.match(/^\/(?:stats|correctness)\/([^/]+)\//)?.[1] ?? null);
      return [
        kind === "plan_node" ? btn("Show in plan", () => void openEvidence(node.id)) : null,
        stepButton(evidenceIndex.get(node.id)?.[0]),
        sandbox && (kind === "benchmark_metric" || kind === "correctness_check") ? btn("Open in benchmark", () => openBenchmark(arm)) : null,
      ];
    }
    if (node.column === "finding" || node.column === "hypothesis") {
      const match = stepForClaim(claimIndex, node.id);
      return [match.status === "found" ? stepButton(match.spanId) : <span key="none" className="text-xs text-muted">Step not recorded</span>, btn("Show in Findings", () => setTab("findings"))];
    }
    const arm = node.column === "candidate" ? node.id : node.verification.candidateKey;
    return sandbox ? btn("Open in benchmark", () => openBenchmark(arm)) : null;
  }

  // Palette entries and `[` `]` / `g f` `g p` `g t` `g r` for the result tabs (UI_UX §3.15).
  const tabCommands = useMemo<Command[]>(() => {
    const ids: Tab[] = ["findings", "evidence", "plan", ...(sandbox ? (["tournament"] as const) : []), "report"];
    const labels: Record<Tab, string> = { findings: "Findings", evidence: "Evidence", plan: "Plan", tournament: "Tournament", report: "Report" };
    const show = (t: Tab) => {
      setGraphPick(null);
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
      ...VIEWS.map((v) => ({ id: `view-${v.id}`, label: `Show ${v.label.toLowerCase()} view`, group: "This investigation" as const, run: () => setMode(v.id) })),
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
    { id: "evidence", label: "Evidence" },
    { id: "plan", label: "Plan" },
    ...(sandbox ? [{ id: "tournament" as const, label: "Tournament" }] : []),
    { id: "report", label: "Report" },
  ];

  const sealedSummary =
    sealedReport && !active ? (
      <ResultSummary
        report={sealedReport}
        onReport={() => {
          setStep(RUN_ROW);
          setGraphPick(null);
          setTab("report");
        }}
        onBenchmark={
          sandbox
            ? () => {
                setStep(RUN_ROW);
                setGraphPick(null);
                setTab("tournament");
              }
            : undefined
        }
      />
    ) : null;

  const results = (
    <section aria-label="Selection details" className="flex min-w-0 flex-col gap-4">
      <div role="tablist" aria-label="Results" className="flex gap-5 overflow-x-auto border-b border-border">
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
        <TournamentPanel
          experiments={experiments.data?.items ?? []}
          candidates={candidates.data?.items ?? []}
          runId={runId ?? undefined}
          focusArm={focusArm}
          focusSection={focusSection}
          onFocusDone={sectionDone}
        />
      ) : tab === "evidence" ? (
        <EvidenceExplorer
          findings={claims?.findings ?? []}
          hypotheses={claims?.hypotheses ?? []}
          candidates={candidates.data?.items ?? []}
          verifications={audits}
          evidence={resolved}
          actionsFor={evidenceActions}
        />
      ) : tab === "findings" ? (
        <FindingsPanel
          data={findings.data}
          onEvidence={(e) => void openEvidence(e)}
          activeEvidence={evidence?.evidence.id ?? null}
          stepFor={(key) => stepForClaim(claimIndex, key)}
          onShowStep={showStep}
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
  );

  const visits = selectedSpan?.kind === "node" ? trace.children.filter((c) => c.kind === "node" && c.name === selectedSpan.name) : undefined;
  const details = (embedded: boolean) =>
    selectedSpan && runId ? (
      <StepDetails
        key={selectedSpan.id}
        span={selectedSpan}
        runId={runId}
        embedded={embedded}
        visits={visits}
        onBack={() => {
          setSheet(false);
          setStep(RUN_ROW);
        }}
        onSelect={setStep}
        onOpenEvidence={(e) => {
          setSheet(false);
          void openEvidence(e);
        }}
        onActions={(at) => setMenu({ spanId: selectedSpan.id, at })}
        onClose={() => setSheet(false)}
      />
    ) : null;
  const notReached = graphPick ? (
    <section aria-label="Selection details" className="qc-panel flex flex-col gap-2 p-4">
      <p className="qc-eyebrow">Graph node</p>
      <h2 className="font-mono text-base font-semibold">{graphPick}</h2>
      <p className="text-sm text-muted">
        {active ? "No events recorded for this step yet." : "Not reached in this run: the run recorded no events for this step."}
      </p>
      <button type="button" onClick={() => setGraphPick(null)} className="qc-btn-secondary qc-btn-sm w-fit">
        Back to run results
      </button>
    </section>
  ) : null;

  const tracePane =
    mode === "graph" ? (
      <TraceGraph
        trace={trace}
        active={active}
        live={live}
        selectedNode={graphPick ?? nodeOf(trace, selectedSpan)}
        onSelectNode={selectNode}
        fillHeight={wide}
        focusRequest={paneFocus}
        onFocusDone={focusDone}
      />
    ) : (
      <TraceTree
        trace={trace}
        events={events}
        runLabel={r ? `Run #${r.runNumber}` : "Run"}
        live={live}
        stream={stream}
        active={active}
        selectedId={selectedSpan ? step : RUN_ROW}
        onSelect={(id) => {
          setGraphPick(null);
          setStep(id);
        }}
        onActivate={(id) => {
          if (!wide && id !== RUN_ROW) setSheet(true);
        }}
        onMenu={(spanId, at) => setMenu({ spanId, at })}
        focusRequest={paneFocus}
        onFocusDone={focusDone}
      />
    );

  function onSplitterKey(e: ReactKeyboardEvent<HTMLDivElement>) {
    const by = e.key === "ArrowLeft" ? INSPECTOR.step : e.key === "ArrowRight" ? -INSPECTOR.step : 0;
    if (e.key === "Home") setInspectorW(INSPECTOR.max);
    else if (e.key === "End") setInspectorW(INSPECTOR.min);
    else if (by) setInspectorW((w) => w + by);
    else return;
    e.preventDefault();
  }
  function onSplitterDown(e: ReactPointerEvent<HTMLDivElement>) {
    const host = split.current;
    if (!host) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    const right = host.getBoundingClientRect().right;
    const move = (ev: PointerEvent) => setResized(clampW(right - ev.clientX - 4));
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  let workspace: ReactNode;
  if (mode === "results") {
    workspace = results;
  } else if (wide) {
    workspace = (
      <div
        ref={split}
        className="grid h-[calc(100dvh-var(--qc-sticky)-2rem)] min-h-[560px] items-stretch"
        style={{ gridTemplateColumns: `minmax(0,1fr) 12px ${inspectorW}px` }}
      >
        <div className="flex min-h-0 min-w-0 flex-col">{tracePane}</div>
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize the details panel"
          aria-valuenow={inspectorW}
          aria-valuemin={INSPECTOR.min}
          aria-valuemax={INSPECTOR.max}
          tabIndex={0}
          onKeyDown={onSplitterKey}
          onPointerDown={onSplitterDown}
          className="group flex cursor-col-resize touch-none items-center justify-center"
        >
          <span aria-hidden="true" className="h-8 w-[3px] rounded-full bg-border-strong group-hover:bg-muted group-focus-visible:bg-accent" />
        </div>
        <div className="min-h-0 min-w-0 overflow-y-auto">{details(false) ?? notReached ?? results}</div>
      </div>
    );
  } else {
    workspace = (
      <div className="flex flex-col gap-5">
        <div className="flex max-h-[70dvh] min-h-0 flex-col">{tracePane}</div>
        {notReached ?? results}
      </div>
    );
  }

  return (
    <div ref={page} className="@container flex flex-col gap-4 [--qc-sticky:0px]">
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
              <Link href={`/app/replay/${r.id}`} className="qc-btn-secondary qc-btn-sm">
                <Icon name="replay" size={13} />
                <span className="hidden sm:inline">Reproducibility & replay</span>
                <span className="sm:hidden">Replay</span>
              </Link>
            ) : null}
            {r && active && r.status !== "cancelling" ? (
              <button type="button" onClick={() => cancel.mutate()} disabled={cancel.isPending} className="qc-btn-danger qc-btn-sm">
                Cancel run
              </button>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
          <div className="flex min-w-0 flex-col gap-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 tabIndex={-1} className="qc-page-title min-w-0 break-words outline-none">{investigation.data.title}</h1>
              {r ? <RunStatusPill status={r.status} /> : null}
            </div>
            {r ? (
              <p className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-[13px]">
                <StatusOrb tone={activity.tone} live={activity.animate} size={14} />
                <span className="font-medium text-ink">{activity.label}</span>
                <span className="text-muted">{activity.detail}</span>
              </p>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <RunSelector runs={runs} selectedId={runId} onSelect={selectRun} replayReports={replayReports} />
            {!summary && r ? <span className="font-mono text-xs text-muted">run {r.runNumber}</span> : null}
            <span className="font-mono text-xs text-muted">{r ? runModelLabel(r) : ""}</span>
          </div>
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

      {r ? <RunStats run={r} events={events} nowMs={clock} /> : null}

      {sealedSummary}

      {(() => {
        const inline = pending && r?.status === "awaiting_approval" ? pending : null;
        const shown = reviewed ?? inline;
        if (!shown || !runId) return null;
        return (
          <ApprovalReview
            key={shown.id}
            approval={shown}
            runId={runId}
            showCard={inline?.id === shown.id}
            open={reviewing === shown.id}
            onOpen={() => setReviewing(shown.id)}
            onClose={closeReview}
            investigationTitle={investigation.data?.title ?? ""}
            candidates={candidates.data?.items ?? []}
            hypotheses={claims?.hypotheses ?? []}
            onEvidence={(ev) => {
              setReviewing(null);
              void openEvidence(ev);
            }}
          />
        );
      })()}

      <div className="flex flex-wrap items-center gap-3">
        <div role="group" aria-label="Workspace view" className="inline-flex rounded-md bg-surface-2 p-0.5">
          {VIEWS.map((v) => (
            <button
              key={v.id}
              type="button"
              aria-pressed={mode === v.id}
              onClick={() => setMode(v.id)}
              className={`h-7 rounded px-3 text-[13px] pointer-coarse:h-10 ${mode === v.id ? "bg-surface text-ink shadow-sm" : "text-muted hover:text-ink"}`}
            >
              {v.label}
            </button>
          ))}
        </div>
        <span className="text-[13px] text-muted">
          {graph.nodes.size ? `${[...graph.nodes.values()].filter((n) => n.state !== "not_reached").length} of ${graph.nodes.size} graph steps reached` : ""}
        </span>
        {mode !== "results" && wide ? <span className="ml-auto hidden text-xs text-muted @4xl:inline">Right-click or Shift+F10 on a step for actions</span> : null}
      </div>

      {workspace}

      {menu ? <ContextMenu label="Step actions" at={menu.at} items={menuItems(menu.spanId)} onClose={() => setMenu(null)} /> : null}
      {sheet && !wide && selectedSpan ? (
        <BottomSheet label={`Step details: ${selectedSpan.name}`} onClose={() => setSheet(false)} ownHeader>
          {details(true)}
        </BottomSheet>
      ) : null}
    </div>
  );
}
