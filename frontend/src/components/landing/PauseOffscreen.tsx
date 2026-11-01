"use client";

import { useEffect } from "react";

/** Marks landing sections `data-off` while they are off screen; landing.css pauses their looping animations. */
export function PauseOffscreen() {
  useEffect(() => {
    const io = new IntersectionObserver((es) => es.forEach((e) => e.target.toggleAttribute("data-off", !e.isIntersecting)));
    document.querySelectorAll(".lp main > section, .lp > footer").forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);
  return null;
}
