"use client";

import { useCallback, useRef, useState, type FocusEvent, type PointerEvent, type ReactNode } from "react";

// A spring with a little overshoot, as a CSS easing, so the label glides to the next item and settles.
const SPRING = "linear(0, 0.28 7%, 0.74 17%, 1.05 31%, 1.08 38%, 1.01 55%, 0.995 70%, 1)";
const SLIDE_MS = 420;
const REVEAL_MS = 260;
const GAP_PX = 10;

interface Tip {
  label: string;
  x: number;
  y: number;
}

/** Hover and keyboard-focus labels for the icon rail. One floating label follows the pointer from
 * item to item on a spring and reveals with a clip-path; it reads each item's `title`, which is
 * taken off the element while the label shows so the browser's own tooltip does not double it. */
export function useRailTooltip(enabled: boolean) {
  const [tip, setTip] = useState<Tip | null>(null);
  const [slide, setSlide] = useState(false);
  const current = useRef<HTMLElement | null>(null);
  const visible = useRef(false);

  const release = useCallback(() => {
    const el = current.current;
    if (el) {
      const label = el.dataset.railTip;
      // If React already wrote a fresh title (the theme label changes on click), keep that one.
      if (label && !el.hasAttribute("title")) el.setAttribute("title", label);
      delete el.dataset.railTip;
    }
    current.current = null;
  }, []);

  const hide = useCallback(() => {
    release();
    visible.current = false;
    setTip(null);
  }, [release]);

  const show = useCallback(
    (target: EventTarget | null) => {
      if (!enabled || !(target instanceof Element)) return hide();
      const el = target.closest<HTMLElement>("[title], [data-rail-tip]");
      if (!el) return hide();
      if (el === current.current) return;
      release();
      const label = el.getAttribute("title") ?? el.dataset.railTip;
      if (!label) return hide();
      el.dataset.railTip = label;
      el.removeAttribute("title");
      current.current = el;
      const rect = el.getBoundingClientRect();
      // Glide only when moving between items; the first reveal appears in place.
      setSlide(visible.current);
      visible.current = true;
      setTip({ label, x: rect.right + GAP_PX, y: rect.top + rect.height / 2 });
    },
    [enabled, hide, release],
  );

  const bind = {
    onPointerOver: (e: PointerEvent) => {
      if (e.pointerType !== "touch") show(e.target);
    },
    onPointerLeave: hide,
    onFocus: (e: FocusEvent) => {
      if (e.target instanceof Element && e.target.matches(":focus-visible")) show(e.target);
    },
    onBlur: hide,
    onScroll: hide,
  };

  const node: ReactNode = (
    <div
      aria-hidden="true"
      className="pointer-events-none fixed top-0 left-0 z-50"
      style={{
        transform: `translate3d(${tip?.x ?? 0}px, ${tip?.y ?? 0}px, 0)`,
        transition: slide ? `transform ${SLIDE_MS}ms ${SPRING}` : "none",
      }}
    >
      <div
        className="-translate-y-1/2 rounded-lg border border-border-strong bg-surface px-2.5 py-1.5 text-xs font-medium whitespace-nowrap text-ink shadow-pop"
        style={{
          clipPath: tip ? "inset(0 0 0 0 round 8px)" : "inset(0 100% 0 0 round 8px)",
          opacity: tip ? 1 : 0,
          transition: `clip-path ${REVEAL_MS}ms cubic-bezier(0.22, 1, 0.36, 1), opacity 120ms ease`,
        }}
      >
        {tip?.label}
      </div>
    </div>
  );

  return { bind, node };
}
