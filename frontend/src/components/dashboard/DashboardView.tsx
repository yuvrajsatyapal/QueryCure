"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { ErrorNotice } from "@/components/common/ErrorNotice";
import { InvestigationRow } from "@/components/history/InvestigationRow";
import { Icon, type IconName } from "@/components/ui/Icon";
import { StatusIcon, type Tone } from "@/components/ui/StatusPill";
import { listInvestigations } from "@/lib/api/investigations";

const RECENT = 25;

const COUNTERS: { label: string; tone: Tone; statuses: string[] }[] = [
  { label: "Running", tone: "running", statuses: ["queued", "running", "cancelling"] },
  { label: "Needs approval", tone: "approval", statuses: ["awaiting_approval"] },
  { label: "Completed", tone: "success", statuses: ["completed"] },
  { label: "Failed", tone: "failed", statuses: ["failed"] },
];

const START: { href: string; icon: IconName; title: string; text: string }[] = [
  { href: "/app/investigations/new", icon: "plus", title: "New investigation", text: "Paste a query, upload an EXPLAIN plan or pick a demo workload." },
  { href: "/app/connections", icon: "plug", title: "Connect a database", text: "Read-only inspection with plain EXPLAIN, never ANALYZE." },
  { href: "/demo", icon: "play", title: "Demo gallery", text: "Prerecorded investigations, end to end, labelled as such." },
];

export function DashboardView() {
  const recent = useQuery({
    queryKey: ["investigations", "list", { limit: RECENT }],
    queryFn: ({ signal }) => listInvestigations({ limit: RECENT }, signal),
  });
  const items = recent.data?.items ?? [];
  const attention = items.filter((i) => ["awaiting_approval", "running", "queued"].includes(i.latestRun?.status ?? ""));

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-7">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Dashboard</h1>
          <p className="text-sm text-muted">Investigations in flight, and what finished recently.</p>
        </div>
        <Link href="/app/investigations/new" className="qc-btn-primary">
          <Icon name="plus" size={14} />
          New investigation
        </Link>
      </div>

      <section aria-label="Recent status" className="grid grid-cols-2 overflow-hidden qc-panel md:grid-cols-[1.2fr_1.2fr_1fr_0.8fr]">
        {COUNTERS.map((c, i) => {
          const n = items.filter((x) => c.statuses.includes(x.latestRun?.status ?? "")).length;
          return (
            <div key={c.label} className={`flex flex-col gap-1 p-4 ${i ? "border-l border-border" : ""} ${i === 2 ? "max-md:border-l-0 max-md:border-t" : ""} ${i === 3 ? "max-md:border-t" : ""}`}>
              <span className="flex items-center gap-1.5 text-xs text-muted">
                <StatusIcon tone={c.tone} size={12} />
                {c.label}
              </span>
              <span className="text-2xl font-semibold tabular-nums">{recent.isSuccess ? n : "–"}</span>
            </div>
          );
        })}
      </section>
      <p className="-mt-5 text-xs text-muted">Counts cover your {RECENT} most recent investigations.</p>

      <ErrorNotice error={recent.error} />

      <div className="grid grid-cols-1 gap-7 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="flex min-w-0 flex-col gap-7">
          {attention.length ? (
            <section aria-label="In progress" className="flex flex-col gap-2">
              <h2 className="text-sm font-semibold">In progress</h2>
              <ul className="qc-panel overflow-hidden">
                {attention.map((item) => (
                  <InvestigationRow key={item.id} item={item} />
                ))}
              </ul>
            </section>
          ) : null}
          <section aria-label="Recent investigations" className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold">Recent investigations</h2>
              <Link href="/app/history" className="flex items-center gap-1 text-xs text-muted hover:text-ink">
                View all <Icon name="arrowRight" size={12} />
              </Link>
            </div>
            {recent.isPending ? (
              <p className="text-sm text-muted">Loading…</p>
            ) : items.length ? (
              <ul className="qc-panel overflow-hidden">
                {items.slice(0, 10).map((item) => (
                  <InvestigationRow key={item.id} item={item} />
                ))}
              </ul>
            ) : (
              <div className="qc-panel flex flex-col items-start gap-3 p-8">
                <p className="text-sm text-muted">Nothing investigated yet. Start with a slow query, or open a prerecorded demo to see a full run.</p>
                <Link href="/app/investigations/new" className="qc-btn-secondary">
                  Start an investigation
                </Link>
              </div>
            )}
          </section>
        </div>
        <aside aria-label="Get started" className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold">Get started</h2>
          <ul className="flex flex-col gap-2">
            {START.map((s) => (
              <li key={s.href}>
                <Link href={s.href} className="qc-panel flex gap-3 p-3 hover:border-border-strong hover:bg-hover">
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
        </aside>
      </div>
    </div>
  );
}
