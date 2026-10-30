import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import matrix from "@/test/fixtures/replay-consistency.json";
import fixtures from "@/test/fixtures/report-v2.json";
import { ReportView } from "@/components/report/ReportView";
import { ResultSummary } from "@/components/report/ResultSummary";
import { RunPicker } from "@/components/investigation/RunPicker";
import type { RunSummary } from "@/lib/api/types";
import type { ReportV1 } from "../types";
import { headlineBody, isLegacyReplayReport, replayReportMeta, replayResultOf, reportTitle } from "../replay";

/* The cross-layer replay matrix (frontend/src/test/fixtures/replay-consistency.json) on the
 * report view, the result summary and the run selector. The backend reads the same rows for
 * the builder, the Markdown, the API, the exports and real sealed runs. Reports are real
 * builder output for the row's synthetic scenario (report-v2.json). */

type Row = (typeof matrix)["reproduced"] & { material_drift?: boolean; correctness_reproduced?: boolean };
type FixtureName = Exclude<keyof typeof fixtures, "_note">;
const rows = Object.entries(matrix).filter(([k]) => !k.startsWith("_")) as [string, Row][];

function reportFor(row: Row): ReportV1 {
  const name = (row.legacy ? "legacy_v1_replay" : row.unit_scenario) as FixtureName;
  return fixtures[name] as unknown as ReportV1;
}

function replayRun(row: Row): RunSummary {
  return {
    id: "run-2",
    investigationId: "inv",
    runNumber: 2,
    kind: "experiment_replay",
    status: row.run_status,
    outcome: row.outcome,
    parentRunId: "run-1",
    replay: null,
    finalized: true,
    createdAt: "2026-10-12T10:00:00Z",
    startedAt: null,
    finishedAt: null,
  } as RunSummary;
}

afterEach(cleanup);

test("the matrix has the ten approved scenarios and a report for each", () => {
  expect(rows.map(([k]) => k).sort()).toEqual(
    ["cross_environment", "historical_v1", "inconclusive_comparison", "mismatched_experiment", "noise_warning_original", "not_reproduced", "performance_drift", "replay_of_replay", "reproduced", "snapshot_missing"],
  );
  for (const [, row] of rows) expect(reportFor(row)).toBeTruthy();
});

test.each(rows)("%s: report JSON fields match the matrix", (_name, row) => {
  const r = reportFor(row);
  expect([r.schemaVersion, r.builderVersion, r.outcome, r.finalStatus]).toEqual([row.schema_version, row.builder_version, row.outcome, row.run_status]);
  expect(r.recommendation.status).toBe(row.recommendation_status);
  expect(r.recommendation.origin ?? null).toBe(row.recommendation_origin);
  expect(isLegacyReplayReport(r)).toBe(row.legacy);
  const rr = replayResultOf(r);
  if (row.legacy) {
    expect(rr).toBeNull();
    return;
  }
  expect(rr).not.toBeNull();
  expect([rr!.result, rr!.title, rr!.claimsReproduction, rr!.originalReproduced]).toEqual([row.result, row.title, row.claims_reproduction, row.original_reproduced]);
  expect([rr!.basis?.code, rr!.basis?.comparisonStatus, rr!.basis?.comparisonMode]).toEqual([row.basis, row.comparison_status, row.comparison_mode]);
  if (row.material_drift !== undefined) expect(rr!.materialDrift).toBe(row.material_drift);
  if (row.correctness_reproduced !== undefined) expect(rr!.correctnessReproduced).toBe(row.correctness_reproduced);
});

test.each(rows)("%s: report view title, single headline and recommendation provenance", (_name, row) => {
  const r = reportFor(row);
  render(<ReportView report={r} />);
  expect(reportTitle(r)).toBe(row.title);
  const [h1, ...more] = screen.getAllByRole("heading", { level: 1 });
  expect(h1?.textContent).toBe(row.title);
  expect(more).toHaveLength(0);
  // the headline is shown once, without repeating the title it starts with
  if (row.legacy) expect(headlineBody(r)).toBe(r.headline);
  else expect(headlineBody(r).startsWith(row.title)).toBe(false);
  const original = screen.queryByRole("region", { name: "Original recommendation" });
  expect(original !== null).toBe(row.recommendation_origin === "source_run");
  if (!row.legacy) {
    expect(screen.queryByText("Verified recommendation")).toBeNull();
    expect(screen.getByRole("region", { name: "Experiment replay result" })).toBeTruthy();
  }
});

test.each(rows)("%s: result summary title and legacy notice", (_name, row) => {
  render(<ResultSummary report={reportFor(row)} onReport={() => undefined} />);
  expect(screen.getByRole("heading", { level: 2 }).textContent).toBe(row.title);
  expect(screen.queryByText("Legacy replay") !== null).toBe(row.legacy);
});

test.each(rows)("%s: run selector label", (_name, row) => {
  const r = reportFor(row);
  const meta = replayReportMeta({ builderVersion: r.builderVersion, reportSchemaVersion: r.schemaVersion, report: r as never });
  const run = replayRun(row);
  render(<RunPicker runs={[run]} selectedId={null} onSelect={() => undefined} replayReports={new Map([[run.id, meta]])} />);
  const item = screen.getByRole("menuitemradio");
  expect(item.textContent).toContain(`· ${row.selector_label}`);
  expect(within(item).queryByText("legacy replay") !== null).toBe(row.legacy);
  if (!row.legacy) expect(item.textContent?.toLowerCase()).not.toContain("verified recommendation");
});
