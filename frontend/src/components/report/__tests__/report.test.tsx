import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQuery } from "@/test/render";
import { ApiError } from "@/lib/api/client";
import { experimentReplayLabel } from "@/lib/report/labels";
import type { Comparison, ReportV1 } from "@/lib/report/types";
import { ComparisonView, StatusBadge } from "@/components/replay/ReplayView";
import { PlanDiffTable, diffSummary } from "@/components/plan/PlanDiffView";
import type { PlanDiff } from "@/lib/api/types";
import { ReportView } from "../ReportView";
import { ReportPanel } from "../ReportPanel";
import { ResultSummary } from "../ResultSummary";

const getReport = vi.fn();
const verifyReport = vi.fn();
vi.mock("@/lib/api/reports", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  getReport: (...a: unknown[]) => getReport(...a),
  verifyReport: (...a: unknown[]) => verifyReport(...a),
  getReportMarkdown: () => Promise.resolve("# Stored markdown body"),
}));

afterEach(() => {
  cleanup();
  getReport.mockReset();
  verifyReport.mockReset();
  window.localStorage.clear();
});

const measurement = {
  arm: "oc_0000000000a1",
  paramSet: "hot",
  baseline: { n: 30, medianNs: 12_000_000, p95Ns: 13_000_000, robustCv: 0.05 },
  candidate: { n: 30, medianNs: 1_000_000, p95Ns: 1_100_000, robustCv: 0.06 },
  speedup: 12,
  ciLow: 10.5,
  ciHigh: 13.4,
  provenance: "measured",
  evidenceId: "ev_0123456789ab",
  source: { artifactSha256: "ab".repeat(32), pointer: "/stats/0" },
};

function report(overrides: Partial<ReportV1> = {}, status: ReportV1["recommendation"]["status"] = "verified"): ReportV1 {
  const verified = status === "verified" || status === "verified_with_noise_warning";
  return {
    schemaVersion: 1,
    builderVersion: "report-builder@1",
    run: { id: "run-1", investigationId: "inv-1", runNumber: 1, kind: "initial", parentRunId: null },
    investigation: { title: "Orders", objective: "Make it fast", modes: ["sandbox_benchmark"], workloadId: "orders_ecommerce@v1:sf=1:seed=42", liveConnection: false },
    finalizedAt: "2026-10-13T12:00:00.000000Z",
    events: { cutoffSeq: 42, digest: "sha256:" + "cd".repeat(32), profile: "qc-events-v1" },
    finalStatus: "completed",
    outcome: verified ? "verified_recommendation" : "inconclusive",
    stopReason: null,
    partial: false,
    headline: "A candidate change was verified in an isolated sandbox.",
    summary: "The scan dominates.",
    query: { sql: "SELECT 1", sha256: "11".repeat(32), paramSets: [{ name: "hot", values: [1] }] },
    problem: { evidence: [], materiality: { verdict: "material", reasons: [], evidenceIds: [] } },
    hypotheses: [],
    findings: [],
    evidence: [],
    rounds: [
      {
        round: 0,
        approval: { id: "ap", round: 0, status: "approved", decidedBy: "user:1", decidedAt: null, approvedCandidateIds: [] },
        candidates: [
          {
            key: "oc_0000000000a1",
            kind: "create_index",
            ddl: ["CREATE INDEX ON orders (customer_id, created_at)"],
            querySql: null,
            sqlSha256: "x",
            addressesHypotheses: [],
            expectedBenefit: "Avoid the sort",
            risks: [],
            status: verified ? status : "inconclusive",
            reasons: verified ? [] : [{ code: "audit_downgrade" }],
          },
        ],
        experiment: {
          id: "exp-1",
          round: 0,
          replicate: 0,
          status: "completed",
          engineVersion: "bench@2",
          rowProfile: "qc-row-v1",
          seed: 1,
          provenance: "measured",
          resultSha256: "ab".repeat(32),
          errorCode: null,
          environment: { digest: "sha256:e", pgVersion: "170011", cpuArch: "arm64", cpuModel: "", cpuCount: 8, memoryBytes: 1, os: "Darwin", containerRuntime: "docker-network", sandboxImageDigest: "postgres:17", workloadId: "w", workloadDataDigest: "d", provenance: "recorded" },
          config: null,
          builds: [],
          verdicts: [],
          tournament: [],
          winner: null,
          measurements: [measurement],
          correctness: [],
          replication: null,
          audit: [
            {
              arm: "oc_0000000000a1",
              engineVerdict: "verified",
              verdict: verified ? "verified" : "inconclusive",
              downgraded: !verified,
              auditorStatus: "completed",
              promptVersion: "benchmark_auditor@1",
              notes: "Fine.",
              checks: [{ name: "plan_change", status: "pass", detail: "new index used", evidenceIds: [] }],
              concerns: [],
            },
          ],
        },
        replicates: [],
      },
    ],
    recommendation: verified
      ? { status, candidateKey: "oc_0000000000a1", kind: "create_index", ddl: ["CREATE INDEX ON orders (customer_id, created_at)"], querySql: null, primaryMeasurement: measurement, scope: "sandbox" }
      : { status: "unverified", candidateKey: null, kind: null, ddl: [], querySql: null, primaryMeasurement: null, scope: "sandbox" },
    limitations: ["Measured in a disposable sandbox copy."],
    nextSteps: ["Review the SQL."],
    provenance: { measurements: ["measured"], stubModel: false, llm: [] },
    replay: null,
    missing: [],
    errors: [],
    usage: null,
    ...overrides,
  };
}

