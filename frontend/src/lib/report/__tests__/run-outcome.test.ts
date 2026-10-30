import { expect, test } from "vitest";
import fixtures from "@/test/fixtures/report-v2.json";
import type { RunSummary } from "@/lib/api/types";
import type { ReportV1 } from "../types";
import { classifyRunOutcome, replayReportMeta, replayReportState, runOutcomeLabel, runOutcomeText, type ReplayReportState } from "../replay";

/* One labelling contract for every surface that shows a run's outcome (REPLAY_OUTCOME_AUDIT §18):
 * the run selector, History, Dashboard, the investigation header and the event log. A replay's
 * stored outcome alone never reads as a verification. */

type Name = Exclude<keyof typeof fixtures, "_note">;
const v2 = (name: Name) => fixtures[name] as unknown as ReportV1;
const loaded = (name: Name): ReplayReportState => {
  const r = v2(name);
  return { status: "loaded", meta: replayReportMeta({ builderVersion: r.builderVersion, reportSchemaVersion: r.schemaVersion, report: r as never }) };
};

const run = (o: Partial<RunSummary>): RunSummary =>
  ({
    id: "r",
    investigationId: "inv",
    runNumber: 2,
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
const text = (r: RunSummary, s?: ReplayReportState) => runOutcomeText(classifyRunOutcome(r, s));

test("ordinary investigations keep their stored outcome", () => {
  expect(text(run({ kind: "initial" }))).toMatchObject({ label: "Verified recommendation", tone: "success", legacy: false });
  expect(text(run({ kind: "reinvestigation", outcome: "unverified_recommendations" }))).toMatchObject({ label: "Unverified recommendations", tone: "neutral" });
  expect(text(run({ kind: "initial", outcome: "no_action_needed" }))).toMatchObject({ label: "No action needed", tone: "neutral" });
  expect(text(run({ kind: "initial", outcome: "inconclusive" }))).toMatchObject({ label: "Inconclusive", tone: "warning" });
  // an outcome this client does not know yet still reads as itself, never as verified
  expect(text(run({ kind: "initial", outcome: "something_new" }))).toMatchObject({ label: "Something new", tone: "neutral" });
  // a report never changes an ordinary run's label
  expect(text(run({ kind: "initial" }), loaded("1_reproduced_original")).label).toBe("Verified recommendation");
});

test("ordinary runs without a concluded outcome show their status", () => {
  expect(text(run({ kind: "initial", status: "running", outcome: null, finalized: false }))).toMatchObject({ label: "Running", tone: "running" });
  expect(text(run({ kind: "initial", status: "failed", outcome: null }))).toMatchObject({ label: "Failed", tone: "failed" });
  expect(text(run({ kind: "initial", status: "cancelled", outcome: null }))).toMatchObject({ label: "Cancelled", tone: "neutral" });
});

test("schema-2 replays show the builder's sealed title", () => {
  const cases: [Name, string, string][] = [
    ["1_reproduced_original", "Original recommendation reproduced", "success"],
    ["2_performance_drift", "Performance drift detected", "warning"],
    ["3_not_reproduced_rows", "Original result not reproduced", "failed"],
    ["4_inconclusive_comparison", "Replay comparison inconclusive", "warning"],
    ["5_cross_environment", "Results not directly comparable", "warning"],
  ];
  for (const [name, label, tone] of cases) {
    const outcome = name === "1_reproduced_original" ? "verified_recommendation" : "inconclusive";
    expect(text(run({ outcome }), loaded(name))).toMatchObject({ label, tone, legacy: false });
  }
});

test("historical schema-1 replays keep their stored outcome, with legacy context and no verified tone", () => {
  const legacy = text(run({}), loaded("legacy_v1_replay"));
  expect(legacy).toMatchObject({ label: "Legacy replay · verified recommendation", tone: "neutral", legacy: true });
  expect(legacy.title).toMatch(/does not independently verify a recommendation/);
  expect(text(run({ outcome: "inconclusive" }), loaded("legacy_v1_replay")).label).toBe("Legacy replay · inconclusive");
});

test("replays in flight show their execution status, never an outcome", () => {
  for (const status of ["queued", "running", "awaiting_approval", "cancelling"]) {
    // even a stale or unexpected stored outcome is not read while the run is in flight
    const view = text(run({ status, finalized: false }), loaded("1_reproduced_original"));
    expect(view.label).not.toMatch(/verified|reproduced/i);
    expect(classifyRunOutcome(run({ status, finalized: false })).kind).toBe("status");
  }
  expect(text(run({ status: "running", outcome: null, finalized: false })).label).toBe("Running");
  expect(text(run({ status: "queued", outcome: null, finalized: false })).label).toBe("Queued");
});

test("failed and cancelled replays show their terminal status", () => {
  expect(text(run({ status: "failed", outcome: null }))).toMatchObject({ label: "Replay failed", tone: "failed" });
  expect(text(run({ status: "cancelled", outcome: null }))).toMatchObject({ label: "Replay cancelled", tone: "neutral" });
  // a stored outcome on a failed replay is still not read as a verification
  expect(text(run({ status: "failed" }), { status: "loading" }).label).toBe("Replay failed");
  expect(text(run({ status: "failed", outcome: null }), loaded("15_execution_failed")).label).toBe("Replay failed");
});

test("a completed replay whose report is loading, not requested, missing or unreadable claims nothing", () => {
  const states: (ReplayReportState | undefined)[] = [undefined, { status: "loading" }, { status: "error" }];
  for (const s of states) {
    for (const outcome of ["verified_recommendation", "inconclusive"]) {
      const view = text(run({ outcome }), s);
      expect(view.label.startsWith("Replay completed")).toBe(true);
      expect(view.tone).toBe("neutral");
      expect(view.label).not.toMatch(/verified|reproduced|inconclusive/i);
    }
  }
  expect(text(run({}), { status: "error" }).label).toBe("Replay completed · report unavailable");
});

test("an unknown report builder or format is not interpreted", () => {
  const unknown: ReplayReportState = { status: "loaded", meta: { builderVersion: "report-builder@9", replayTitle: null, replayResult: null } };
  expect(text(run({}), unknown)).toMatchObject({ label: "Replay completed · see report", tone: "neutral", legacy: false });
  expect(text(run({}), unknown).title).toMatch(/report-builder@9/);
});

test("no replay is ever labelled a verified recommendation from its stored outcome alone", () => {
  const names = Object.keys(fixtures).filter((n) => n !== "_note") as Name[];
  const states: (ReplayReportState | undefined)[] = [undefined, { status: "loading" }, { status: "error" }, ...names.map(loaded)];
  for (const status of ["queued", "running", "awaiting_approval", "cancelling", "completed", "failed", "cancelled"]) {
    for (const s of states) {
      const view = text(run({ status }), s);
      expect(view.label).not.toBe("Verified recommendation");
      if (!view.legacy) expect(view.label).not.toMatch(/verified recommendation/i);
      if (view.tone === "success") expect(view.label).toBe("Original recommendation reproduced");
    }
  }
});

test("report query state: data wins, then error, else loading", () => {
  const r = v2("1_reproduced_original");
  const data = { builderVersion: r.builderVersion, reportSchemaVersion: r.schemaVersion, report: r } as never;
  expect(replayReportState({ data, isError: false })).toMatchObject({ status: "loaded", meta: { replayTitle: "Original recommendation reproduced", replayResult: "original_reproduced" } });
  expect(replayReportState({ data: undefined, isError: true })).toEqual({ status: "error" });
  expect(replayReportState({ data: undefined, isError: false })).toEqual({ status: "loading" });
});

test("the run selector uses the same classification", () => {
  expect(runOutcomeLabel(run({ status: "cancelled", outcome: null }))).toEqual({ outcome: "Replay cancelled", legacy: false });
  // pending: no outcome is claimed, whatever was stored
  expect(runOutcomeLabel(run({ outcome: "inconclusive" }))).toEqual({ outcome: null, legacy: false });
  expect(runOutcomeLabel(run({ status: "running", outcome: null, finalized: false }))).toEqual({ outcome: null, legacy: false });
  expect(runOutcomeLabel(run({}), { builderVersion: "report-builder@9", replayTitle: null, replayResult: null })).toEqual({ outcome: "replay result in report", legacy: false });
});
