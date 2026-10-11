import Link from "next/link";
import type { ReactNode } from "react";
import { ThemeToggle } from "@/components/theme/ThemeToggle";
import { SessionGate } from "./SessionGate";
import { SideNav } from "./SideNav";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-full flex-1 flex-col">
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-surface px-4">
        <Link href="/app" className="text-sm font-semibold tracking-tight text-ink">
          QueryDoctor AI
        </Link>
        <ThemeToggle />
      </header>
      <div className="flex flex-1">
        <SideNav />
        <main className="flex-1 p-6">
          <SessionGate>{children}</SessionGate>
        </main>
      </div>
    </div>
  );
}
