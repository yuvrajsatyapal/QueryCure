import { replayResultOf } from "./replay";
import type { ReportV1 } from "./types";

/* The report's table of contents (UI_UX §3.11): exactly the sections ReportView renders for this
 * report, in the same order. Keep the conditions here and in ReportView in step. */

export interface ReportSection {
  id: string;
  title: string;
}

const slug = (title: string) => `report-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "")}`;

export function reportSections(r: ReportV1): ReportSection[] {
  const rr = replayResultOf(r);
  if (rr) {
    const replayTitles = [
      "Query",
      ...(r.problem.evidence.length || r.problem.materiality ? ["Observed problem"] : []),
      ...(r.hypotheses.length ? ["Hypotheses"] : []),
      ...(r.rounds.length ? ["Replay measurement"] : []),
      "Experiment replay result",
      r.recommendation.origin === "source_run" ? "Original recommendation" : "Recommendation",
      ...(r.replay?.comparison ? ["Comparison with the original"] : []),
      "Limitations",
      "Next steps",
      ...(r.missing.length ? ["Missing evidence"] : []),
      "Provenance and integrity",
    ];
    return replayTitles.map((title) => ({ id: slug(title), title }));
  }
  const titles = [
    "Query",
    "Observed problem",
    "Hypotheses",
    ...(r.rounds.length ? ["Optimizations, approvals and benchmarks"] : []),
    "Recommendation",
    ...(r.replay?.comparison ? ["Experiment replay"] : []),
    "Limitations",
    "Next steps",
    ...(r.missing.length ? ["Missing evidence"] : []),
    "Provenance and integrity",
  ];
  return titles.map((title) => ({ id: slug(title), title }));
}

export const sectionId = slug;
