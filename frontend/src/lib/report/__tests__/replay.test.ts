import { expect, test } from "vitest";
import fixtures from "@/test/fixtures/report-v2.json";
import type { RunSummary } from "@/lib/api/types";
import type { ReportV1 } from "../types";
import { REPLAY_TONE, headlineBody, isLegacyReplayReport, replayReportMeta, replayResultOf, reportTitle, runOutcomeLabel, sealedReplayRuns } from "../replay";
import { reportSections } from "../sections";

type Name = Exclude<keyof typeof fixtures, "_note">;
const v2 = (name: Name) => fixtures[name] as unknown as ReportV1;
const names = Object.keys(fixtures).filter((n) => n !== "_note") as Name[];

test("schema-2 replay reports expose the builder's replay result; others have none", () => {
  expect(replayResultOf(v2("1_reproduced_original"))?.result).toBe("original_reproduced");
  expect(replayResultOf(v2("legacy_v1_replay"))).toBeNull();
  const base = v2("1_reproduced_original");
  expect(replayResultOf({ ...base, replayResult: undefined })).toBeNull();
});

test("titles come from the report: the builder's replay title, else the stored outcome label", () => {
  expect(reportTitle(v2("1_reproduced_original"))).toBe("Original recommendation reproduced");
  expect(reportTitle(v2("2_performance_drift"))).toBe("Performance drift detected");
  expect(reportTitle(v2("3_not_reproduced_rows"))).toBe("Original result not reproduced");
  expect(reportTitle(v2("5_cross_environment"))).toBe("Results not directly comparable");
  expect(reportTitle(v2("15_execution_failed"))).toBe("Replay failed");
  // a historical v1 replay keeps its stored outcome label (never rewritten)
  expect(reportTitle(v2("legacy_v1_replay"))).toBe("Verified recommendation");
  for (const name of names.filter((n) => n !== "legacy_v1_replay")) {
    expect(reportTitle(v2(name))).not.toBe("Verified recommendation");
  }
});

test("only the reproduced result uses the verified tone; contradictions use the rejected tone", () => {
  expect(REPLAY_TONE.original_reproduced).toBe("verified");
  expect(REPLAY_TONE.not_reproduced).toBe("rejected");
  expect(REPLAY_TONE.failed).toBe("rejected");
  for (const kind of ["performance_drift", "inconclusive", "not_comparable", "not_confirmed", "unavailable", "unclassified"] as const) {
    expect(REPLAY_TONE[kind]).toBe("inconclusive");
  }
});

test("legacy notice selector: report-builder@1 and an experiment replay, nothing else", () => {
  expect(isLegacyReplayReport(v2("legacy_v1_replay"))).toBe(true);
  expect(isLegacyReplayReport(v2("1_reproduced_original"))).toBe(false);
  const legacy = v2("legacy_v1_replay");
  expect(isLegacyReplayReport({ ...legacy, run: { ...legacy.run, kind: "initial" } })).toBe(false);
});

const run = (o: Partial<RunSummary>): RunSummary =>
  ({
    id: "r",
    investigationId: "inv",
    runNumber: 1,
    kind: "experiment_replay",
    status: "completed",
    outcome: "verified_recommendation",
    parentRunId: "p",
    replay: null,
    finalized: true,
    createdAt: "2026-10-12T10:00:00Z",
    startedAt: null,
    finishedAt: null,
    ...o,
  }) as RunSummary;

test("the run selector reads the report of every sealed replay, and of nothing else", () => {
  const runs = [
    run({ id: "a" }),
    run({ id: "b", outcome: "inconclusive" }),
    run({ id: "c", kind: "initial" }),
    run({ id: "d", finalized: false, status: "running", outcome: null }),
    run({ id: "e", status: "failed", outcome: null }),
  ];
  expect(sealedReplayRuns(runs).map((r) => r.id)).toEqual(["a", "b", "e"]);
});

const meta = (name: Name) => {
  const r = v2(name);
  return replayReportMeta({ builderVersion: r.builderVersion, reportSchemaVersion: r.schemaVersion, report: r as never });
};

