"use client";

import Link from "next/link";
import { useState, useSyncExternalStore, type ReactNode } from "react";
import { CommandProvider } from "@/components/command/CommandProvider";
import { ThemeToggle } from "@/components/theme/ThemeToggle";
import { Icon } from "@/components/ui/Icon";
import { Logo } from "@/components/ui/Logo";
import { AccountMenu } from "./AccountMenu";
import { SessionGate } from "./SessionGate";
import { SideNav } from "./SideNav";

// The rail preference is a per-browser convenience; it falls back to expanded when storage is
// unavailable (private windows, blocked site data).
const RAIL_KEY = "qc.sidebar";
const listeners = new Set<() => void>();
function readRail(): boolean {
  try {
    return localStorage.getItem(RAIL_KEY) === "rail";
  } catch {
    return false;
  }
}
function writeRail(rail: boolean) {
  try {
    localStorage.setItem(RAIL_KEY, rail ? "rail" : "expanded");
  } catch {
    // Not persisted; the toggle still works for this page.
  }
  listeners.forEach((l) => l());
}
function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useSidebarRail(): [boolean, (rail: boolean) => void] {
  const rail = useSyncExternalStore(subscribe, readRail, () => false);
  return [rail, writeRail];
}

function SidebarBody({ collapsed = false, onToggle, onNavigate }: { collapsed?: boolean; onToggle?: () => void; onNavigate?: () => void }) {
  return (
    <>
      <div className={`flex items-center gap-2 ${collapsed ? "flex-col" : "justify-between px-1"}`}>
        <Link href="/app" onClick={onNavigate} aria-label={collapsed ? "QueryCure dashboard" : undefined} className="flex h-8 items-center gap-2 text-sm font-semibold tracking-tight">
          <Logo />
          {collapsed ? null : "QueryCure"}
        </Link>
        {onToggle ? (
          <button
            type="button"
            onClick={onToggle}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-expanded={!collapsed}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className="qc-btn-ghost size-8 p-0"
          >
            <Icon name="sidebar" size={16} />
          </button>
        ) : null}
      </div>
      <SideNav collapsed={collapsed} onNavigate={onNavigate} />
      <div className={`flex border-t border-border pt-3 ${collapsed ? "flex-col items-center gap-2" : "items-start gap-2 px-1"}`}>
        {collapsed ? null : (
          <div className="min-w-0 flex-1">
            <AccountMenu />
          </div>
        )}
        <ThemeToggle className="pointer-coarse:size-11" />
      </div>
    </>
  );
}

/** Linear-style shell: a quiet sidebar (240px, or a 56px icon rail) and a full-bleed content
 * area. Below md the sidebar becomes a drawer opened from a slim top bar. */
export function AppShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [rail, setRail] = useSidebarRail();

  return (
    <CommandProvider>
      <div className="flex min-h-full flex-1">
        <aside
          className={`sticky top-0 hidden h-screen shrink-0 flex-col gap-5 border-r border-border bg-sidebar py-3 md:flex ${rail ? "w-14 px-2" : "w-60 px-3"}`}
        >
          <SidebarBody collapsed={rail} onToggle={() => setRail(!rail)} />
        </aside>
        {open ? (
          <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
            <button type="button" aria-label="Close navigation" onClick={() => setOpen(false)} className="absolute inset-0 bg-[var(--scrim)]" />
            <aside className="relative flex h-full w-72 max-w-[85vw] flex-col gap-5 overflow-y-auto border-r border-border bg-sidebar px-3 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] shadow-pop">
              <SidebarBody onNavigate={() => setOpen(false)} />
            </aside>
          </div>
        ) : null}
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border bg-sidebar px-4 md:hidden">
            <button type="button" onClick={() => setOpen(true)} aria-label="Open navigation" className="qc-btn-ghost -ml-2 size-11 p-0">
              <Icon name="menu" size={18} />
            </button>
            <Link href="/app" className="flex items-center gap-2 text-sm font-semibold tracking-tight">
              <Logo />
              QueryCure
            </Link>
          </header>
          <main className="min-w-0 flex-1 px-4 py-5 md:px-8 md:py-7">
            <SessionGate>{children}</SessionGate>
          </main>
        </div>
      </div>
    </CommandProvider>
  );
}
