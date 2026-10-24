"use client";

import { useState, type ReactNode } from "react";
import { Icon } from "@/components/ui/Icon";
import { useMediaQuery } from "@/lib/ui/hooks";

/** Phones collapse the studio's secondary sections (UI_UX §3.17); wider screens keep them open. */
export const COMPACT_QUERY = "(max-width: 767px)";

export function useCompactStudio(): boolean {
  return useMediaQuery(COMPACT_QUERY);
}

/** A secondary studio section. On phones it is a disclosure with a title and a one-line summary
 * (several may be open at once); elsewhere it renders its content unchanged. `attention` keeps it
 * open by default and marks the summary, so a warning is never folded away unannounced. */
export function StudioSection({
  title,
  summary,
  compact,
  attention = false,
  children,
}: {
  title: string;
  summary: string;
  compact: boolean;
  attention?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(attention);
  if (!compact) return <>{children}</>;
  return (
    <details data-bench-section open={open} onToggle={(e) => setOpen(e.currentTarget.open)} className="group min-w-0 rounded-lg border border-border bg-surface">
      <summary className="flex min-h-12 cursor-pointer list-none items-center gap-3 px-4 py-2.5 select-none [&::-webkit-details-marker]:hidden">
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="text-sm font-semibold">{title}</span>
          <span className={`text-xs ${attention ? "text-inconclusive" : "text-muted"}`}>
            {attention ? <span className="sr-only">Needs attention: </span> : null}
            {summary}
          </span>
        </span>
        <Icon name="chevronDown" size={16} className="shrink-0 text-muted transition-transform group-open:rotate-180 motion-reduce:transition-none" />
      </summary>
      <div className="border-t border-border p-4 [&>section]:rounded-none [&>section]:border-0 [&>section]:bg-transparent [&>section]:p-0">{children}</div>
    </details>
  );
}