test("verified report states sandbox scope, labels numbers and recommends the exact SQL", () => {
  render(<ReportView report={report()} />);

  expect(screen.getByText("Verified recommendation")).toBeTruthy();
  expect(screen.getByText(/Nothing was applied to your database/)).toBeTruthy();
  const rec = screen.getByRole("region", { name: "Recommendation" });
  expect(within(rec).getByText(/CREATE INDEX ON orders/)).toBeTruthy();
  expect(within(rec).getByText(/12\.0×/)).toBeTruthy();
  expect(within(rec).getByText("measured")).toBeTruthy();
});

test("noise warning is spelled out", () => {
  render(<ReportView report={report({}, "verified_with_noise_warning")} />);

  expect(screen.getAllByText(/noise warning/i).length).toBeGreaterThan(0);
  expect(screen.getByText(/treat its size as uncertain/)).toBeTruthy();
});

test("auditor downgrade is shown and nothing is recommended", () => {
  render(<ReportView report={report({}, "unverified")} />);

  expect(screen.getByText("Downgraded by the Benchmark Auditor")).toBeTruthy();
  expect(screen.getByText(/No change is recommended as verified/)).toBeTruthy();
  expect(screen.getByText(/Benchmark Auditor found a reason to doubt/)).toBeTruthy();
});

test("prerecorded, stub and partial reports carry their banners and missing evidence", () => {
  render(
    <ReportView
      report={report({
        provenance: { measurements: ["prerecorded"], stubModel: true, llm: [] },
        partial: true,
        stopReason: "cancelled",
        missing: [{ section: "benchmark", reason: "not benchmarked" }],
      })}
    />,
  );

  expect(screen.getByText(/prerecorded demo measurements: these are not live results/)).toBeTruthy();
  expect(screen.getByText(/offline stub model/)).toBeTruthy();
  expect(screen.getByText(/Partial report/)).toBeTruthy();
  expect(screen.getByRole("region", { name: "Missing evidence" })).toBeTruthy();
});

test("Why? opens lineage with the evidence and the source artifact", async () => {
  const onWhy = vi.fn();
  render(<ReportView report={report()} onWhy={onWhy} />);

  await userEvent.click(screen.getAllByRole("button", { name: /Why: Speed-up 12\.0×/ })[0]!);

  expect(onWhy).toHaveBeenCalledWith(
    expect.objectContaining({ evidenceIds: ["ev_0123456789ab"], artifact: expect.objectContaining({ pointer: "/stats/0" }) }),
  );
});

