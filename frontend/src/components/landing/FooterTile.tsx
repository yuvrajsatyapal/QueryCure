"use client";

import { useEffect, useRef } from "react";
import { Logo } from "@/components/ui/Logo";

const REST = { ry: -9, rx: 5 };
const MAX_OFFSET = 2;

/** Footer brand tile that tilts toward the pointer. The resting tilt is plain CSS, so it still renders without
 * JS and for people who ask for reduced motion (the effect is skipped entirely for them). */
export function FooterTile() {
  const tile = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const el = tile.current;
    const host = el?.closest<HTMLElement>(".ft-mega");
    if (!el || !host || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    let raf = 0;
    let ry = REST.ry;
    let rx = REST.rx;
    const apply = () => {
      raf = 0;
      el.style.setProperty("--ry", `${ry.toFixed(2)}deg`);
      el.style.setProperty("--rx", `${rx.toFixed(2)}deg`);
    };
    const schedule = () => {
      if (!raf) raf = requestAnimationFrame(apply);
    };
    const move = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      const px = (e.clientX - (r.left + r.width / 2)) / (r.width / 2);
      const py = (e.clientY - (r.top + r.height / 2)) / (r.height / 2);
      ry = Math.max(-MAX_OFFSET, Math.min(MAX_OFFSET, px)) * 16;
      rx = -Math.max(-MAX_OFFSET, Math.min(MAX_OFFSET, py)) * 14;
      schedule();
    };
    const leave = () => {
      ry = REST.ry;
      rx = REST.rx;
      schedule();
    };
    host.addEventListener("pointermove", move);
    host.addEventListener("pointerleave", leave);
    return () => {
      host.removeEventListener("pointermove", move);
      host.removeEventListener("pointerleave", leave);
      if (raf) cancelAnimationFrame(raf);
    };
  }, []);

  return (
    <span className="ft-tile">
      <span className="ft-tilt" ref={tile}>
        <Logo size={48} className="ft-q" />
      </span>
    </span>
  );
}
