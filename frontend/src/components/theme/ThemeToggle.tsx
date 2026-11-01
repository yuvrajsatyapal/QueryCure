"use client";

import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";

const subscribe = () => () => {};

const ICON_MORPH_MS = 600;

/** Sun and moon share one disc: the moon is the disc with a circular bite masked out, and the rays
 * scale away. */
function ThemeIcon({ isDark }: { isDark: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="60%" height="60%" fill="currentColor" aria-hidden="true">
      <mask id="qc-theme-moon-mask">
        <rect x="0" y="0" width="24" height="24" fill="#fff" />
        <circle
          cx={isDark ? 16 : 30}
          cy={isDark ? 7 : 0}
          r="6"
          fill="#000"
          style={{ transition: `cx ${ICON_MORPH_MS / 2}ms ease, cy ${ICON_MORPH_MS / 2}ms ease` }}
        />
      </mask>
      {/* Moon: dark theme shows the bite, light theme pushes it off the disc to leave a sun. */}
      <circle
        cx="12"
        cy="12"
        r={isDark ? 9 : 5}
        mask="url(#qc-theme-moon-mask)"
        style={{ transition: `r ${ICON_MORPH_MS / 2}ms ease` }}
      />
      <g
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        style={{
          transformOrigin: "12px 12px",
          transform: isDark ? "rotate(-45deg) scale(0.4)" : "rotate(0deg) scale(1)",
          opacity: isDark ? 0 : 1,
          transition: `transform ${ICON_MORPH_MS / 2}ms ease, opacity ${ICON_MORPH_MS / 3}ms ease`,
        }}
      >
        <path d="M12 1.5v3M12 19.5v3M1.5 12h3M19.5 12h3M4.6 4.6l2.1 2.1M17.3 17.3l2.1 2.1M4.6 19.4l2.1-2.1M17.3 6.7l2.1-2.1" />
      </g>
    </svg>
  );
}

export function ThemeToggle({ className = "" }: { className?: string }) {
  const { resolvedTheme, setTheme } = useTheme();
  // The resolved theme is only known in the browser; render a stable control during SSR.
  const mounted = useSyncExternalStore(subscribe, () => true, () => false);
  const isDark = !mounted || resolvedTheme === "dark";
  const next = isDark ? "light" : "dark";

  return (
    <button
      type="button"
      // No full-page view transition: snapshotting and clip-path-animating the whole viewport
      // over the landing page's animated DOM made the app stutter.
      onClick={() => setTheme(next)}
      className={`inline-flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-full border border-[var(--border)] bg-[var(--surface)] text-[var(--ink)] transition duration-150 hover:border-[var(--border-strong)] hover:scale-105 active:scale-95 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ink)] ${className}`}
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      title={isDark ? "Light theme" : "Dark theme"}
    >
      <ThemeIcon isDark={isDark} />
    </button>
  );
}
