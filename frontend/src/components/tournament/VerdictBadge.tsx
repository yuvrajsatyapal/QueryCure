const STYLE: Record<string, { icon: string; label: string; className: string }> = {
  verified: { icon: "✓", label: "Verified · tested scope", className: "border-verified text-verified" },
  // ADR-0019: noisy samples, verified only by agreement of independent experiments.
  verified_with_noise_warning: {
    icon: "✓",
    label: "Verified · noise warning, 3 runs agree",
    className: "border-dashed border-verified text-verified",
  },
  rejected: { icon: "✕", label: "Rejected", className: "border-rejected text-rejected" },
  inconclusive: { icon: "?", label: "Inconclusive", className: "border-inconclusive text-inconclusive" },
  proposed: { icon: "○", label: "Proposed · awaiting approval", className: "border-dashed border-hypothesis text-hypothesis" },
  approved: { icon: "○", label: "Approved · not yet measured", className: "border-dashed border-hypothesis text-hypothesis" },
  benchmarked: { icon: "◐", label: "Benchmarking", className: "border-dashed border-hypothesis text-hypothesis" },
  declined: { icon: "–", label: "Declined · not run", className: "border-border-strong text-muted" },
  expired: { icon: "–", label: "Approval expired · not run", className: "border-border-strong text-muted" },
};

/** Verdict or candidate status, always in words (DESIGN_SYSTEM: never colour alone). */
export function VerdictBadge({ status }: { status: string }) {
  const s = STYLE[status] ?? { icon: "·", label: status, className: "border-border-strong text-muted" };
  return (
    <span className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-[11px] ${s.className}`}>
      <span aria-hidden="true">{s.icon}</span>
      {s.label}
    </span>
  );
}
