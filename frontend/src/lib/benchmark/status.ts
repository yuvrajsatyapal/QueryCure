// Candidate statuses and verdicts in words (DESIGN_SYSTEM: never colour alone). Shared by the
// verdict badge and the command palette so both say the same thing.
const STATUS_LABEL: Record<string, string> = {
  verified: "Verified · tested scope",
  rejected: "Rejected",
  inconclusive: "Inconclusive",
  disputed: "Disputed · auditor downgrade",
  unverified: "Unverified · not measured",
  proposed: "Proposed · awaiting approval",
  approved: "Approved · not yet measured",
  benchmarked: "Benchmarking",
  declined: "Declined · not run",
  expired: "Approval expired · not run",
  verified_with_noise_warning: "Verified · noise warning, 3 runs agree",
};

export function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status;
}
