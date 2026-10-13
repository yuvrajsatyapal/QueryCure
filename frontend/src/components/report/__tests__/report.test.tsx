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
  expect(screen.getByText("Seq Scan → Index Scan")).toBeTruthy();
});
