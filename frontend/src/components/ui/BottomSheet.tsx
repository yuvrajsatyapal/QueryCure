"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { useModal } from "@/components/command/useModal";
import { Icon } from "./Icon";

/** A modal sheet from the bottom of a narrow screen (the trace inspector on phones). Esc, the
 * scrim and the close button dismiss it; focus stays inside and returns to the opener. With
 * `ownHeader` the content supplies the close button (marked `data-autofocus`) in its own header,
 * so the sheet has a single header row. */
export function BottomSheet({ label, onClose, children, ownHeader = false }: { label: string; onClose: () => void; children: ReactNode; ownHeader?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useModal(ref, onClose);
  useEffect(() => {
    ref.current?.querySelector<HTMLElement>("[data-autofocus]")?.focus();
    const body = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = body;
    };
  }, []);
  return (
    <div className="fixed inset-0 z-40 flex flex-col justify-end">
      <button type="button" aria-label="Close details" tabIndex={-1} onClick={onClose} className="absolute inset-0 bg-[var(--scrim)]" />
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        className="relative flex max-h-[85dvh] flex-col rounded-t-xl border-t border-border bg-surface pb-[env(safe-area-inset-bottom)] shadow-pop"
      >
        <div className="flex items-center justify-between gap-2 px-4 pt-2">
          <span aria-hidden="true" className="mx-auto h-1 w-10 rounded-full bg-border-strong" />
        </div>
        {ownHeader ? null : (
          <button type="button" data-autofocus onClick={onClose} aria-label="Close details" className="qc-btn-ghost absolute top-1.5 right-2 size-11 p-0">
            <Icon name="close" size={16} />
          </button>
        )}
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">{children}</div>
      </div>
    </div>
  );
}
