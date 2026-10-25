import { statusLabel } from "@/lib/benchmark/status";

const STYLE: Record<string, { icon: string; label: string; className: string }> = {
  verified: { icon: "✓", label: statusLabel("verified"), className: "border-verified/40 bg-verified/10 text-verified" },
  // ADR-0019: noisy samples, verified only by agreement of independent experiments.
  verified_with_noise_warning: {
    icon: "✓",
    label: statusLabel("verified_with_noise_warning"),
    className: "border-dashed border-verified/60 bg-verified/10 text-verified",
  },
  rejected: { icon: "✕", label: statusLabel("rejected"), className: "border-rejected/40 bg-rejected/10 text-rejected" },
  inconclusive: { icon: "?", label: statusLabel("inconclusive"), className: "border-inconclusive/40 bg-inconclusive/10 text-inconclusive" },
  // The Benchmark Auditor downgraded the engine verdict (downgrade-only, ADR-0009).
  disputed: { icon: "!", label: statusLabel("disputed"), className: "border-dashed border-inconclusive/60 bg-inconclusive/10 text-inconclusive" },
  unverified: { icon: "–", label: statusLabel("unverified"), className: "border-dashed border-border-strong text-muted" },
  proposed: { icon: "○", label: statusLabel("proposed"), className: "border-dashed border-approval/60 bg-approval/10 text-approval" },
  approved: { icon: "○", label: statusLabel("approved"), className: "border-dashed border-hypothesis text-hypothesis" },
  benchmarked: { icon: "◐", label: statusLabel("benchmarked"), className: "border-dashed border-running/60 bg-running/10 text-running" },
  declined: { icon: "–", label: statusLabel("declined"), className: "border-border-strong text-muted" },
  expired: { icon: "–", label: statusLabel("expired"), className: "border-border-strong text-muted" },
};

/** Verdict or candidate status, always in words (DESIGN_SYSTEM: never colour alone). */
export function VerdictBadge({ status }: { status: string }) {
  const s = STYLE[status] ?? { icon: "·", label: statusLabel(status), className: "border-border-strong text-muted" };
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium whitespace-nowrap ${s.className}`}>
      <span aria-hidden="true">{s.icon}</span>
      {s.label}
    </span>
  );
}
