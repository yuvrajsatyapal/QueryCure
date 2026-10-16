import Link from "next/link";
import type { ReactNode } from "react";
import { ThemeToggle } from "@/components/theme/ThemeToggle";

// The gallery reads the API in the browser; no session is needed.
export const instant = false;

export default function DemoLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-full flex-1 flex-col">
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-surface px-4">
        <Link href="/" className="text-sm font-semibold tracking-tight text-ink">
          QueryCure <span className="font-normal text-muted">· demo</span>
        </Link>
        <div className="flex items-center gap-3">
          <Link href="/app" className="text-sm text-link">
            Open the app
          </Link>
          <ThemeToggle />
        </div>
      </header>
      <main className="mx-auto w-full min-w-0 max-w-6xl flex-1 p-4 md:p-6">{children}</main>
    </div>
  );
}
