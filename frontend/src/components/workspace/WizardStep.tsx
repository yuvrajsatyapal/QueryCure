"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { Icon } from "@/components/ui/Icon";

export type StepState = "active" | "done" | "upcoming";

/** One step of the guided flow: numbered header, a one-line summary once done, and its body while open. */
export function WizardStep({
  index,
  title,
  state,
  summary,
  onEdit,
  focusOnOpen,
  children,
}: {
  index: number;
  title: string;
  state: StepState;
  summary?: ReactNode;
  onEdit?: () => void;
  /** Move focus to the heading when this step opens (not on first render). */
  focusOnOpen: boolean;
  children: ReactNode;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  const id = `wizard-step-${index}`;
  useEffect(() => {
    if (state === "active" && focusOnOpen) heading.current?.focus();
  }, [state, focusOnOpen]);

  return (
    <li aria-current={state === "active" ? "step" : undefined} className="relative flex gap-3">
      <span
        aria-hidden="true"
        className={`mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full border text-xs font-semibold ${
          state === "active"
            ? "border-accent bg-accent text-accent-fg"
            : state === "done"
              ? "border-border-strong bg-surface-2 text-ink"
              : "border-border text-muted"
        }`}
      >
        {state === "done" ? <Icon name="check" size={12} /> : index + 1}
      </span>
      <section aria-labelledby={id} className="flex min-w-0 flex-1 flex-col gap-3 pb-5">
        <div className="flex min-h-6 flex-wrap items-center justify-between gap-2">
          <h2
            id={id}
            ref={heading}
            tabIndex={-1}
            className={`text-sm font-semibold ${state === "upcoming" ? "text-muted" : "text-ink"}`}
          >
            <span className="sr-only">Step {index + 1}: </span>
            {title}
            {state === "done" ? <span className="sr-only"> (done)</span> : null}
          </h2>
          {state === "done" && onEdit ? (
            <button type="button" onClick={onEdit} className="qc-btn-ghost px-2 py-0.5 text-xs" aria-label={`Edit ${title}`}>
              Edit
            </button>
          ) : null}
        </div>
        {state === "done" && summary ? <div className="min-w-0 text-sm text-muted">{summary}</div> : null}
        {state === "active" ? children : null}
      </section>
    </li>
  );
}