test("report panel: loading, not finalized, verify result wording", async () => {
  getReport.mockReturnValue(new Promise(() => undefined));
  renderWithQuery(<ReportPanel runId="run-1" />);
  expect(screen.getByText("Loading report…")).toBeTruthy();
  cleanup();

  getReport.mockRejectedValue(new ApiError("NOT_FINALIZED", "no", 404, [], null));
  renderWithQuery(<ReportPanel runId="run-1" />);
  expect(await screen.findByText(/final report is written when the run ends/)).toBeTruthy();
  cleanup();

  getReport.mockResolvedValue({ reportSchemaVersion: 1, manifestSha256: "f".repeat(64), report: report() });
  verifyReport.mockResolvedValue({ status: "verified", failureCode: null, warnings: [], result: { checks: [{ name: "manifest", status: "ok", code: null, detail: "" }] } });
  renderWithQuery(<ReportPanel runId="run-1" />);
  await userEvent.click(await screen.findByRole("button", { name: "Verify report" }));
  expect(await screen.findByText("Integrity check passed against stored digests")).toBeTruthy();
  expect(screen.queryByText(/tamper/i)).toBeNull();
});

test("a failed report request shows the error and claims no outcome (REPLAY_OUTCOME_AUDIT §18.1)", async () => {
  getReport.mockRejectedValue(new ApiError("INTERNAL_ERROR", "The report could not be loaded.", 500, [], null));
  renderWithQuery(<ReportPanel runId="run-1" />);
  expect(await screen.findByText("The report could not be loaded.")).toBeTruthy();
  expect(screen.queryByText(/verified recommendation|reproduced/i)).toBeNull();
  expect(screen.queryByRole("button", { name: "Verify report" })).toBeNull();
});

test("unknown report schema falls back to the stored markdown", async () => {
  getReport.mockResolvedValue({ reportSchemaVersion: 7, manifestSha256: "f".repeat(64), report: {} });
  renderWithQuery(<ReportPanel runId="run-1" />);

  expect(await screen.findByText(/newer version than this page understands/)).toBeTruthy();
  expect(await screen.findByText("# Stored markdown body")).toBeTruthy();
});

const comparison = (mode: Comparison["comparisonMode"], status = "reproduced"): Comparison => ({
  status,
  failureCode: null,
  comparisonMode: mode,
  config: { margin: 1.25, resamples: 2000, confidence: 0.95, seed: 1 },
  pairs: [
    {
      arm: "oc_0000000000a1", paramSet: "hot", status: status as "reproduced", code: null, originalVerdict: "verified", replayVerdict: "verified",
      originalSpeedup: 12, replaySpeedup: 11.5, originalCi: [10, 13], replayCi: [10, 13], originalMediansNs: [12e6, 1e6], replayMediansNs: [11e6, 0.9e6],
      drift: 0.96, driftCiLow: 0.85, driftCiHigh: 1.1,
    },
  ],
  environment: { originalDigest: "a", replayDigest: "b", differences: mode === "cross_environment" ? [{ field: "cpu_count", class: "material", original: 8, replay: 16 }] : [] },
  winner: { original: "oc_0000000000a1", replay: "oc_0000000000a1" },
  limitations: ["Coverage: two experiments."],
});

test("same-environment comparison says reproduced; cross-environment never does", () => {
  render(<ComparisonView comparison={comparison("same_environment")} replayRunId="r2" />);
  expect(screen.getAllByText("Reproduced").length).toBeGreaterThan(0);
  cleanup();

  render(<ComparisonView comparison={comparison("cross_environment")} replayRunId={null} />);
  expect(screen.getByText(/not a reproduction/)).toBeTruthy();
  expect(screen.getAllByText("Consistent across environments").length).toBeGreaterThan(0);
  expect(screen.queryByText(/^Reproduced/)).toBeNull();
  expect(screen.getByText(/cpu_count: 8 → 16/)).toBeTruthy();
});

test("replay status wording for every status", () => {
  for (const s of ["reproduced", "reproduced_with_drift", "not_reproduced"]) {
    expect(experimentReplayLabel(s, "cross_environment").toLowerCase()).not.toContain("reproduced");
  }
  expect(experimentReplayLabel("queued", null)).toBe("Queued");
  render(<StatusBadge attempt={{ kind: "report", status: "integrity_failed", result: {} }} />);
  expect(screen.getByText("Integrity check failed")).toBeTruthy();
});

