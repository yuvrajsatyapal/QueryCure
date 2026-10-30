"use client";

import Link from "next/link";
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { Icon } from "@/components/ui/Icon";
import type { RunSummary } from "@/lib/api/types";
import type { ReplayReportMeta } from "@/lib/report/replay";
import { RunPicker, runKindLabel, runRelation } from "./RunPicker";

/** Below this the menu is a sheet at the bottom of the screen (UI_UX §3.6c). */
const NARROW_QUERY = "(max-width: 479.98px)";
const MENU_WIDTH = 416;
const MARGIN = 8;
const GAP = 4;
/** Open upwards only when the space below is shorter than this and the space above is larger. */
const MIN_BELOW = 240;
const ITEM = '[role="menuitemradio"]:not([aria-disabled="true"])';

type Placement = { narrow: true } | { narrow: false; style: CSSProperties };

function place(trigger: HTMLElement): Placement {
  if (typeof window.matchMedia === "function" && window.matchMedia(NARROW_QUERY).matches) return { narrow: true };
  const r = trigger.getBoundingClientRect();
  const width = Math.min(MENU_WIDTH, window.innerWidth - 2 * MARGIN);
  const left = Math.max(MARGIN, Math.min(r.left, window.innerWidth - width - MARGIN));
  const below = window.innerHeight - r.bottom - GAP - MARGIN;
  const above = r.top - GAP - MARGIN;
  if (below < MIN_BELOW && above > below) return { narrow: false, style: { left, width, bottom: window.innerHeight - r.top + GAP, maxHeight: above } };
  return { narrow: false, style: { left, width, top: r.bottom + GAP, maxHeight: below } };
}

/** The investigation header's run switcher (UI_UX §3.6c): a menu button whose menu groups the runs
 * (investigation runs, experiment replays) as `menuitemradio` rows. Arrows (wrapping), Home and End move;
 * Enter, Space or a click choose; Escape closes and returns focus; Tab closes and moves on; an
 * outside click closes. The selected sealed run's report link sits beside the trigger. A single
 * run is a plain label. */
export function RunSelector({
  runs,
  selectedId,
  onSelect,
  replayReports,
}: {
  runs: RunSummary[];
  selectedId: string | null;
  onSelect: (runId: string) => void;
  replayReports?: ReadonlyMap<string, ReplayReportMeta>;
}) {
  const [placement, setPlacement] = useState<Placement | null>(null);
  const open = placement !== null;
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const current = runs.find((r) => r.id === selectedId);
  const relation = current ? runRelation(current, runs) : null;
  const label = current ? `run ${current.runNumber} · ${runKindLabel(current.kind)}${relation ? ` ${relation}` : ""}` : "run";

  function show() {
    if (trigger.current) setPlacement(place(trigger.current));
  }
  function close(refocus: boolean) {
    setPlacement(null);
    if (refocus) trigger.current?.focus();
  }

  // On open: the selected run takes focus (or the first one).
  useLayoutEffect(() => {
    if (!open) return;
    const el = menu.current;
    (el?.querySelector<HTMLElement>(`${ITEM}[aria-checked="true"]`) ?? el?.querySelector<HTMLElement>(ITEM))?.focus({ preventScroll: false });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const outside = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!root.current?.contains(t) && !menu.current?.contains(t)) setPlacement(null);
    };
    const follow = (e: Event) => {
      // Scrolling inside the menu must not move it.
      if (e.target instanceof Node && menu.current?.contains(e.target)) return;
      if (trigger.current) setPlacement(place(trigger.current));
    };
    document.addEventListener("pointerdown", outside, true);
    window.addEventListener("resize", follow);
    window.addEventListener("scroll", follow, true);
    return () => {
      document.removeEventListener("pointerdown", outside, true);
      window.removeEventListener("resize", follow);
      window.removeEventListener("scroll", follow, true);
    };
  }, [open]);

  // The bottom sheet must not scroll the page behind it.
  const narrow = placement?.narrow === true;
  useEffect(() => {
    if (!narrow) return;
    const before = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = before;
    };
  }, [narrow]);

  if (!current) return null;
  if (runs.length < 2) return <span className="font-mono text-[11px] text-muted">{label}</span>;

  function onMenuKey(e: KeyboardEvent<HTMLDivElement>) {
    const all = Array.from(menu.current?.querySelectorAll<HTMLElement>(ITEM) ?? []);
    const i = all.indexOf(document.activeElement as HTMLElement);
    const move = (to: number) => all[(to + all.length) % all.length]?.focus();
    if (e.key === "ArrowDown") move(i < 0 ? 0 : i + 1);
    else if (e.key === "ArrowUp") move(i < 0 ? all.length - 1 : i - 1);
    else if (e.key === "Home") move(0);
    else if (e.key === "End") move(all.length - 1);
    else if (e.key === "Escape") close(true);
    else if (e.key === "Tab") {
      // No trap: focus goes back to the trigger and the browser's Tab moves on from there.
      close(true);
      return;
    } else return;
    e.preventDefault();
    e.stopPropagation();
  }

  return (
    <div ref={root} className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
      <button
        ref={trigger}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => (open ? close(false) : show())}
        onKeyDown={(e) => {
          if ((e.key === "ArrowDown" || e.key === "ArrowUp") && !open) {
            e.preventDefault();
            show();
          }
        }}
        className="qc-btn-ghost -ml-2 max-w-full min-w-0 justify-start gap-1 px-2 py-0.5 text-left font-mono text-[11px] font-normal whitespace-normal text-ink pointer-coarse:min-h-11"
      >
        <span className="min-w-0 break-words">{label}</span>
        <span className="shrink-0 text-muted">of {runs.length}</span>
        <Icon name="chevronDown" size={12} className={`text-muted transition-transform motion-reduce:transition-none ${open ? "rotate-180" : ""}`} />
      </button>
      {current.finalized ? (
        <Link href={`/app/reports/${current.id}`} aria-label="Open this run's report" className="text-xs text-link">
          This run&apos;s report
        </Link>
      ) : null}
      {placement
        ? createPortal(
            <>
              {placement.narrow ? <div aria-hidden="true" className="fixed inset-0 z-40 bg-[var(--scrim)]" /> : null}
              <div
                ref={menu}
                role="menu"
                aria-label="Runs of this investigation"
                data-run-menu=""
                onKeyDown={onMenuKey}
                style={placement.narrow ? undefined : placement.style}
                className={`fixed z-50 overflow-y-auto overscroll-contain border border-border-strong bg-surface-2 p-1.5 shadow-pop ${
                  placement.narrow
                    ? "qc-sheet-in inset-x-2 bottom-2 max-h-[min(70dvh,32rem)] rounded-xl pb-[max(0.375rem,env(safe-area-inset-bottom))]"
                    : `qc-menu-in rounded-[10px] ${"bottom" in placement.style ? "origin-bottom-left" : "origin-top-left"}`
                }`}
              >
                <RunPicker
                  runs={runs}
                  replayReports={replayReports}
                  selectedId={selectedId}
                  onSelect={(id) => {
                    close(true);
                    onSelect(id);
                  }}
                />
              </div>
            </>,
            document.body,
          )
        : null}
    </div>
  );
}