test("selector labels: the builder's title for schema-2 replays, the stored outcome plus legacy tag for v1", () => {
  expect(runOutcomeLabel(run({}), meta("1_reproduced_original"))).toEqual({ outcome: "Original recommendation reproduced", legacy: false });
  expect(runOutcomeLabel(run({ outcome: "inconclusive" }), meta("2_performance_drift"))).toEqual({ outcome: "Performance drift detected", legacy: false });
  expect(runOutcomeLabel(run({ outcome: "inconclusive" }), meta("3_not_reproduced_verdict"))).toEqual({ outcome: "Original result not reproduced", legacy: false });
  expect(runOutcomeLabel(run({ outcome: "inconclusive" }), meta("4_inconclusive_comparison"))).toEqual({ outcome: "Replay comparison inconclusive", legacy: false });
  expect(runOutcomeLabel(run({ outcome: "inconclusive" }), meta("5_cross_environment"))).toEqual({ outcome: "Results not directly comparable", legacy: false });
  expect(runOutcomeLabel(run({ status: "failed", outcome: null }), meta("15_execution_failed"))).toEqual({ outcome: "Replay failed", legacy: false });
  expect(runOutcomeLabel(run({}), meta("legacy_v1_replay"))).toEqual({ outcome: "verified recommendation", legacy: true });
  expect(runOutcomeLabel(run({ outcome: "inconclusive" }), meta("legacy_v1_replay"))).toEqual({ outcome: "inconclusive", legacy: true });
});

test("selector labels before the report is known: never a bare verified replay; ordinary runs unchanged", () => {
  expect(runOutcomeLabel(run({}))).toEqual({ outcome: null, legacy: false });
  expect(runOutcomeLabel(run({ status: "failed", outcome: null }))).toEqual({ outcome: "Replay failed", legacy: false });
  expect(runOutcomeLabel(run({ outcome: "inconclusive" }))).toEqual({ outcome: "inconclusive", legacy: false });
  expect(runOutcomeLabel(run({ kind: "initial" }))).toEqual({ outcome: "verified recommendation", legacy: false });
  expect(runOutcomeLabel(run({ kind: "reinvestigation", outcome: "no_action_needed" }))).toEqual({ outcome: "no action needed", legacy: false });
  expect(runOutcomeLabel(run({ kind: "initial" }), meta("1_reproduced_original"))).toEqual({ outcome: "verified recommendation", legacy: false });
});

test("schema-2 replay sections: replay measurement, result, then the original recommendation", () => {
  expect(reportSections(v2("1_reproduced_original")).map((s) => s.title)).toEqual([
    "Query",
    "Replay measurement",
    "Experiment replay result",
    "Original recommendation",
    "Comparison with the original",
    "Limitations",
    "Next steps",
    "Missing evidence",
    "Provenance and integrity",
  ]);
  const drift = reportSections(v2("2_performance_drift")).map((s) => s.title);
  expect(drift).toContain("Recommendation");
  expect(drift).not.toContain("Original recommendation");
  // the historical v1 replay keeps its v1 sections
  expect(reportSections(v2("legacy_v1_replay")).map((s) => s.title)).toContain("Optimizations, approvals and benchmarks");
});

test("the headline body drops the title it starts with (the title is the heading)", () => {
  expect(headlineBody(v2("1_reproduced_original"))).toMatch(/^A new sandbox measurement of the same experiment/);
  expect(headlineBody(v2("3_not_reproduced_rows"))).toMatch(/^The result rows changed\. The original result is not confirmed/);
  // not "title:" or "title." — the whole headline stays
  expect(headlineBody(v2("15_execution_failed"))).toBe("Replay failed (sandbox_unavailable): nothing was compared with the original.");
  expect(headlineBody(v2("legacy_v1_replay"))).toBe(v2("legacy_v1_replay").headline);
});

test("problem and hypotheses appear on a replay page only when the sealed report has them", () => {
  const base = v2("2_performance_drift");
  expect(reportSections(base).map((s) => s.title)).not.toContain("Hypotheses");
  const withHyp = { ...base, hypotheses: [{ key: "hy_1" } as ReportV1["hypotheses"][number]] };
  expect(reportSections(withHyp).map((s) => s.title)).toContain("Hypotheses");
});
