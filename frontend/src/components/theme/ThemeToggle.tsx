"use client";

import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";
import { Icon } from "@/components/ui/Icon";

const subscribe = () => () => {};

export function ThemeToggle({ className = "" }: { className?: string }) {
  const { resolvedTheme, setTheme } = useTheme();
  // The resolved theme is only known in the browser; render a stable control during SSR.
  const mounted = useSyncExternalStore(subscribe, () => true, () => false);
  const isDark = !mounted || resolvedTheme === "dark";
  return (
    <button
      type="button"
      onClick={() => setTheme(isDark ? "light" : "dark")}
      className={`qc-btn-ghost size-7 shrink-0 p-0 ${className}`}
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      title={isDark ? "Light theme" : "Dark theme"}
    >
      <Icon name={isDark ? "sun" : "moon"} size={15} />
    </button>
  );
}