test("plan diff summary reads like the design", () => {
  const diff = {
    summary: {
      same: 1, changed: 1, added: 0, removed: 1, addedNodeTypes: [], removedNodeTypes: ["Sort"], indexesUsedFrom: [], indexesUsedTo: ["o_idx"],
      newIndexesUsed: ["o_idx"],
      executionTimeMs: { fromValue: 121, toValue: 0.4, ratio: 302.5 },
      planningTimeMs: { fromValue: null, toValue: null, ratio: null },
      rootTotalCost: { fromValue: null, toValue: null, ratio: null },
    },
    nodes: [
      { status: "changed", fromId: 1, toId: 1, fromLocator: "/a", toLocator: "/b", nodeTypeFrom: "Seq Scan", nodeTypeTo: "Index Scan", relation: "orders", indexFrom: null, indexTo: "o_idx", depth: 1, changes: ["node_type", "index_name"], metrics: { inclusiveTimeMs: { fromValue: 100, toValue: 0.2, ratio: 500 } } },
    ],
  } as unknown as PlanDiff;

  expect(diffSummary(diff)).toBe("Seq Scan → Index Scan on orders; Sort removed; new index used: o_idx");
  render(<PlanDiffTable diff={diff} />);
  // Side by side: each plan's node in its own column, the change named between them.
  expect(screen.getByRole("button", { name: "Seq Scan → Index Scan, type changed: show recorded metrics" })).toBeTruthy();
  expect(screen.getByText("Seq Scan")).toBeTruthy();
  expect(screen.getByText("Index Scan")).toBeTruthy();
});

test("the standalone report page links its run, the replay page and the original run, with a contents list", async () => {
  getReport.mockResolvedValue({
    reportSchemaVersion: 1,
    manifestSha256: "f".repeat(64),
    report: report({
      run: { id: "run-2", investigationId: "inv-1", runNumber: 2, kind: "experiment_replay", parentRunId: "run-1" },
      replay: { replayOf: { experimentId: "e".repeat(32), runId: "run-1" }, comparison: null },
    }),
  });
  renderWithQuery(<ReportPanel runId="run-2" standalone />);

  const nav = await screen.findByRole("navigation", { name: "Report navigation" });
  const href = (name: string | RegExp) => within(nav).getByRole("link", { name }).getAttribute("href");
  expect(href("Open the run")).toBe("/app/investigations/inv-1?run=run-2");
  expect(href("Reproducibility & replay")).toBe("/app/replay/run-2");
  expect(href("Original run's report")).toBe("/app/reports/run-1");
  // The parent is the original here, so it is not listed twice.
  expect(within(nav).queryByRole("link", { name: "Parent run" })).toBeNull();
  expect(screen.getByRole("navigation", { name: "Breadcrumb" }).textContent).toContain("Orders");

  const toc = screen.getByRole("navigation", { name: "Report contents" });
  const entries = within(toc).getAllByRole("link").map((a) => a.getAttribute("href"));
  expect(entries[0]).toBe("#report-query");
  for (const id of entries) expect(document.querySelector(id ?? "")).not.toBeNull();
});

test("the investigation's Report tab has no contents list or page navigation", async () => {
  getReport.mockResolvedValue({ reportSchemaVersion: 1, manifestSha256: "f".repeat(64), report: report() });
  renderWithQuery(<ReportPanel runId="run-1" />);
  await screen.findByRole("article", { name: "Final report" });
  expect(screen.queryByRole("navigation", { name: "Report contents" })).toBeNull();
  expect(screen.queryByRole("navigation", { name: "Report navigation" })).toBeNull();
});

