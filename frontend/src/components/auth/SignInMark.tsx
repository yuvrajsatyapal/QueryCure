"use client";

import { useState } from "react";

/** The QueryCure mark at sign-in size with its intro animation (CSS in globals.css). Clicking replays it;
 * the key change remounts the SVG, which restarts every CSS animation. Decorative: the heading names the page. */
export function SignInMark({ size = 56 }: { size?: number }) {
  const [run, setRun] = useState(0);
  return (
    <svg
      key={run}
      width={size}
      height={size}
      viewBox="0 0 32 32"
      aria-hidden="true"
      focusable="false"
      onClick={() => setRun((n) => n + 1)}
      className="qc-signin-mark overflow-visible text-ink"
    >
      <g fill="none" stroke="currentColor" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round">
        <path className="qc-ring" pathLength={1} d="M22.43 12.25A9.5 9.5 0 1 1 17.52 6.89" />
        <path className="qc-tail" pathLength={1} d="M17.1 19.1L21.4 23.4H23.2" />
      </g>
      <circle className="qc-ripple" cx={25.7} cy={23.4} r={2.6} />
      <circle className="qc-dot" cx={25.7} cy={23.4} r={2.6} fill="var(--accent)" />
    </svg>
  );
}
