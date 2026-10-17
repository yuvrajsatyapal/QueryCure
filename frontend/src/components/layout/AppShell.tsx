import Link from "next/link";
import type { ReactNode } from "react";
import { ThemeToggle } from "@/components/theme/ThemeToggle";
import { AccountMenu } from "./AccountMenu";
import { SessionGate } from "./SessionGate";
import { SideNav } from "./SideNav";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-full flex-1 flex-col">
      <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border bg-surface px-4">
        <Link href="/app" className="shrink-0 text-sm font-semibold tracking-tight text-ink">
          QueryCure
        </Link>
        <div className="flex min-w-0 items-center gap-3">
          <AccountMenu />
          <div className="shrink-0">
            <ThemeToggle />
          </div>
        </div>
      </header>
      <div className="flex flex-1 flex-col md:flex-row">
        <SideNav />
        <main className="min-w-0 flex-1 p-4 md:p-6">
          <SessionGate>{children}</SessionGate>
        </main>
      </div>
    </div>
  );
}
