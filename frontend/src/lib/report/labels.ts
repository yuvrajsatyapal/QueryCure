/** Words for verdicts, replay results and failure codes. Wording rules: REPLAY_ENGINE §6.3
 * ("Integrity check passed against stored digests", never "tamper-proof") and §9.2
 * (cross-environment comparisons are never called "reproduced"). */

export const OUTCOME_LABEL: Record<string, string> = {
  verified_recommendation: "Verified recommendation",
  unverified_recommendations: "Unverified recommendations",
  no_action_needed: "No action needed",
  inconclusive: "Inconclusive",
};

export const VERDICT_EXPLANATION: Record<string, string> = {
  verified:
    "Faster with the same result rows on every tested parameter set, in an isolated sandbox. Holds within the tested scope only.",
  verified_with_noise_warning:
    "Single experiments were too noisy to decide. Three independent experiments agreed, so the speed-up is verified with a noise warning: treat its size as uncertain.",
  rejected: "The deterministic rules rejected the candidate (for example a regression or different result rows).",
  inconclusive:
    "Not enough evidence either way (noise, too few samples, an effect smaller than required, or an auditor downgrade). Inconclusive is not a rejection.",
};

export const REASON_TEXT: Record<string, string> = {
  insufficient_evidence: "too few samples, or measurements too noisy to decide",
  effect_not_significant: "the speed-up is smaller than the required effect",
  unstable_execution: "too many executions timed out or failed",
  nondeterministic_order: "the query's own results varied between executions",
  result_too_large: "the result was too large to compare completely",
  replicates_disagree: "independent re-measurements did not agree",
  regression: "at least one parameter set got slower",
  result_mismatch: "different result rows than the original query",
  no_improvement: "not faster",
  ddl_failed: "the change could not be applied in the sandbox",
  constraint_violation: "the change exceeded size or build-time limits",
  audit_downgrade: "the Benchmark Auditor found a reason to doubt the result",
  approval_declined: "a human declined the change",
  approval_expired: "the approval request expired",
  experiment_failed: "the sandbox experiment failed",
};

export const REPORT_REPLAY_STATUS: Record<string, string> = {
  verified: "Integrity check passed against stored digests",
  verified_stored_only: "Integrity check passed against stored digests (rebuild skipped: retired version)",
  not_replayable: "Not replayable",
  integrity_failed: "Integrity check failed",
  error: "Verification error",
};

export const REPLAY_CODE_TEXT: Record<string, string> = {
  not_finalized: "The run was never finalized (runs from before Phase 4 are never sealed).",
  manifest_missing: "The replay manifest is missing.",
  artifact_purged: "A stored artifact was purged.",
  events_purged: "The sealed event log was purged.",
  unsupported_profile: "An artifact uses an unknown canonicalization profile.",
  unsupported_manifest_schema: "The manifest uses an unknown schema version.",
  manifest_digest_mismatch: "The manifest no longer matches its stored digest.",
  artifact_digest_mismatch: "A stored artifact no longer matches its digest.",
  events_gap: "The sealed event log has a gap.",
  events_digest_mismatch: "The sealed events no longer match their digest.",
  rebuild_mismatch: "Rebuilding the report from the records gives different bytes.",
  internal_error: "Unexpected error; try again.",
  source_not_finalized: "The source run was never finalized.",
  source_integrity_failed: "The source run fails its integrity check.",
  source_experiment_incomplete: "The source experiment did not complete.",
  config_artifact_missing: "The experiment configuration is missing.",
  unsupported_config_schema: "The configuration (or its SQL) is no longer supported.",
  workload_unavailable: "The demo workload is no longer available.",
  workload_snapshot_changed: "The demo data changed since the original run.",
  sandbox_disabled: "This deployment has no live sandbox.",
  unsupported_row_profile: "The result-row profile is not supported.",
  sandbox_unavailable: "The sandbox was unavailable.",
  timeout: "The replay timed out.",
  budget_exhausted: "The replay ran out of budget.",
  cancelled_by_user: "Cancelled.",
  insufficient_evidence: "Too few samples or too much noise on one side to compare.",
  drift_undetermined: "The speed-up drift interval straddles the equivalence margin.",
  verdict_inconclusive: "One side's verdict is inconclusive.",
  verdict_changed: "The verdict changed.",
  direction_reversed: "The improvement direction reversed.",
  result_fingerprint_changed: "The query returned different rows (data or generator not deterministic).",
  winner_changed: "A different candidate won.",
};

const SAME_ENV: Record<string, string> = {
  reproduced: "Reproduced",
  reproduced_with_drift: "Reproduced, effect size drifted",
  not_reproduced: "Not reproduced",
  inconclusive: "Inconclusive",
};
const CROSS_ENV: Record<string, string> = {
  reproduced: "Consistent across environments",
  reproduced_with_drift: "Same conclusion, effect size differs across environments",
  not_reproduced: "Conclusion differs across environments",
  inconclusive: "Inconclusive",
};
const LIFECYCLE: Record<string, string> = {
  checking: "Checking",
  queued: "Queued",
  running: "Measuring",
  comparing: "Comparing",
  not_replayable: "Not replayable",
  failed: "Failed",
  cancelled: "Cancelled",
};

/** The stored status worded by comparison mode (REPLAY_ENGINE §9.2). */
export function experimentReplayLabel(status: string, mode: string | null | undefined): string {
  const lifecycle = LIFECYCLE[status];
  if (lifecycle) return lifecycle;
  const table = mode === "cross_environment" ? CROSS_ENV : SAME_ENV;
  return table[status] ?? status;
}

export const ACTIVE_REPLAY = new Set(["checking", "queued", "running", "comparing"]);

export const x = (v: number | null | undefined) =>
  v === null || v === undefined ? "n/a" : `${v >= 10 ? v.toFixed(1) : v.toFixed(2)}×`;
export const ms = (ns: number | null | undefined) =>
  ns === null || ns === undefined ? "n/a" : `${(ns / 1e6).toFixed(ns / 1e6 >= 10 ? 1 : 3)} ms`;
