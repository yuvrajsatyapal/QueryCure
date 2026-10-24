"use client";

import { useQueries, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { ErrorNotice } from "@/components/common/ErrorNotice";
import { timeAgo } from "@/components/history/InvestigationRow";
import { RECENT_LIMIT, recentKey, recentRefetch } from "@/components/layout/SideNav";
import { Icon, type IconName } from "@/components/ui/Icon";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusIcon, StatusPill, runStatusMeta, type Tone } from "@/components/ui/StatusPill";
import { investigationKeys, getRun, listInvestigations } from "@/lib/api/investigations";
import { getApprovals, optimizationKeys } from "@/lib/api/optimization";
import type { InvestigationPage, InvestigationSummary } from "@/lib/api/types";
import { cappedCount, sumCounts, type CountResult } from "@/lib/investigations/counts";
import { activeFirst, medianRunMs, outcomeBreakdown, type OutcomeKey } from "@/lib/investigations/dashboard";
import { formatDuration } from "@/lib/format";

// The list endpoint's maximum page; a full page with a cursor is "100+", never a total (UI_UX §3.2).
const COUNT_PAGE = 100;
const LIVE_REFRESH_MS = 10_000;
const RECENT_ROWS = 8;
const DAY_MS = 86_400_000;
const STATUSES = ["queued", "running", "cancelling", "awaiting_approval", "completed", "failed", "cancelled"] as const;
const IN_FLIGHT: readonly string[] = ["queued", "running", "cancelling", "awaiting_approval"];
const countKey = (status: string) => investigationKeys.list({ status, limit: COUNT_PAGE });

const COUNTERS: { label: string; tone: Tone; statuses: (typeof STATUSES)[number][] }[] = [
  { label: "Running", tone: "running", statuses: ["queued", "running", "cancelling"] },
  { label: "Needs approval", tone: "approval", statuses: ["awaiting_approval"] },
  { label: "Completed", tone: "success", statuses: ["completed"] },
  { label: "Failed", tone: "failed", statuses: ["failed"] },
  { label: "Cancelled", tone: "neutral", statuses: ["cancelled"] },
];

const MODE_LABEL: Record<string, string> = { offline: "Offline", live_inspection: "Live inspection", sandbox_benchmark: "Sandbox benchmark" };

const OUTCOME: Record<OutcomeKey, { label: string; short: string; tone: Tone; bar: string }> = {
  verified_recommendation: { label: "Verified recommendation", short: "verified", tone: "success", bar: "bg-verified" },
  unverified_recommendations: { label: "Unverified recommendations", short: "unverified", tone: "neutral", bar: "bg-hypothesis" },
  no_action_needed: { label: "No action needed", short: "no action needed", tone: "neutral", bar: "bg-border-strong" },
  inconclusive: { label: "Inconclusive", short: "inconclusive", tone: "warning", bar: "bg-inconclusive" },
  completed: { label: "Completed", short: "completed", tone: "success", bar: "bg-verified/60" },
  failed: { label: "Failed", short: "failed", tone: "failed", bar: "bg-rejected" },
  cancelled: { label: "Cancelled", short: "cancelled", tone: "neutral", bar: "bg-faint" },
};
const OUTCOME_ORDER = Object.keys(OUTCOME) as OutcomeKey[];

/** Poll only while the cache shows something in flight, so finished runs move tiles promptly. */
function liveInterval(client: QueryClient): number | false {
  const busy = IN_FLIGHT.some((st) => (client.getQueryData<InvestigationPage>(countKey(st))?.items.length ?? 0) > 0);
  return busy ? LIVE_REFRESH_MS : false;
}

/** The latest run's outcome in words, or its status while it has none. */
function outcomeMeta(item: InvestigationSummary): { tone: Tone; label: string } {
  const run = item.latestRun;
  if (run?.status === "completed" && run.outcome) return OUTCOME[run.outcome as OutcomeKey] ?? { tone: "success", label: run.outcome.replaceAll("_", " ") };
  return runStatusMeta(run?.status);
}

