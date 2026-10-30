"use client";

import { useEffect, useState } from "react";
import { Icon } from "@/components/ui/Icon";

export type DetailRow = [label: string, value: string | null | undefined];

/** Identifiers and digests for reproducing a claim, one disclosure away so they do not compete
 * with the content they support on narrow screens. Every value is rendered complete (only
 * collapsed, never truncated), copies in full, and the disclosure opens for printing. */
export function TechnicalDetails({ label, summary, rows }: { label: string; summary?: string; rows: DetailRow[] }) {
  const [copied, setCopied] = useState("");
  const recorded = rows.filter(([, v]) => v).length;
  return (
    <details data-print-open className="group rounded-md border border-border text-xs text-muted">
      <summary className="flex cursor-pointer items-center gap-1.5 px-3 py-2 hover:text-ink pointer-coarse:min-h-11">
        <Icon name="chevronRight" size={12} className="shrink-0 transition-transform group-open:rotate-90 motion-reduce:transition-none" />
        <span>
          {label} · {summary ?? `${recorded} IDs and digests`}
        </span>
      </summary>
      <ul aria-label={label} className="flex flex-col gap-1 border-t border-border px-3 py-2">
        {rows.map(([k, v]) => (
          <li key={k} className="flex min-w-0 items-start gap-2">
            <span className="flex min-w-0 flex-1 flex-col sm:flex-row sm:gap-2">
              <span className="shrink-0 sm:w-40">{k}</span>
              <span className="min-w-0 font-mono break-all text-ink">{v ?? "not recorded"}</span>
            </span>
            {v ? (
              <button
                type="button"
                aria-label={`Copy ${k}`}
                title={`Copy ${k}`}
                onClick={() => {
                  void navigator.clipboard?.writeText(v).then(
                    () => setCopied(k),
                    () => undefined,
                  );
                }}
                className="grid size-6 shrink-0 place-items-center rounded text-muted hover:bg-hover hover:text-ink print:hidden pointer-coarse:size-10"
              >
                <Icon name="copy" size={12} />
              </button>
            ) : null}
          </li>
        ))}
      </ul>
      <p role="status" className="sr-only">
        {copied ? `Copied ${copied}` : ""}
      </p>
    </details>
  );
}

/** Opens every technical disclosure before the browser prints, so a printed report keeps them. */
export function useOpenDetailsForPrint() {
  useEffect(() => {
    const open = () => document.querySelectorAll<HTMLDetailsElement>("details[data-print-open]").forEach((d) => (d.open = true));
    window.addEventListener("beforeprint", open);
    return () => window.removeEventListener("beforeprint", open);
  }, []);
}
