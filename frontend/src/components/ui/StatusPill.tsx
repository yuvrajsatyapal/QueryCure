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

export function StatusIcon({ tone, size = 14, className }: { tone: Tone; size?: number; className?: string }) {
  return (
    <Icon
      name={TONE_ICON[tone]}
      size={size}
      className={`${TONE_TEXT[tone]} ${tone === "running" ? "animate-spin [animation-duration:1.4s]" : ""} ${className ?? ""}`}
    />
  );
}

export function StatusPill({ tone, label, className }: { tone: Tone; label: string; className?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap ${TONE_PILL[tone]} ${className ?? ""}`}
    >
      <StatusIcon tone={tone} size={12} />
      {label}
    </span>
  );
}

export function RunStatusPill({ status }: { status: string | null | undefined }) {
  const meta = runStatusMeta(status);
  return <StatusPill tone={meta.tone} label={meta.label} />;
}