test("result summary puts outcome, verdict, candidate and CI first; limitations are one disclosure away", async () => {
  const onReport = vi.fn();
  const onBenchmark = vi.fn();
  render(<ResultSummary report={report({ limitations: ["Measured in a disposable sandbox copy.", "Warm cache only."] })} onReport={onReport} onBenchmark={onBenchmark} />);
  const s = screen.getByRole("region", { name: "Result summary" });
  expect(within(s).getByRole("heading", { name: "Verified recommendation" })).toBeTruthy();
  expect(within(s).getByText("A candidate change was verified in an isolated sandbox.")).toBeTruthy();
  expect(within(s).getByText("Composite index on orders (customer_id, created_at)")).toBeTruthy();
  expect(within(s).getByText("oc_0000000000a1")).toBeTruthy();
  expect(within(s).getByText(/12\.0×/)).toBeTruthy();
  expect(within(s).getByText(/10\.5×–13\.4×/)).toBeTruthy();
  // Provenance is never collapsed; the limitations are, behind a labelled disclosure.
  expect(within(s).getByText(/Nothing was applied to your database/)).toBeTruthy();
  const disclosure = within(s).getByRole("button", { name: "Limitations (2)" });
  expect(disclosure.getAttribute("aria-expanded")).toBe("false");
  expect(within(s).queryByRole("list", { name: "Limitations" })).toBeNull();
  await userEvent.click(disclosure);
  expect(disclosure.getAttribute("aria-expanded")).toBe("true");
  expect(within(within(s).getByRole("list", { name: "Limitations" })).getByText("Warm cache only.")).toBeTruthy();
  expect(within(s).getByText("Measured in a disposable sandbox copy.")).toBeTruthy();
  // The AI-written summary stays in the report, not in the summary.
  expect(within(s).queryByText("The scan dominates.")).toBeNull();
  await userEvent.click(within(s).getByRole("button", { name: "Full report" }));
  await userEvent.click(within(s).getByRole("button", { name: "Benchmark details" }));
  expect(onReport).toHaveBeenCalledOnce();
  expect(onBenchmark).toHaveBeenCalledOnce();
});

test("result summary without a recommendation says so and keeps warnings", () => {
  render(
    <ResultSummary
      report={report({ partial: true, stopReason: "budget_exhausted", provenance: { measurements: ["prerecorded"], stubModel: true, llm: [] } }, "unverified")}
      onReport={() => {}}
    />,
  );
  const s = screen.getByRole("region", { name: "Result summary" });
  expect(within(s).getByRole("heading", { name: "Inconclusive" })).toBeTruthy();
  expect(within(s).getByText(/No recommendation was verified/)).toBeTruthy();
  expect(within(s).getByText(/Partial report/)).toBeTruthy();
  expect(within(s).getByText(/prerecorded/i)).toBeTruthy();
  expect(within(s).getByText(/offline stub model/)).toBeTruthy();
  expect(within(s).queryByRole("button", { name: "Benchmark details" })).toBeNull();
});

// --- Report schema 2 and historical replay notices (Workstream 5) ------------------------
// Fixtures are real report-builder@2 / @1 output for synthetic inputs (backend
// tests/unit/reports/test_frontend_report_fixture.py keeps them current).
import v2fixtures from "@/test/fixtures/report-v2.json";

type V2Name = Exclude<keyof typeof v2fixtures, "_note">;
const v2 = (name: V2Name) => v2fixtures[name] as unknown as ReportV1;
const LEGACY_COPY =
  "Earlier replay classification. This report used an older outcome rule based on the replay's measurement, not its comparison with the original investigation. It does not independently verify a recommendation.";
const LEGACY = /older outcome rule based on the replay's measurement/;

test("a reproduced schema-2 replay says reproduced and shows the original recommendation from its source run", () => {
  render(<ReportView report={v2("1_reproduced_original")} />);
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Original recommendation reproduced");
  expect(screen.queryByText("Verified recommendation")).toBeNull();
  const original = screen.getByRole("region", { name: "Original recommendation" });
  expect(within(original).getByText("Source run").nextSibling?.textContent).toBe("00000000-0000-4000-8000-0000000000bb");
  expect(within(original).getByText(/reproduced by this replay/)).toBeTruthy();
  const result = screen.getByRole("region", { name: "Experiment replay result" });
  expect(within(result).getByText("Correctness reproduced").nextSibling?.textContent).toBe("Yes");
  expect(within(result).getByText(/replay measurement, not a verification/)).toBeTruthy();
  expect(screen.queryByText(LEGACY)).toBeNull();
});

test.each([
  ["2_performance_drift", "Performance drift detected"],
  ["3_not_reproduced_rows", "Original result not reproduced"],
  ["5_cross_environment", "Results not directly comparable"],
  ["8_inconclusive_source_with_replay_winner", "Re-measurement only"],
  ["14_not_replayable", "No comparison with the original was possible"],
  ["15_execution_failed", "Replay failed"],
] as const)("schema-2 replay %s: no recommendation of its own, never a verified card", (name, title) => {
  render(<ReportView report={v2(name)} />);
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(title);
  expect(screen.queryByText("Verified recommendation")).toBeNull();
  expect(screen.queryByRole("region", { name: "Original recommendation" })).toBeNull();
  expect(within(screen.getByRole("region", { name: "Recommendation" })).getByText("This replay makes no recommendation of its own.")).toBeTruthy();
});

