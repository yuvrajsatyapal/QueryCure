"use client";

import { useEffect, useRef, useState, useSyncExternalStore, type RefObject } from "react";

const motionQuery = "(prefers-reduced-motion: reduce)";
const subscribeMotion = (cb: () => void) => {
  const mq = window.matchMedia(motionQuery);
  mq.addEventListener("change", cb);
  return () => mq.removeEventListener("change", cb);
};

/** True when the visitor asked for reduced motion. Server render assumes motion is allowed. */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribeMotion, () => window.matchMedia(motionQuery).matches, () => false);
}

/** Whether `ref` is on screen (at `threshold`) and the tab is visible. Drives pausing offscreen. */
export function useInView<T extends Element>(ref: RefObject<T | null>, threshold = 0): boolean {
  const [inView, setInView] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let intersecting = false;
    const fire = () => setInView(intersecting && !document.hidden);
    const io = new IntersectionObserver(
      (es) => {
        intersecting = es[0]?.isIntersecting ?? false;
        fire();
      },
      { threshold },
    );
    io.observe(el);
    document.addEventListener("visibilitychange", fire);
    return () => {
      io.disconnect();
      document.removeEventListener("visibilitychange", fire);
    };
  }, [ref, threshold]);
  return inView;
}

/** Adds `in` to an element the first time it scrolls into view (the `.reveal` entrance). */
export function useReveal<T extends HTMLElement>(): RefObject<T | null> {
  const ref = useRef<T>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (es) => {
        if (es[0]?.isIntersecting) {
          el.classList.add("in");
          io.disconnect();
        }
      },
      { threshold: 0.12 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return ref;
}
