import { Icon, type IconName } from "./Icon";

/** The five meanings color is allowed to carry (DESIGN_SYSTEM §2), plus neutral. */
export type Tone = "running" | "success" | "failed" | "warning" | "approval" | "neutral";

export const TONE_TEXT: Record<Tone, string> = {
  running: "text-running",
  success: "text-verified",
  failed: "text-rejected",
  warning: "text-inconclusive",
  approval: "text-approval",
  neutral: "text-muted",
};

const TONE_PILL: Record<Tone, string> = {
  running: "border-running/30 bg-running/10 text-running",
  success: "border-verified/30 bg-verified/10 text-verified",
  failed: "border-rejected/30 bg-rejected/10 text-rejected",
  warning: "border-inconclusive/30 bg-inconclusive/10 text-inconclusive",
  approval: "border-approval/30 bg-approval/10 text-approval",
  neutral: "border-border bg-surface-2 text-muted",
};

export const TONE_ICON: Record<Tone, IconName> = {
  running: "loader",
  success: "checkCircle",
  failed: "xCircle",
  warning: "alert",
  approval: "hand",
  neutral: "circleDashed",
};

const RUN_STATUS: Record<string, { tone: Tone; label: string }> = {
  queued: { tone: "neutral", label: "Queued" },
  running: { tone: "running", label: "Running" },
  awaiting_approval: { tone: "approval", label: "Approval required" },
  cancelling: { tone: "warning", label: "Cancelling" },
  completed: { tone: "success", label: "Completed" },
  failed: { tone: "failed", label: "Failed" },
  cancelled: { tone: "neutral", label: "Cancelled" },
};

/** Run status → tone and words. A completed run whose outcome is not a finding still reads completed. */
export function runStatusMeta(status: string | null | undefined): { tone: Tone; label: string } {
  if (!status) return { tone: "neutral", label: "No run" };
  return RUN_STATUS[status] ?? { tone: "neutral", label: status.replaceAll("_", " ") };
}

/** The one status indicator that may move (DESIGN_SYSTEM §5, UI_UX §3.6b). Still by default:
 * a running orb drifts only when the caller has a confirmed live stream and the operation is
 * executing now, and every other tone is still whatever `live` says. A stored or polled status
 * alone is never enough. Reduced motion stops the drift (globals.css). */
export function StatusOrb({
  tone,
  live = false,
  size = 14,
  label,
  className,
}: {
  tone: Tone;
  live?: boolean;
  size?: number;
  /** Names the state for assistive tech; omit when visible text already says it. */
  label?: string;
  className?: string;
}) {
  // Below 12 px the dot texture has too little ink to read, so a small orb is a plain dot and
  // cannot show motion; live indicators use 12 px or more.
  const textured = tone === "running" && size >= 12;
  const moves = live && textured;
  // A small orb is the dot itself; a larger one keeps the dot at the same weight inside its box.
  const dot = textured || size <= 10 ? size : Math.round((size * 4) / 7);
  return (
    <span
      data-tone={tone}
      data-motion={moves ? "live" : "still"}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      className={`inline-flex shrink-0 items-center justify-center ${TONE_TEXT[tone]} ${className ?? ""}`}
      style={{ width: size, height: size }}
    >
      <span
        className={textured ? `qc-orb ${moves ? "qc-orb-live" : ""}` : "rounded-full bg-current"}
        style={{ width: dot, height: dot, ...(textured ? { ["--qc-orb-step" as string]: `${size / 4}px` } : {}) }}
      />
    </span>
  );
}

/** A tone as a glyph: running is the orb (still unless `live`), every other tone keeps its own
 * shape so color is never the only signal. */
export function StatusIcon({ tone, live = false, size = 14, className }: { tone: Tone; live?: boolean; size?: number; className?: string }) {
  if (tone === "running") return <StatusOrb tone={tone} live={live} size={size} className={className} />;
  return <Icon name={TONE_ICON[tone]} size={size} className={`${TONE_TEXT[tone]} ${className ?? ""}`} />;
}

export function StatusPill({ tone, label, live = false, className }: { tone: Tone; label: string; live?: boolean; className?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap ${TONE_PILL[tone]} ${className ?? ""}`}
    >
      <StatusIcon tone={tone} live={live} size={12} />
      {label}
    </span>
  );
}

/** The run's recorded status in words. Still: it names the status, it does not claim activity. */
export function RunStatusPill({ status }: { status: string | null | undefined }) {
  const meta = runStatusMeta(status);
  return <StatusPill tone={meta.tone} label={meta.label} />;
}
