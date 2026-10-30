import type { ReportOut, RunSummary } from "@/lib/api/types";
import { OUTCOME_LABEL } from "./labels";
import type { ReplayResult, ReplayResultKind, ReportV1 } from "./types";

/* Experiment-replay presentation (REPLAY_OUTCOME_AUDIT §13.3–§13.4). Schema-2 reports carry the
 * builder's sealed replay result and title; the page renders them and classifies nothing.
 * Historical report-builder@1 replays are shown as stored, with a notice beside them. */

export const LEGACY_REPLAY_BUILDER = "report-builder@1";

/** One notice for historical replays, shown outside the sealed report in the report view, the
 * result summary and the run selector (the selector as the tag's tooltip). */
export const LEGACY_REPLAY_TITLE = "Earlier replay classification.";
export const LEGACY_REPLAY_NOTICE =
  "This report used an older outcome rule based on the replay's measurement, not its comparison with the original investigation. It does not independently verify a recommendation.";

/** Colour only, keyed by the builder's result. */
export const REPLAY_TONE: Record<ReplayResultKind, "verified" | "inconclusive" | "rejected" | "muted"> = {
  original_reproduced: "verified",
  performance_drift: "inconclusive",
  not_reproduced: "rejected",
  inconclusive: "inconclusive",
  not_comparable: "inconclusive",
  not_confirmed: "inconclusive",
  unavailable: "inconclusive",
  failed: "rejected",
  cancelled: "muted",
  unclassified: "inconclusive",
};

export function replayResultOf(r: Pick<ReportV1, "schemaVersion" | "replayResult">): ReplayResult | null {
  return r.schemaVersion >= 2 && r.replayResult ? r.replayResult : null;
}

export function isLegacyReplayReport(r: Pick<ReportV1, "builderVersion" | "run">): boolean {
  return r.builderVersion === LEGACY_REPLAY_BUILDER && r.run.kind === "experiment_replay";
}

/** The headline without the title it repeats ("Title: rest" / "Title. Rest"), for pages that
 * show the title as the heading. The Markdown does the same (report-md@2). */
export function headlineBody(r: ReportV1): string {
  const title = replayResultOf(r)?.title;
  const h = r.headline;
  if (!title || !h.startsWith(title) || !/^[.:]\s/.test(h.slice(title.length))) return h;
  const rest = h.slice(title.length + 2);
  return rest.charAt(0).toUpperCase() + rest.slice(1);
}

export function reportTitle(r: ReportV1): string {
  return replayResultOf(r)?.title ?? OUTCOME_LABEL[r.outcome ?? ""] ?? `Run ${r.finalStatus}`;
}

/** What the run selector needs from a replay's sealed report (existing report endpoint, cached
 * forever: sealed reports never change). */
export interface ReplayReportMeta {
  builderVersion: string;
  /** The builder's replay title (schema 2), else null. */
  replayTitle: string | null;
}

export function replayReportMeta(out: Pick<ReportOut, "builderVersion" | "reportSchemaVersion" | "report">): ReplayReportMeta {
  const report = out.report as unknown as Partial<ReportV1>;
  const title = out.reportSchemaVersion >= 2 ? (report.replayResult?.title ?? null) : null;
  return { builderVersion: out.builderVersion, replayTitle: title };
}

/** Sealed replays: the run selector reads their report to label them (§13.3–§13.4). */
export function sealedReplayRuns(runs: RunSummary[]): RunSummary[] {
  return runs.filter((r) => r.kind === "experiment_replay" && r.finalized);
}

/** A run's outcome text in the run selector. Ordinary runs: the stored outcome, unchanged. A
 * schema-2 replay: the builder's sealed title (e.g. "Original recommendation reproduced"), never
 * the bare stored outcome. A historical report-builder@1 replay: its stored outcome, tagged
 * legacy. A sealed replay whose report is not loaded yet shows no outcome rather than a stored
 * "verified recommendation" that its report may qualify. */
export function runOutcomeLabel(run: RunSummary, meta?: ReplayReportMeta | null): { outcome: string | null; legacy: boolean } {
  const stored = run.outcome ? run.outcome.replaceAll("_", " ") : null;
  if (run.kind !== "experiment_replay") return { outcome: stored, legacy: false };
  if (meta?.replayTitle) return { outcome: meta.replayTitle, legacy: false };
  if (meta?.builderVersion === LEGACY_REPLAY_BUILDER) return { outcome: stored, legacy: true };
  if (run.status === "failed") return { outcome: "Replay failed", legacy: false };
  if (run.finalized && run.outcome === "verified_recommendation") return { outcome: null, legacy: false };
  return { outcome: stored, legacy: false };
}

export const YES_NO = (v: boolean | null) => (v === null ? "Not determined" : v ? "Yes" : "No");
