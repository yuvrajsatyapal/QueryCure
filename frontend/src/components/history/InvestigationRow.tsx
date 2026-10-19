import Link from "next/link";
import type { ReactNode } from "react";
import { StatusIcon, runStatusMeta } from "@/components/ui/StatusPill";
import type { InvestigationSummary } from "@/lib/api/types";

const MODE_LABEL: Record<string, string> = {
  offline: "Offline",
  live_inspection: "Live",
  sandbox_benchmark: "Sandbox",
};

const shortDate = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });

/** Compact age, Linear-style: "now", "5m", "15h", "3d", then the date. */
export function timeAgo(iso: string, now = Date.now()): string {
  const seconds = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  if (seconds < 60) return "now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h`;
  if (seconds < 7 * 86_400) return `${Math.floor(seconds / 86_400)}d`;
  return shortDate.format(new Date(iso));
}

/** One investigation as a dense Linear-style row: status, title, modes, outcome, age. */
export function InvestigationRow({ item, actions }: { item: InvestigationSummary; actions?: ReactNode }) {
  const run = item.latestRun;
  const meta = runStatusMeta(run?.status);
  return (
    <li className="group flex h-11 min-w-0 items-center gap-3 border-b border-border px-3 last:border-b-0 hover:bg-hover">
      <span title={meta.label} className="flex shrink-0">
        <StatusIcon tone={meta.tone} size={15} />
        <span className="sr-only">{meta.label}</span>
      </span>
      {run ? <span className="hidden w-8 shrink-0 font-mono text-[11px] text-muted sm:inline">#{run.runNumber}</span> : null}
      <Link href={`/app/investigations/${item.id}`} className="min-w-24 flex-1 truncate text-sm font-medium text-ink">
        {item.title}
      </Link>
      <span className="hidden shrink-0 gap-1 sm:flex">
        {item.modes.map((m) => (
          <span key={m} className="rounded border border-border px-1.5 py-px text-[11px] text-muted">
            {MODE_LABEL[m] ?? m}
          </span>
        ))}
      </span>
      <span className="hidden w-44 shrink-0 truncate text-right text-xs text-muted xl:inline">
        {run ? (run.outcome ? run.outcome.replaceAll("_", " ") : meta.label) : "no run"}
      </span>
      <time dateTime={item.createdAt} title={new Date(item.createdAt).toLocaleString()} className="w-12 shrink-0 text-right text-xs text-muted tabular-nums">
        {timeAgo(item.createdAt)}
      </time>
      {actions}
    </li>
  );
}
