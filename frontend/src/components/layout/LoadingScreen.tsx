"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { Icon } from "@/components/ui/Icon";
import { Logo } from "@/components/ui/Logo";

export type StepState = "wait" | "run" | "done";
export interface LoadingStep {
  label: string;
  state: StepState;
}

function StepMark({ state }: { state: StepState }) {
  if (state === "done") return <Icon name="check" size={15} className="text-verified" />;
  if (state === "run") return <span className="size-3.5 rounded-full border-2 border-border-strong border-t-accent motion-safe:animate-spin" />;
  return <span className="size-1.5 rounded-full bg-border-strong" />;
}

/** The full-screen "getting things ready" state for sign-in and sign-out (docs/design/prototypes/loading-screen).
 * `stalled` swaps the hint for a recovery panel, so a slow API never leaves a bare spinner. */
export function LoadingScreen({
  title,
  status,
  steps,
  hint,
  stalled,
}: {
  title: string;
  status: string;
  steps: LoadingStep[];
  hint?: string;
  stalled?: { title: string; body: string; onRetry: () => void };
}): ReactNode {
  const done = steps.filter((s) => s.state === "done").length;
  const progress = Math.max(4, Math.round((done / steps.length) * 100));
  return (
    <div className="fixed inset-0 z-[60] grid place-items-center overflow-y-auto bg-bg p-6">
      <div className="w-full max-w-[340px] text-center">
        <Logo size={44} className="qc-mark-busy mx-auto mb-5 text-ink" />
        <h1 className="mb-1 text-[17px] font-semibold tracking-tight">{title}</h1>
        <p role="status" aria-live="polite" className="mb-6 min-h-5 text-muted">
          {status}
        </p>
        <div aria-hidden="true" className="mb-5 h-[3px] overflow-hidden rounded-full bg-surface-2">
          <div className="h-full rounded-full bg-accent motion-safe:transition-[width] motion-safe:duration-500" style={{ width: `${progress}%` }} />
        </div>
        <ul className="flex flex-col gap-2.5 text-left text-[13px]">
          {steps.map((s) => (
            <li key={s.label} className={`flex items-center gap-2.5 ${s.state === "run" ? "text-ink" : s.state === "done" ? "text-muted" : "text-faint"}`}>
              <span className="grid size-4 shrink-0 place-items-center">
                <StepMark state={s.state} />
              </span>
              {s.label}
            </li>
          ))}
        </ul>
        {stalled ? (
          <div role="alert" className="mt-5 rounded-[10px] border border-border bg-surface p-4 text-left">
            <div className="mb-1.5 flex items-center gap-2.5">
              <span className="grid size-7 shrink-0 place-items-center rounded-full bg-accent-tint">
                <Icon name="alert" size={15} className="text-accent" />
              </span>
              <h2 className="text-sm font-semibold">{stalled.title}</h2>
            </div>
            <p className="mb-3.5 ml-[38px] text-[13px] leading-relaxed text-muted">{stalled.body}</p>
            <div className="ml-[38px] flex gap-2">
              <button
                type="button"
                onClick={stalled.onRetry}
                className="h-9 flex-1 rounded-md border border-accent bg-accent px-3 text-sm font-semibold whitespace-nowrap text-accent-fg hover:opacity-90"
              >
                Try again
              </button>
              <Link
                href="/"
                className="flex h-9 flex-1 items-center justify-center rounded-md border border-border-strong bg-surface-2 px-3 text-sm font-semibold whitespace-nowrap text-ink hover:bg-hover"
              >
                Back to home
              </Link>
            </div>
          </div>
        ) : hint ? (
          <p className="mt-6 text-xs text-faint">{hint}</p>
        ) : null}
      </div>
    </div>
  );
}
