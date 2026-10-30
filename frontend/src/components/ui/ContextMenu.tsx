"use client";

import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { Icon, type IconName } from "./Icon";

export interface MenuItem {
  id: string;
  label: string;
  icon?: IconName;
  disabled?: boolean;
  onSelect: () => void;
}

const MARGIN = 8;
const GAP = 4;

/** A WAI-ARIA menu at a point (right-click, Shift+F10, the context-menu key, or a long press).
 * Arrow keys move, Enter/Space choose, Esc and Tab close; focus returns to the opener.
 *
 * With `anchor` it is a menu button's popup instead: it opens upward from `at` (the anchor's
 * top-left), and a press on the anchor is left to the anchor's own toggle. Fixed positioning keeps
 * it from being clipped by a scrolling ancestor such as the sidebar. */
export function ContextMenu({
  label,
  at,
  items,
  onClose,
  anchor,
}: {
  label: string;
  at: { x: number; y: number };
  items: MenuItem[];
  onClose: () => void;
  anchor?: HTMLElement | null;
}) {
  const ref = useRef<HTMLDivElement>(null);
  // The opener, read before the menu takes focus, so focus can go back to it.
  const [opener] = useState(() => (typeof document !== "undefined" && document.activeElement instanceof HTMLElement ? document.activeElement : null));
  const [pos, setPos] = useState(at);
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  }, [onClose]);

  // Keep the menu inside the viewport, then focus the first enabled item.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const { width, height } = el.getBoundingClientRect();
    const y = anchor ? at.y - height - GAP : at.y;
    setPos({
      x: Math.max(MARGIN, Math.min(at.x, window.innerWidth - width - MARGIN)),
      y: Math.max(MARGIN, Math.min(y, window.innerHeight - height - MARGIN)),
    });
    // No scroll: inside the sidebar, focusing a fixed child would scroll its container.
    el.querySelector<HTMLElement>('[role="menuitem"]:not([aria-disabled="true"])')?.focus({ preventScroll: true });
  }, [at, anchor]);

  useEffect(() => {
    const outside = (e: PointerEvent) => {
      const target = e.target as Node;
      if (!ref.current?.contains(target) && !anchor?.contains(target)) close.current();
    };
    const away = () => close.current();
    // An anchored menu would drift off its button if the sidebar (or page) scrolled it away.
    const scrolled = () => {
      const r = anchor?.getBoundingClientRect();
      if (r && (Math.abs(r.left - at.x) > 1 || Math.abs(r.top - at.y) > 1)) close.current();
    };
    document.addEventListener("pointerdown", outside, true);
    window.addEventListener("resize", away);
    if (anchor) document.addEventListener("scroll", scrolled, true);
    return () => {
      document.removeEventListener("pointerdown", outside, true);
      window.removeEventListener("resize", away);
      document.removeEventListener("scroll", scrolled, true);
      if (opener?.isConnected) opener.focus();
    };
  }, [opener, anchor, at]);

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const all = Array.from(ref.current?.querySelectorAll<HTMLElement>('[role="menuitem"]:not([aria-disabled="true"])') ?? []);
    const i = all.indexOf(document.activeElement as HTMLElement);
    const move = (to: number) => all[(to + all.length) % all.length]?.focus();
    if (e.key === "ArrowDown") move(i + 1);
    else if (e.key === "ArrowUp") move(i - 1);
    else if (e.key === "Home") move(0);
    else if (e.key === "End") move(all.length - 1);
    else if (e.key === "Escape" || e.key === "Tab") close.current();
    else return;
    e.preventDefault();
    e.stopPropagation();
  }

  return (
    <div
      ref={ref}
      role="menu"
      aria-label={label}
      onKeyDown={onKeyDown}
      style={{ left: pos.x, top: pos.y }}
      className="fixed z-50 flex min-w-52 flex-col rounded-lg border border-border bg-surface py-1 text-sm shadow-pop"
    >
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          role="menuitem"
          tabIndex={-1}
          aria-disabled={item.disabled || undefined}
          onClick={() => {
            if (item.disabled) return;
            close.current();
            item.onSelect();
          }}
          className="mx-1 flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-ink outline-none hover:bg-hover focus:bg-hover aria-disabled:cursor-default aria-disabled:text-faint aria-disabled:hover:bg-transparent pointer-coarse:py-2.5"
        >
          {item.icon ? <Icon name={item.icon} size={14} className="text-muted" /> : <span className="w-3.5" aria-hidden="true" />}
          {item.label}
        </button>
      ))}
    </div>
  );
}
