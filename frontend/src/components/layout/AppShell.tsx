"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import { CommandProvider } from "@/components/command/CommandProvider";
import { ThemeToggle } from "@/components/theme/ThemeToggle";
import { Icon } from "@/components/ui/Icon";
import { Logo } from "@/components/ui/Logo";
import { AccountMenu } from "./AccountMenu";
import { SessionGate } from "./SessionGate";
import { SideNav } from "./SideNav";

function SidebarBody({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <>
      <div className="flex items-center justify-between gap-2 px-1">
        <Link href="/app" onClick={onNavigate} className="flex items-center gap-2 text-sm font-semibold tracking-tight">
          <Logo />
          QueryCure
        </Link>
        <ThemeToggle />
      </div>
      <SideNav onNavigate={onNavigate} />
      <div className="border-t border-border px-1 pt-3">
        <AccountMenu />
      </div>
    </>
  );
}

/** Linear-style shell: a quiet fixed sidebar and a full-bleed content area. Below md the sidebar
 * becomes a drawer opened from a slim top bar. */
export function AppShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);

  return (
    <CommandProvider>
      <div className="flex min-h-full flex-1">
        <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col gap-5 border-r border-border bg-sidebar px-3 py-3 md:flex">
          <SidebarBody />
        </aside>
        {open ? (
          <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
            <button type="button" aria-label="Close navigation" onClick={() => setOpen(false)} className="absolute inset-0 bg-black/40" />
            <aside className="relative flex h-full w-72 max-w-[85vw] flex-col gap-5 border-r border-border bg-sidebar px-3 py-3 shadow-pop">
              <SidebarBody onNavigate={() => setOpen(false)} />
            </aside>
          </div>
        ) : null}
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border bg-sidebar px-4 md:hidden">
            <button type="button" onClick={() => setOpen(true)} aria-label="Open navigation" className="qc-btn-ghost -ml-2 px-2">
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
