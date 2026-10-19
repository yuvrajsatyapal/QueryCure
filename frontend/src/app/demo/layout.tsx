import Link from "next/link";
import type { ReactNode } from "react";
import { ThemeToggle } from "@/components/theme/ThemeToggle";
import { Logo } from "@/components/ui/Logo";

// The gallery reads the API in the browser; no session is needed.
export const instant = false;

export default function DemoLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-full flex-1 flex-col">
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-border bg-sidebar px-4">
        <Link href="/" className="flex items-center gap-2 text-sm font-semibold tracking-tight text-ink">
          <Logo />
          QueryCure <span className="font-normal text-muted">· demo</span>
        </Link>
        <div className="flex items-center gap-1">
          <Link href="/app" className="qc-btn-ghost">
            Open the app
          </Link>
          <ThemeToggle />
        </div>
      </header>
      <main className="mx-auto w-full min-w-0 max-w-6xl flex-1 p-4 md:p-6">{children}</main>
    </div>
  );
}
