"use client";

import { useEffect, useRef, useState } from "react";
import { Icon } from "@/components/ui/Icon";
import type { RunSummary } from "@/lib/api/types";
import { RunPicker, runKindLabel, runRelation } from "./RunPicker";

/** The investigation header's run switcher: the run list (RunPicker) in a dropdown. A single run
 * is shown as a plain label. Closes on selection, Escape (focus returns) and outside clicks. */
export function RunSelector({
  runs,
  selectedId,
  onSelect,
}: {
  runs: RunSummary[];
  selectedId: string | null;
  onSelect: (runId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const current = runs.find((r) => r.id === selectedId);
  const relation = current ? runRelation(current, runs) : null;
  const label = current ? `run ${current.runNumber} · ${runKindLabel(current.kind)}${relation ? ` ${relation}` : ""}` : "run";

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open]);

  if (!current) return null;
  if (runs.length < 2) return <span className="font-mono text-[11px] text-muted">{label}</span>;

  return (
    <div
      ref={root}
      className="relative"
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) {
          e.stopPropagation();
          setOpen(false);
          trigger.current?.focus();
        }
      }}
    >
      <button
        ref={trigger}
        type="button"
        aria-expanded={open}
        aria-haspopup="true"
        onClick={() => setOpen((v) => !v)}
        className="qc-btn-ghost -ml-2 gap-1 px-2 py-0.5 font-mono text-[11px] font-normal text-ink"
      >
        {label}
        <span className="text-muted">of {runs.length}</span>
        <Icon name="chevronDown" size={12} className="text-muted" />
      </button>
      {open ? (
        <div className="absolute top-full left-0 z-30 mt-1 max-h-[60vh] w-[min(26rem,calc(100vw-2rem))] overflow-y-auto rounded-lg border border-border bg-surface p-2 shadow-pop">
          <RunPicker
            runs={runs}
            selectedId={selectedId}
            className="p-1"
            onSelect={(id) => {
              setOpen(false);
              onSelect(id);
            }}
          />
        </div>
      ) : null}
    </div>
  );
}
