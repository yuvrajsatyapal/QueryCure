import type { ReportOut, RunSummary } from "@/lib/api/types";
import { runStatusMeta, type Tone } from "@/components/ui/StatusPill";
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

/** What the outcome labels need from a replay's sealed report (existing report endpoint, cached
 * forever: sealed reports never change). */
export interface ReplayReportMeta {
  builderVersion: string;
  /** The builder's replay title (schema 2), else null. */
  replayTitle: string | null;
  /** The builder's replay result (schema 2), else null; colour only. */
  replayResult: ReplayResultKind | null;
}

export function replayReportMeta(out: Pick<ReportOut, "builderVersion" | "reportSchemaVersion" | "report">): ReplayReportMeta {
  const report = out.report as unknown as Partial<ReportV1>;
  const result = out.reportSchemaVersion >= 2 ? (report.replayResult ?? null) : null;
  return { builderVersion: out.builderVersion, replayTitle: result?.title ?? null, replayResult: result?.result ?? null };
}

/** Where a replay's report stands for a label. `undefined` (not requested) reads like loading. */
export type ReplayReportState = { status: "loaded"; meta: ReplayReportMeta } | { status: "loading" } | { status: "error" };

export function replayReportState(q: { data?: Pick<ReportOut, "builderVersion" | "reportSchemaVersion" | "report">; isError: boolean }): ReplayReportState {
  if (q.data) return { status: "loaded", meta: replayReportMeta(q.data) };
  return q.isError ? { status: "error" } : { status: "loading" };
}

/** Sealed replays: the run selector reads their report to label them (§13.3–§13.4). */
export function sealedReplayRuns(runs: RunSummary[]): RunSummary[] {
  return runs.filter((r) => r.kind === "experiment_replay" && r.finalized);
}

/** What a run's outcome may say, decided once for every surface (REPLAY_OUTCOME_AUDIT §18.1).
 * Ordinary runs: the stored outcome once completed, else the status. Replays: never the bare
 * stored outcome. In flight, the status; failed or cancelled, that terminal status; completed,
 * the builder's sealed title (schema 2), the stored outcome as legacy context (report-builder@1),
 * or nothing while the report is unknown, unreadable or of a format this client does not know. */
export type RunOutcomeView =
  | { kind: "status"; status: string }
  | { kind: "outcome"; outcome: string }
  | { kind: "replay_result"; title: string; result: ReplayResultKind | null }
  | { kind: "legacy_replay"; outcome: string | null }
  | { kind: "replay_ended"; status: "failed" | "cancelled" }
  | { kind: "replay_pending" }
  | { kind: "replay_unavailable"; reason: "error" | "unknown_format"; builderVersion: string | null };

export function classifyRunOutcome(run: Pick<RunSummary, "kind" | "status" | "outcome">, report?: ReplayReportState): RunOutcomeView {
  if (run.kind !== "experiment_replay") {
    return run.status === "completed" && run.outcome ? { kind: "outcome", outcome: run.outcome } : { kind: "status", status: run.status };
  }
  if (run.status === "failed" || run.status === "cancelled") return { kind: "replay_ended", status: run.status };
  if (run.status !== "completed") return { kind: "status", status: run.status };
  if (report?.status === "loaded") {
    const { meta } = report;
    if (meta.replayTitle) return { kind: "replay_result", title: meta.replayTitle, result: meta.replayResult };
    if (meta.builderVersion === LEGACY_REPLAY_BUILDER) return { kind: "legacy_replay", outcome: run.outcome };
    return { kind: "replay_unavailable", reason: "unknown_format", builderVersion: meta.builderVersion };
  }
  if (report?.status === "error") return { kind: "replay_unavailable", reason: "error", builderVersion: null };
  return { kind: "replay_pending" };
}

const ORDINARY_TONE: Record<string, Tone> = {
  verified_recommendation: "success",
  unverified_recommendations: "neutral",
  no_action_needed: "neutral",
  inconclusive: "warning",
};
const RESULT_TONE: Record<(typeof REPLAY_TONE)[ReplayResultKind], Tone> = { verified: "success", inconclusive: "warning", rejected: "failed", muted: "neutral" };
const words = (s: string) => s.replaceAll("_", " ");
const sentence = (s: string) => words(s).charAt(0).toUpperCase() + words(s).slice(1);

/** A classified outcome as words and a tone for lists, pills and the header. `title` explains
 * the label (tooltip). Only a reproduced original uses the verified tone on a replay. */
export function runOutcomeText(view: RunOutcomeView): { label: string; tone: Tone; legacy: boolean; title?: string } {
  switch (view.kind) {
    case "status":
      return { ...runStatusMeta(view.status), legacy: false };
    case "outcome":
      return { label: OUTCOME_LABEL[view.outcome] ?? sentence(view.outcome), tone: ORDINARY_TONE[view.outcome] ?? "neutral", legacy: false };
    case "replay_result":
      return { label: view.title, tone: view.result ? RESULT_TONE[REPLAY_TONE[view.result]] : "neutral", legacy: false };
    case "legacy_replay":
      return {
        label: view.outcome ? `Legacy replay · ${words(view.outcome)}` : "Legacy replay",
        tone: "neutral",
        legacy: true,
        title: `${LEGACY_REPLAY_TITLE} ${LEGACY_REPLAY_NOTICE}`,
      };
    case "replay_ended":
      return view.status === "failed" ? { label: "Replay failed", tone: "failed", legacy: false } : { label: "Replay cancelled", tone: "neutral", legacy: false };
    case "replay_pending":
      return { label: "Replay completed", tone: "neutral", legacy: false, title: "The replay's result is in its sealed report." };
    case "replay_unavailable":
      return view.reason === "error"
        ? { label: "Replay completed · report unavailable", tone: "neutral", legacy: false, title: "The replay's report could not be loaded, so its result is not shown." }
        : {
            label: "Replay completed · see report",
            tone: "neutral",
            legacy: false,
            title: `This version of the app does not recognise the report format (${view.builderVersion ?? "unknown builder"}), so its result is not shown here.`,
          };
  }
}

/** A run's outcome text in the run selector: the shared classification in the selector's
 * lower-case wording. A replay whose report is not loaded yet shows no outcome. */
export function runOutcomeLabel(run: RunSummary, meta?: ReplayReportMeta | null): { outcome: string | null; legacy: boolean } {
  const view = classifyRunOutcome(run, meta ? { status: "loaded", meta } : undefined);
  switch (view.kind) {
    case "status":
      return { outcome: null, legacy: false };
    case "outcome":
      return { outcome: words(view.outcome), legacy: false };
    case "replay_result":
      return { outcome: view.title, legacy: false };
    case "legacy_replay":
      return { outcome: view.outcome ? words(view.outcome) : null, legacy: true };
    case "replay_ended":
      return { outcome: runOutcomeText(view).label, legacy: false };
    case "replay_pending":
      return { outcome: null, legacy: false };
    case "replay_unavailable":
      return { outcome: "replay result in report", legacy: false };
  }
}

export const YES_NO = (v: boolean | null) => (v === null ? "Not determined" : v ? "Yes" : "No");