function untilLabel(iso: string, now: number): string {
  const min = Math.round((Date.parse(iso) - now) / 60_000);
  if (min <= 0) return "expired";
  return min < 60 ? `expires in ${min}m` : `expires in ${Math.floor(min / 60)}h ${String(min % 60).padStart(2, "0")}m`;
}

function Meter({ label, used, limit }: { label: string; used: number; limit: number }) {
  const pct = Math.min(100, Math.round((used / Math.max(limit, 1)) * 100));
  return (
    <div className="flex w-24 flex-col gap-1" title={`${label}: ${used} of ${limit}`}>
      <div className="flex justify-between text-xs text-muted">
        <span>{label}</span>
        <span className="font-mono tabular-nums">
          <span className="text-ink">{used}</span>/{limit}
        </span>
      </div>
      <div className="h-1 rounded-full bg-surface-2" role="meter" aria-label={label} aria-valuenow={used} aria-valuemin={0} aria-valuemax={limit}>
        <div className={`h-1 rounded-full ${pct >= 80 ? "bg-inconclusive" : "bg-muted"}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

/** One in-flight investigation: what it is waiting on, from the run and approval records. */
function ActiveRow({ item }: { item: InvestigationSummary }) {
  const run = item.latestRun!;
  const meta = runStatusMeta(run.status);
  const href = `/app/investigations/${item.id}`;
  const waiting = run.status === "awaiting_approval";
  const detail = useQuery({
    queryKey: investigationKeys.run(run.id),
    queryFn: ({ signal }) => getRun(run.id, signal),
    enabled: run.status === "running" || run.status === "cancelling",
    refetchInterval: LIVE_REFRESH_MS,
  });
  const approvals = useQuery({
    queryKey: optimizationKeys.approvals(run.id),
    queryFn: ({ signal }) => getApprovals(run.id, signal),
    enabled: waiting,
  });
  const pending = approvals.data?.items.find((a) => a.status === "pending");
  const expiry = pending ? untilLabel(pending.expiresAt, approvals.dataUpdatedAt) : null;
  const usage = detail.data?.usage ?? {};

  let line: string;
  if (waiting) line = pending ? `Round ${pending.round + 1} · ${pending.payload.candidates.length} candidate${pending.payload.candidates.length === 1 ? "" : "s"}` : "Paused until you review the candidates";
  else if (run.status === "queued") line = "Waiting for a worker to claim the job";
  else if (run.status === "cancelling") line = "Stopping after the current step";
  else line = run.startedAt ? `Started ${timeAgo(run.startedAt)} ago` : "Starting";
  if (line.endsWith("now ago")) line = "Started just now";

  return (
    <li className={`flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-border px-4 py-3.5 last:border-b-0 ${waiting ? "bg-approval/5" : ""}`}>
      <div className="flex min-w-0 flex-1 basis-64 flex-col gap-1.5">
        <Link href={href} title={item.title} className="min-w-0 truncate text-sm font-semibold text-ink hover:underline pointer-coarse:line-clamp-2 pointer-coarse:whitespace-normal pointer-coarse:break-words">
          {item.title}
        </Link>
        <div className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1 text-[13px] text-muted sm:flex-nowrap">
          <StatusPill tone={meta.tone} label={meta.label} />
          <span className="min-w-0 sm:truncate">{line}</span>
          {expiry ? <span className={`shrink-0 font-mono text-xs ${expiry === "expired" ? "text-rejected" : "text-inconclusive"}`}>{expiry}</span> : <span className="shrink-0 font-mono text-xs">run {run.runNumber}</span>}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        {detail.data ? (
          <>
            <Meter label="LLM calls" used={usage.llmCalls ?? 0} limit={detail.data.budget.llmCalls} />
            <Meter label="Tools" used={usage.toolCalls ?? 0} limit={detail.data.budget.toolCalls} />
          </>
        ) : null}
        <Link href={href} className={waiting ? "qc-btn-primary" : "qc-btn-secondary"}>
          {waiting ? "Review candidates" : "Open"}
        </Link>
      </div>
    </li>
  );
}

const START: { href: string; icon: IconName; title: string; text: string }[] = [
  { href: "/app/investigations/new", icon: "plus", title: "New investigation", text: "Paste a query, upload an EXPLAIN plan or pick a demo workload." },
  { href: "/app/connections", icon: "plug", title: "Connect a database", text: "Read-only inspection with plain EXPLAIN, never ANALYZE." },
  { href: "/demo", icon: "play", title: "Demo gallery", text: "Prerecorded investigations, end to end, labelled as such." },
];

// `now` is when the list was fetched, so "last 24 h" matches the data on screen.
function Unavailable() {
  return <p className="p-4 text-sm text-muted">Not available while the investigation list can&apos;t be loaded.</p>;
}

function ActivePanel({ items, loading, failed, now }: { items: InvestigationSummary[]; loading: boolean; failed: boolean; now: number }) {
  const active = activeFirst(items);
  const concluded = outcomeBreakdown(items.filter((i) => i.latestRun?.finishedAt && now - Date.parse(i.latestRun.finishedAt) < DAY_MS));
  return (
    <section aria-labelledby="dash-active" className="qc-panel flex min-w-0 flex-col">
      <div className="qc-panel-header">
        <h2 id="dash-active" className="qc-section-title">
          Active investigations
        </h2>
        {active.length ? <span className="qc-tag font-mono">{active.length}</span> : null}
        <span className="ml-auto hidden text-[13px] text-muted sm:inline">{active.length ? "Runs that need you come first" : ""}</span>
      </div>
      {failed ? (
        <Unavailable />
      ) : loading ? (
        <Skeleton label="Loading active investigations" lines={3} className="p-4" />
      ) : active.length ? (
        <ul className="flex flex-col">
          {active.map((item) => (
            <ActiveRow key={item.id} item={item} />
          ))}
        </ul>
      ) : (
        <div className="flex flex-1 flex-col gap-4 p-4">
          <p className="text-sm text-muted">Nothing in flight. Start with a slow query, or open a prerecorded demo to see a full run.</p>
          <ul className="grid gap-2 sm:grid-cols-3">
            {START.map((s) => (
              <li key={s.href}>
                <Link href={s.href} className="flex h-full gap-3 rounded-lg border border-border p-3 hover:border-border-strong hover:bg-hover">
                  <span className="flex size-7 shrink-0 items-center justify-center rounded-md border border-border bg-surface-2 text-muted">
                    <Icon name={s.icon} size={14} />
                  </span>
                  <span className="flex min-w-0 flex-col gap-0.5">
                    <span className="text-sm font-medium">{s.title}</span>
                    <span className="text-xs text-muted">{s.text}</span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
      {concluded.total ? (
        <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-border px-4 py-3">
          <span className="text-[13px] text-muted">
            <span className="font-medium text-ink">Last 24 h</span> · concluded runs
          </span>
          <ul className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px]">
            {OUTCOME_ORDER.filter((k) => concluded.parts.some((p) => p.key === k)).map((k) => (
              <li key={k} className="flex items-center gap-1.5">
                <StatusIcon tone={OUTCOME[k].tone} size={13} />
                <span className="font-mono tabular-nums">{concluded.parts.find((p) => p.key === k)!.count}</span>
                <span className="text-muted">{OUTCOME[k].short}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function OutcomesPanel({ items, failed }: { items: InvestigationSummary[]; failed: boolean }) {
  const b = outcomeBreakdown(items);
  const parts = OUTCOME_ORDER.map((key) => ({ key, count: b.parts.find((p) => p.key === key)?.count ?? 0 })).filter((p) => p.count);
  const median = medianRunMs(items);
  return (
    <section aria-labelledby="dash-outcomes" className="qc-panel flex min-w-0 flex-col">
      <div className="qc-panel-header">
        <h2 id="dash-outcomes" className="qc-section-title">
          Run outcomes
        </h2>
        <span className="ml-auto text-[13px] text-muted" title={`Latest run of each of the ${RECENT_LIMIT} most recent investigations, whenever it finished`}>
          Sample · {RECENT_LIMIT} most recent
        </span>
      </div>
      {failed ? (
        <Unavailable />
      ) : (
        <div className="flex flex-1 flex-col gap-3 p-4">
          {b.total ? (
            <>
              <div className="flex h-2.5 gap-0.5 overflow-hidden rounded-[3px]" role="img" aria-label={parts.map((p) => `${p.count} ${OUTCOME[p.key].label}`).join(", ")}>
                {parts.map((p) => (
                  <span key={p.key} className={OUTCOME[p.key].bar} style={{ flex: p.count }} />
                ))}
              </div>
              <ul className="flex flex-col gap-2.5">
                {parts.map((p) => (
                  <li key={p.key} className="flex items-center gap-2.5 text-[13px]">
                    <StatusIcon tone={OUTCOME[p.key].tone} size={14} />
                    <span className="flex-1">{OUTCOME[p.key].label}</span>
                    <span className="font-mono tabular-nums">{p.count}</span>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="text-sm text-muted">No concluded runs yet. Outcomes appear here once a run finishes.</p>
          )}
          <div className="mt-auto flex items-baseline gap-2 border-t border-border pt-3">
            <span className="qc-label">Median run time</span>
            <span className="ml-auto font-mono text-base font-medium">{median ? formatDuration(median.ms) : "—"}</span>
          </div>
          <p className="-mt-1.5 text-xs text-muted">
            {b.total ? `${b.total} concluded` : "None concluded"} · latest run of each of the {RECENT_LIMIT} most recent investigations, not a time window.
            {median ? ` Median of ${median.n} completed run${median.n === 1 ? "" : "s"}.` : " No completed runs with timestamps."}
          </p>
        </div>
      )}
    </section>
  );
}

function RecentResults({ items, loading, failed }: { items: InvestigationSummary[]; loading: boolean; failed: boolean }) {
  const rows = items.slice(0, RECENT_ROWS);
  return (
    <section aria-labelledby="dash-recent" className="qc-panel min-w-0 overflow-hidden">
      <div className="qc-panel-header">
        <h2 id="dash-recent" className="qc-section-title">
          Recent investigations
        </h2>
        <Link href="/app/history" className="ml-auto text-[13px] text-link hover:underline">
          Open History →
        </Link>
      </div>
      {failed ? (
        <Unavailable />
      ) : loading ? (
        <Skeleton label="Loading recent investigations" lines={4} className="p-4" />
      ) : rows.length ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="h-[34px] border-b border-border text-left text-xs text-muted">
                <th scope="col" className="hidden w-56 px-4 font-medium sm:table-cell">
                  Outcome
                </th>
                <th scope="col" className="px-4 font-medium sm:px-3">
                  Investigation
                </th>
                <th scope="col" className="hidden w-44 px-3 font-medium md:table-cell">
                  Mode
                </th>
                <th scope="col" className="hidden w-20 px-3 font-medium sm:table-cell">
                  Run
                </th>
                <th scope="col" className="w-24 px-4 text-right font-medium">
                  Updated
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((item) => {
                const o = outcomeMeta(item);
                const when = item.latestRun?.finishedAt ?? item.latestRun?.startedAt ?? item.createdAt;
                return (
                  <tr key={item.id} className="h-11 border-b border-border last:border-b-0 hover:bg-hover">
                    <td className="hidden px-4 sm:table-cell">
                      <StatusPill tone={o.tone} label={o.label} />
                    </td>
                    <td className="max-w-0 px-4 py-2.5 sm:px-3 sm:py-0">
                      <Link href={`/app/investigations/${item.id}`} title={item.title} className="block truncate font-medium text-ink hover:underline pointer-coarse:line-clamp-2 pointer-coarse:whitespace-normal pointer-coarse:break-words">
                        {item.title}
                      </Link>
                      <span className="mt-1.5 flex sm:hidden">
                        <StatusPill tone={o.tone} label={o.label} />
                      </span>
                    </td>
                    <td className="hidden truncate px-3 text-muted md:table-cell">{item.modes.map((m) => MODE_LABEL[m] ?? m).join(" + ")}</td>
                    <td className="hidden px-3 font-mono text-[13px] text-muted sm:table-cell">{item.latestRun ? `run ${item.latestRun.runNumber}` : "—"}</td>
                    <td className="px-4 text-right align-top pt-3 font-mono text-[13px] text-muted tabular-nums sm:pt-0 sm:align-middle">
                      <time dateTime={when} title={new Date(when).toLocaleString()}>
                        {timeAgo(when)}
                      </time>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="flex flex-col items-start gap-3 p-6">
          <p className="text-sm text-muted">Nothing investigated yet.</p>
          <Link href="/app/investigations/new" className="qc-btn-secondary">
            Start an investigation
          </Link>
        </div>
      )}
    </section>
  );
}

/** One status tile. "N+" is a lower bound, said in words to screen readers too. */
function CountTile({ label, tone, count }: { label: string; tone: Tone; count: CountResult | null }) {
  return (
    <div className="-mb-px -ml-px flex flex-col gap-1 border-b border-l border-border px-4 py-3">
      <span className="flex items-center gap-1.5 text-xs font-medium text-muted">
        <StatusIcon tone={tone} size={12} />
        {label}
      </span>
      <span
        className="font-mono text-xl font-medium tabular-nums"
        title={count?.capped ? `At least ${count.value}; the list endpoint reports no total` : undefined}
      >
        {count ? count.label : "–"}
        {count?.capped ? <span className="sr-only"> (at least {count.value})</span> : null}
      </span>
    </div>
  );
}

export function DashboardView() {
  const client = useQueryClient();
  const recent = useQuery({
    queryKey: recentKey,
    queryFn: ({ signal }) => listInvestigations({ limit: RECENT_LIMIT }, signal),
    refetchInterval: (q) => recentRefetch(q.state.data) || liveInterval(client),
  });
  const counts = useQueries({
    queries: STATUSES.map((status) => ({
      queryKey: countKey(status),
      queryFn: ({ signal }: { signal: AbortSignal }) => listInvestigations({ status, limit: COUNT_PAGE }, signal),
      refetchInterval: () => liveInterval(client),
    })),
    combine: (results) => new Map(STATUSES.map((st, i) => [st, cappedCount(results[i]?.data)] as const)),
  });
  const tiles = COUNTERS.map((c) => ({ ...c, count: sumCounts(c.statuses.map((st) => counts.get(st) ?? null)) }));
  const anyCapped = tiles.some((t) => t.count?.capped);
  const items = recent.data?.items ?? [];
  // A failed refetch keeps showing the last good data; only a load with no data is "unavailable".
  const failed = recent.isError && !recent.data;

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-4">
      <div className="mb-1 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="qc-page-title">Dashboard</h1>
          <p className="text-sm text-muted">What needs you, what finished, and how runs are going.</p>
        </div>
      </div>

      <ErrorNotice error={recent.error} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1.75fr)_minmax(0,1fr)]">
        <ActivePanel items={items} loading={recent.isPending} failed={failed} now={recent.dataUpdatedAt} />
        <OutcomesPanel items={items} failed={failed} />
      </div>

      <RecentResults items={items} loading={recent.isPending} failed={failed} />

      <section aria-label="Investigations by status" className="qc-panel grid grid-cols-2 overflow-hidden sm:grid-cols-3 lg:grid-cols-5">
        {tiles.map((t) => (
          <CountTile key={t.label} label={t.label} tone={t.tone} count={t.count} />
        ))}
      </section>
      {anyCapped ? <p className="-mt-2 text-xs text-muted">“100+” means at least 100: the list endpoint returns up to {COUNT_PAGE} per request and no total.</p> : null}
    </div>
  );
}
