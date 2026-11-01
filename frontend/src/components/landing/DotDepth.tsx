"use client";

import { useEffect, useRef, type CSSProperties } from "react";
import { DOT_DEPTH, farLayerOffset } from "@/lib/landing/dotDepth";

/** Fainter, wider dot grid behind the page that trails the scroll at a fraction of its speed, so the
 * foreground grid reads as nearer. One passive scroll listener, coalesced to one write per frame. */
export function DotDepth() {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    let frame = 0;

    const apply = () => {
      frame = 0;
      el.style.transform = `translate3d(0, ${farLayerOffset(window.scrollY, window.devicePixelRatio || 1)}px, 0)`;
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(apply);
    };
    const sync = () => {
      window.removeEventListener("scroll", onScroll);
      if (reduced.matches) {
        el.style.transform = "";
        return;
      }
      window.addEventListener("scroll", onScroll, { passive: true });
      apply();
    };

    sync();
    reduced.addEventListener("change", sync);
    return () => {
      reduced.removeEventListener("change", sync);
      window.removeEventListener("scroll", onScroll);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);

  if (DOT_DEPTH.intensity <= 0) return null;
  const style = { "--dd-tile": `${DOT_DEPTH.tile}px`, "--dd-intensity": DOT_DEPTH.intensity } as CSSProperties;
  return <div ref={ref} className="dot-depth" style={style} aria-hidden="true" />;
}
