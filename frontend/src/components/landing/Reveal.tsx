"use client";

import type { HTMLAttributes } from "react";
import { useReveal } from "./hooks";

/** A block that fades up the first time it scrolls into view (`.reveal` → `.reveal.in`). */
export function Reveal({ className = "", ...rest }: HTMLAttributes<HTMLDivElement>) {
  const ref = useReveal<HTMLDivElement>();
  const cls = className.includes("bridge") ? className : `reveal ${className}`.trim();
  return <div ref={ref} className={cls} {...rest} />;
}
