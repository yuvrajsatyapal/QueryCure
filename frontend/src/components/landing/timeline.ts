"use client";

import { useEffect, useState } from "react";
import { mulberry32 } from "@/lib/landing/bench";

/* Small scripted timelines. Callers remount (via `key`) to restart one, so state starts fresh and
 * effects only schedule timers. Reduced motion starts at the end state and schedules nothing. */

/** Number of `times` (ms after mount) that have passed. */
export function useSteps(times: readonly number[], reduced: boolean): number {
  const [n, setN] = useState(reduced ? times.length : 0);
  useEffect(() => {
    if (reduced) return;
    const ids = times.map((t, k) => window.setTimeout(() => setN((c) => Math.max(c, k + 1)), t));
    return () => ids.forEach(clearTimeout);
  }, [times, reduced]);
  return n;
}

/** Types `text` two characters at a time from `start` ms; returns the visible prefix and whether it finished. */
export function useTyped(text: string, start: number, reduced: boolean): [string, boolean] {
  const [k, setK] = useState(reduced ? text.length : 0);
  useEffect(() => {
    if (reduced) return;
    let id = 0;
    let c = 0;
    const tick = () => {
      c = Math.min(text.length, c + 2);
      setK(c);
      if (c < text.length) id = window.setTimeout(tick, 22);
    };
    id = window.setTimeout(tick, start);
    return () => clearTimeout(id);
  }, [text, start, reduced]);
  return [text.slice(0, k), k >= text.length];
}

/** Streams `text` one word every 65 ms from `start`; returns the visible words and whether it finished. */
export function useStream(text: string, start: number, reduced: boolean): [string, boolean] {
  const total = text.split(" ").length;
  const [k, setK] = useState(reduced ? total : 0);
  useEffect(() => {
    if (reduced) return;
    const n = text.split(" ").length;
    let id = 0;
    let c = 0;
    const tick = () => {
      c += 1;
      setK(c);
      if (c < n) id = window.setTimeout(tick, 65);
    };
    id = window.setTimeout(tick, start);
    return () => clearTimeout(id);
  }, [text, start, reduced]);
  return [text.split(" ").slice(0, k).join(" "), k >= total];
}

/** Shows random hex while "computing", then settles on `final`. Display-only; the digest itself is fixed. */
export function useRoll(prefix: string, final: string, start: number, duration: number, reduced: boolean): [string, boolean] {
  const [text, setText] = useState(reduced ? prefix + final : `${prefix}········`);
  const [done, setDone] = useState(reduced);
  useEffect(() => {
    if (reduced) return;
    const rng = mulberry32(9);
    const hex = (n: number) => Array.from({ length: n }, () => "0123456789abcdef"[Math.floor(rng() * 16)]).join("");
    let iv = 0;
    const t0 = window.setTimeout(() => {
      const began = performance.now();
      iv = window.setInterval(() => {
        if (performance.now() - began >= duration) {
          clearInterval(iv);
          setText(prefix + final);
          setDone(true);
          return;
        }
        setText(`${prefix}${hex(4)}…${hex(4)}`);
      }, 45);
    }, start);
    return () => {
      clearTimeout(t0);
      clearInterval(iv);
    };
  }, [prefix, final, start, duration, reduced]);
  return [text, done];
}

/** Counts up to `to` over `duration` ms (ease-out) from `start`. */
export function useCountUp(to: number, start: number, duration: number, reduced: boolean): number {
  const [v, setV] = useState(reduced ? to : 0);
  useEffect(() => {
    if (reduced) return;
    let raf = 0;
    const t = window.setTimeout(() => {
      const t0 = performance.now();
      const step = (now: number) => {
        const u = Math.min(1, (now - t0) / duration);
        setV(Math.round(to * (1 - Math.pow(1 - u, 3))));
        if (u < 1) raf = requestAnimationFrame(step);
      };
      raf = requestAnimationFrame(step);
    }, start);
    return () => {
      clearTimeout(t);
      cancelAnimationFrame(raf);
    };
  }, [to, start, duration, reduced]);
  return v;
}