test("the drifted replay shows the original candidate for reference only", () => {
  render(<ReportView report={v2("2_performance_drift")} />);
  const rec = screen.getByRole("region", { name: "Recommendation" });
  expect(within(rec).getByText(/shown for reference and is not confirmed by this replay/)).toBeTruthy();
  const result = screen.getByRole("region", { name: "Experiment replay result" });
  expect(within(result).getByText("Material drift").nextSibling?.textContent).toBe("Yes");
});

test("result summary: schema-2 replay line, the original candidate labelled, the replay winner a measurement", () => {
  render(<ResultSummary report={v2("1_reproduced_original")} onReport={() => undefined} />);
  expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("Original recommendation reproduced");
  expect(screen.getByText("Original recommendation")).toBeTruthy();
  expect(screen.getByText(/from the source run/)).toBeTruthy();
  expect(screen.getByText(/replay measurement, not a verification/)).toBeTruthy();
  cleanup();

  render(<ResultSummary report={v2("8_inconclusive_source_with_replay_winner")} onReport={() => undefined} />);
  expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("Re-measurement only");
  expect(screen.getByText("This replay makes no recommendation of its own.")).toBeTruthy();
  expect(screen.queryByText(/No recommendation was verified/)).toBeNull();
});

test("historical v1 replay: stored outcome kept, legacy notice outside the report in panel and summary", async () => {
  const legacy = v2("legacy_v1_replay");
  render(<ResultSummary report={legacy} onReport={() => undefined} />);
  expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("Verified recommendation");
  expect(screen.getByText("Legacy replay")).toBeTruthy();
  // one shared copy (REPLAY_OUTCOME_AUDIT §17): the summary, the report notice and the selector tag say the same thing
  expect(screen.getByRole("note", { name: "Legacy replay" }).textContent).toBe(`Legacy replay${LEGACY_COPY}`);
  cleanup();

  getReport.mockResolvedValue({ reportSchemaVersion: 1, builderVersion: "report-builder@1", manifestSha256: "f".repeat(64), report: legacy });
  renderWithQuery(<ReportPanel runId="run-1" />);
  const notice = await screen.findByRole("note", { name: "Historical replay report" });
  expect(notice.textContent).toBe(LEGACY_COPY);
  expect(notice.textContent).not.toMatch(/was reproduced|not reproduced/i);
  // outside the sealed report body
  expect(within(screen.getByRole("article", { name: "Final report" })).queryByText(LEGACY)).toBeNull();
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Verified recommendation");
});

test("no legacy notice on ordinary v1 reports or on schema-2 replays", async () => {
  render(<ResultSummary report={report()} onReport={() => undefined} />);
  expect(screen.queryByText("Legacy replay")).toBeNull();
  cleanup();
  getReport.mockResolvedValue({ reportSchemaVersion: 2, manifestSha256: "f".repeat(64), report: v2("1_reproduced_original") });
  renderWithQuery(<ReportPanel runId="run-1" />);
  expect(await screen.findByRole("article", { name: "Final report" })).toBeTruthy();
  expect(screen.queryByRole("note", { name: "Historical replay report" })).toBeNull();
  expect(screen.queryByText(/newer version than this page understands/)).toBeNull();
});

test("schema 3 still falls back to the stored markdown", async () => {
  getReport.mockResolvedValue({ reportSchemaVersion: 3, manifestSha256: "f".repeat(64), report: {} });
  renderWithQuery(<ReportPanel runId="run-1" />);
  expect(await screen.findByText(/newer version than this page understands/)).toBeTruthy();
  expect(await screen.findByText("# Stored markdown body")).toBeTruthy();
});

test("a schema-2 replay page has no empty problem or hypotheses sections and does not repeat its title", () => {
  render(<ReportView report={v2("2_performance_drift")} />);
  expect(screen.queryByRole("region", { name: "Hypotheses" })).toBeNull();
  expect(screen.queryByRole("region", { name: "Observed problem" })).toBeNull();
  expect(screen.getByText(/^Correctness held, but the speed-up changed/)).toBeTruthy();
});

