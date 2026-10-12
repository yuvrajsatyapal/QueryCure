import type { Hypothesis } from "@/lib/api/types";

const CONFIDENCE_ICON: Record<Hypothesis["confidence"], string> = { high: "●●●", medium: "●●○", low: "●○○" };

/** Dashed border = hypothesis (DESIGN_SYSTEM §5). Nothing is verified before Phase 3, so every
 * claim says so in words, never by colour alone. */
export function ClaimBadge({ confidence }: { confidence: Hypothesis["confidence"] }) {
  return (
    <span className="inline-flex items-center gap-1 rounded border border-dashed border-hypothesis px-1.5 py-0.5 font-mono text-[11px] text-hypothesis">
      <span aria-hidden="true">{CONFIDENCE_ICON[confidence]}</span>
      Hypothesis · {confidence} · unverified
    </span>
  );
}
