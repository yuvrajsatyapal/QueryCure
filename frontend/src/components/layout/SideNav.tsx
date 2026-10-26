"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCommands } from "@/components/command/CommandProvider";
import { KeyHint } from "@/components/command/KeyHint";
import { Icon, type IconName } from "@/components/ui/Icon";
import { StatusIcon, StatusOrb, TONE_TEXT, runStatusMeta } from "@/components/ui/StatusPill";
import { investigationKeys, listInvestigations } from "@/lib/api/investigations";
import type { InvestigationPage } from "@/lib/api/types";
import { activeFirst } from "@/lib/investigations/dashboard";

interface NavItem {
  label: string;
  href: string;
  icon: IconName;
}

// Linear-style groups. Every entry is a real route: no placeholders, no dead links.
const MAIN: NavItem[] = [
  { label: "Dashboard", href: "/app", icon: "dashboard" },
  { label: "History", href: "/app/history", icon: "history" },
];
const WORKSPACE: NavItem[] = [
  { label: "Connections", href: "/app/connections", icon: "plug" },
  { label: "Demo gallery", href: "/demo", icon: "play" },
];
const SETTINGS: NavItem = { label: "Settings", href: "/app/settings", icon: "settings" };

// Shared with the dashboard's recent list, so the two never disagree and fetch once.
export const RECENT_LIMIT = 25;
export const recentKey = investigationKeys.list({ limit: RECENT_LIMIT });
export const LIVE_REFRESH_MS = 10_000;
const MAX_ACTIVE = 5;

/** Poll the recent list only while something in it is still in flight. */
export const recentRefetch = (data: InvestigationPage | undefined) => (activeFirst(data?.items ?? []).length ? LIVE_REFRESH_MS : false);

function isActive(pathname: string | null, href: string): boolean {
  if (!pathname) return false;
  if (href === "/app") return pathname === "/app";
  // An open investigation belongs to History, where it was picked from.
  if (href === "/app/history") return pathname.startsWith("/app/history") || /^\/app\/(investigations\/(?!new)|reports|replay)/.test(pathname);
  return pathname.startsWith(href);
}

function NavLink({ item, pathname, collapsed, onNavigate }: { item: NavItem; pathname: string | null; collapsed: boolean; onNavigate?: () => void }) {
  const active = isActive(pathname, item.href);
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      aria-label={collapsed ? item.label : undefined}
      title={collapsed ? item.label : undefined}
      className={`flex h-8 items-center gap-2.5 rounded-md text-sm font-medium ${collapsed ? "w-9 justify-center" : "px-2"} ${
        active ? "bg-hover text-ink" : "text-muted hover:bg-hover hover:text-ink"
      }`}
    >
      <Icon name={item.icon} size={16} className={active ? "text-accent" : "text-faint"} />
      {collapsed ? null : item.label}
    </Link>
  );
}

/** Investigations whose latest run is still in flight, taken from the recent list. */
function ActiveRuns({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const recent = useQuery({
    queryKey: recentKey,
    queryFn: ({ signal }) => listInvestigations({ limit: RECENT_LIMIT }, signal),
    refetchInterval: (q) => recentRefetch(q.state.data),
  });
  const active = activeFirst(recent.data?.items ?? []).slice(0, MAX_ACTIVE);
  if (!active.length) return null;
  return (
    <div className={`flex flex-col gap-0.5 ${collapsed ? "items-center" : ""}`}>
      {collapsed ? null : (
        <p id="active-runs" className="px-2 pb-1 text-xs font-medium text-muted">
          Active runs
        </p>
      )}
      <ul aria-label={collapsed ? "Active runs" : undefined} aria-labelledby={collapsed ? undefined : "active-runs"} className="flex flex-col gap-0.5">
        {active.map((item) => {
          const meta = runStatusMeta(item.latestRun?.status);
          return (
            <li key={item.id}>
              <Link
                href={`/app/investigations/${item.id}`}
                onClick={onNavigate}
                title={`${item.title} · ${meta.label}`}
                aria-label={collapsed ? `${item.title}, ${meta.label}` : undefined}
                className={`flex min-h-[30px] items-center gap-2.5 rounded-md text-[13px] text-ink hover:bg-hover ${collapsed ? "w-9 justify-center" : "px-2 pointer-coarse:py-1.5"}`}
              >
                {/* A polled snapshot, never confirmed activity: always still (UI_UX §3.6b). */}
                {collapsed ? <StatusIcon tone={meta.tone} size={15} /> : <StatusOrb tone={meta.tone} size={8} />}
                {collapsed ? null : (
                  <>
                    <span className="min-w-0 flex-1 truncate pointer-coarse:line-clamp-2 pointer-coarse:whitespace-normal pointer-coarse:break-words">{item.title}</span>
                    <span className={`shrink-0 font-mono text-xs ${TONE_TEXT[meta.tone]}`}>{meta.tone === "approval" ? "approval" : meta.label.toLowerCase()}</span>
                  </>
                )}
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function SideNav({ collapsed = false, onNavigate }: { collapsed?: boolean; onNavigate?: () => void }) {
  const pathname = usePathname();
  const { openPalette, mac } = useCommands();
  const group = (items: NavItem[], title?: string) => (
    <div className={`flex flex-col gap-0.5 ${collapsed ? "items-center" : ""}`}>
      {title && !collapsed ? <p className="px-2 pb-1 text-xs font-medium text-muted">{title}</p> : null}
      {items.map((item) => (
        <NavLink key={item.href} item={item} pathname={pathname} collapsed={collapsed} onNavigate={onNavigate} />
      ))}
    </div>
  );
  return (
    <nav aria-label="Main" className="flex min-h-0 flex-1 flex-col gap-5">
      <div className={`flex flex-col gap-1.5 ${collapsed ? "items-center" : ""}`}>
        <button
          type="button"
          onClick={() => {
            onNavigate?.();
            openPalette();
          }}
          aria-keyshortcuts={mac ? "Meta+K" : "Control+K"}
          aria-label={collapsed ? "Search or jump to…" : undefined}
          title={collapsed ? "Search or jump to…" : undefined}
          className={`qc-btn-ghost h-8 border border-border bg-surface text-[13px] font-normal ${collapsed ? "w-9 p-0" : "w-full justify-between px-2"}`}
        >
          <span className="flex items-center gap-2.5">
            <Icon name="search" size={15} className="text-faint" />
            {collapsed ? null : "Search or jump to…"}
          </span>
          {collapsed ? null : <KeyHint keys={["Mod", "K"]} mac={mac} />}
        </button>
        <Link
          href="/app/investigations/new"
          onClick={onNavigate}
          aria-label={collapsed ? "New investigation" : undefined}
          title={collapsed ? "New investigation" : undefined}
          className={`qc-btn-secondary h-8 shadow-sm ${collapsed ? "w-9 p-0" : "w-full justify-start"}`}
        >
          <Icon name="plus" size={15} className="text-accent" />
          {collapsed ? null : "New investigation"}
        </Link>
      </div>
      {group(MAIN)}
      <ActiveRuns collapsed={collapsed} onNavigate={onNavigate} />
      {group(WORKSPACE, "Workspace")}
      <div className={`mt-auto flex flex-col gap-0.5 ${collapsed ? "items-center" : ""}`}>
        <NavLink item={SETTINGS} pathname={pathname} collapsed={collapsed} onNavigate={onNavigate} />
      </div>
    </nav>
  );
}