/** Body headings and the contents list must number the same visible sections 01..N (no 00, no gaps). */
function numbering(container: HTMLElement) {
  const body = [...container.querySelectorAll("article section > h2")].map((h) => ({
    n: h.querySelector("span")?.textContent ?? "",
    title: (h.textContent ?? "").replace(/^\d+/, ""),
  }));
  const toc = [...container.querySelectorAll("nav[aria-label='Report contents'] li a")].map((a) => ({
    n: a.querySelector("span")?.textContent ?? "",
    title: (a.textContent ?? "").replace(/^\d+/, ""),
  }));
  return { body, toc };
}

const ev = { id: "ev_0123456789ab", kind: "plan_node", summary: "Seq scan on orders", provenance: "measured" };
const hyp = { key: "h1", category: "missing_index", confidence: "high", statement: "No index.", supportingEvidence: ["ev_0123456789ab"] };
const NUMBERING_CASES: [string, ReportV1][] = [
  ...(Object.keys(v2fixtures).filter((k) => k !== "_note") as V2Name[]).map((k) => [k, v2(k)] as [string, ReportV1]),
  ["v1 verified", report()],
  ["v1 no rounds, missing evidence", report({ rounds: [], missing: [{ section: "rounds", reason: "not benchmarked" }] }, "unverified")],
  ["v2 replay with problem evidence", { ...v2("2_performance_drift"), problem: { evidence: [ev], materiality: null } } as unknown as ReportV1],
  ["v2 replay with materiality only", { ...v2("2_performance_drift"), problem: { evidence: [], materiality: { verdict: "material", reasons: [], evidenceIds: [] } } } as unknown as ReportV1],
  ["v2 replay with hypotheses", { ...v2("1_reproduced_original"), hypotheses: [hyp] } as unknown as ReportV1],
  ["v2 replay without rounds or comparison", { ...v2("2_performance_drift"), rounds: [], replay: null, missing: [] } as unknown as ReportV1],
];

test.each(NUMBERING_CASES)("section numbering is sequential and matches the contents list: %s", (_name, r) => {
  const { container } = render(<ReportView report={r} toc />);
  const { body, toc } = numbering(container);
  expect(body.length).toBeGreaterThan(0);
  expect(body.map((s) => s.n)).toEqual(body.map((_, i) => String(i + 1).padStart(2, "0")));
  expect(toc).toEqual(body);
});

test("reproduced replay: candidate and verification scope lead; source IDs and digests are secondary but complete", () => {
  render(<ReportView report={v2("1_reproduced_original")} />);
  const original = screen.getByRole("region", { name: "Original recommendation" });
  const text = original.textContent ?? "";
  // primary: what the candidate is and what its verification covers
  expect(within(original).getByRole("heading", { level: 3 }).textContent).toMatch(/Index on orders \(customer_id\)/);
  expect(within(original).getByText(/Verified in the sandbox by the source investigation and reproduced by this replay/)).toBeTruthy();
  // secondary, after the primary content, nothing truncated
  const details = within(original).getByRole("list", { name: "Source details" });
  for (const value of ["00000000-0000-4000-8000-0000000000bb", "00000000-0000-4000-8000-0000000000e1", "ev_777777777777", "5a".repeat(32)]) {
    expect(details.textContent).toContain(value);
  }
  expect(text.indexOf("Verified in the sandbox")).toBeLessThan(text.indexOf("00000000-0000-4000-8000-0000000000bb"));

  const result = screen.getByRole("region", { name: "Experiment replay result" });
  const resultDetails = within(result).getByRole("list", { name: "Source details" });
  for (const value of ["00000000-0000-4000-8000-0000000000bb", "verified_recommendation", "report-builder@1", "reproduced_source_recommendation", "1".repeat(64), "2".repeat(64)]) {
    expect(resultDetails.textContent).toContain(value);
  }
  // the lead sentence carries no IDs
  expect(within(result).getByText(/^Re-measured one experiment of the original investigation/).textContent).not.toMatch(/[0-9a-f]{8}/);
});
