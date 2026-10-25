import { afterEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQuery } from "@/test/render";
import { describe as describeEvent } from "@/lib/events/describe";
import type { Approval, ExperimentDetail, OptimizationCandidate, RunEvent } from "@/lib/api/types";
import { ApprovalCard } from "../ApprovalCard";
import { ExperimentView } from "../TournamentPanel";
import { VerdictBadge } from "../VerdictBadge";

const decideApproval = vi.fn();
vi.mock("@/lib/api/optimization", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  decideApproval: (...args: unknown[]) => decideApproval(...args),
}));

afterEach(() => {
  cleanup();
  decideApproval.mockReset();
});

const approval = {
  id: "ap-1",
  runId: "run-1",
  round: 0,
  kind: "sandbox_execution",
  status: "pending",
  decidedBy: null,
  decidedAt: null,
  expiresAt: "2099-10-13T10:00:00Z",
  approvedCandidateIds: [],
  comment: "",
  createdAt: "2026-10-12T10:00:00Z",
  payload: {
    schemaVersion: 1,
    workloadId: "orders_ecommerce@v1:sf=0.1:seed=42",
    sandbox: "QueryCure sandbox",
    baselineQuery: "SELECT 1",
    paramSets: [{ name: "hot", values: [1024] }],
    candidates: [
      { candidateId: "c-1", key: "oc_000000000001", kind: "create_index", ddl: ["CREATE INDEX ON orders (customer_id, created_at)"], querySql: null, sqlSha256: "x", expectedBenefit: "Avoids the sort", risks: [] },
      { candidateId: "c-2", key: "oc_000000000002", kind: "analyze_statistics", ddl: ["ANALYZE orders"], querySql: null, sqlSha256: "y", expectedBenefit: "Fresh stats", risks: ["confounds"] },
    ],
  },
} as unknown as Approval;

test("approval card shows the exact SQL before anything runs", () => {
  renderWithQuery(<ApprovalCard approval={approval} runId="run-1" />);

  const card = screen.getByRole("region", { name: "Approval required" });
  expect(within(card).getByText("CREATE INDEX ON orders (customer_id, created_at)")).toBeDefined();
  expect(within(card).getByText("ANALYZE orders")).toBeDefined();
  expect(within(card).getByText(/Nothing has run yet/)).toBeDefined();
  expect(decideApproval).not.toHaveBeenCalled();
});

test("approving everything sends approve; a subset sends partial with the ids", async () => {
  const user = userEvent.setup();
  decideApproval.mockResolvedValue({ ...approval, status: "approved" });
  renderWithQuery(<ApprovalCard approval={approval} runId="run-1" />);

  await user.click(screen.getByRole("checkbox", { name: "Include oc_000000000002" }));
  await user.click(screen.getByRole("button", { name: "Approve 1 selected" }));

  expect(decideApproval).toHaveBeenCalledWith("ap-1", { decision: "partial", candidateIds: ["c-1"] });
});

test("declining sends decline", async () => {
  const user = userEvent.setup();
  decideApproval.mockResolvedValue({ ...approval, status: "declined" });
  renderWithQuery(<ApprovalCard approval={approval} runId="run-1" />);

  await user.click(screen.getByRole("button", { name: "Decline" }));

  expect(decideApproval).toHaveBeenCalledWith("ap-1", { decision: "decline", candidateIds: [] });
});

test("verdicts are always spelled out, never colour alone", () => {
  render(
    <>
      <VerdictBadge status="verified" />
      <VerdictBadge status="rejected" />
      <VerdictBadge status="inconclusive" />
    </>,
  );

  expect(screen.getByText("Verified · tested scope")).toBeDefined();
  expect(screen.getByText("Rejected")).toBeDefined();
  expect(screen.getByText("Inconclusive")).toBeDefined();
});

const summary = (median: number, n = 30) => ({
  n,
  medianNs: median,
  p95Ns: n >= 20 ? median * 1.2 : null,
  minNs: median,
  maxNs: median,
  iqrNs: 1,
  cv: 0.1,
  robustCv: 0.05,
});
const detail = {
  id: "ex-1",
  runId: "run-1",
  round: 0,
  kind: "tournament",
  status: "completed",
  engineVersion: "bench@1",
  rowProfile: "qc-row-v1",
  environmentDigest: "abcdef0123456789",
  startedAt: null,
  finishedAt: null,
  winner: "oc_000000000001",
  errorCode: null,
  environment: { pgVersion: "170011", cpuArch: "arm64" },
  config: { paramSets: [{ name: "hot" }] },
  blocks: [],
  provenance: "measured",
  result: {
    schemaVersion: 1,
    experimentId: "ex-1",
    engineVersion: "bench@1",
    environmentDigest: "abcdef",
    builds: [
      { arm: "oc_000000000001", ok: true, reason: null, detail: "", indexSizeBytes: 2_400_000, buildNs: 1 },
      { arm: "oc_000000000002", ok: true, reason: null, detail: "", indexSizeBytes: 0, buildNs: 1 },
    ],
    measurements: [],
    stats: [
      { arm: "oc_000000000001", paramSet: "hot", baseline: summary(4_400_000), candidate: summary(700_000, 12), speedup: 6.29, ciLow: 5.1, ciHigh: 7.0 },
    ],
    verdicts: [
      { arm: "oc_000000000001", verdict: "verified", reasons: [], gate: null },
      { arm: "oc_000000000002", verdict: "rejected", reasons: [{ code: "no_improvement", detail: "CI below 1" }], gate: 6 },
    ],
    tournament: [
      { arm: "oc_000000000001", rank: 1, verdict: "verified", primaryCiLow: 5.1 },
      { arm: "oc_000000000002", rank: 2, verdict: "rejected", primaryCiLow: 0.9 },
    ],
    winner: "oc_000000000001",
    orderIsTotal: false,
    provenance: "measured",
  },
} as unknown as ExperimentDetail;
const candidates = [
  { key: "oc_000000000001", kind: "create_index", ddl: ["CREATE INDEX ON orders (customer_id, created_at)"], querySql: null, status: "verified" },
  { key: "oc_000000000002", kind: "analyze_statistics", ddl: ["ANALYZE orders"], querySql: null, status: "rejected" },
] as unknown as OptimizationCandidate[];

test("tournament ranks candidates and compares the winner against the baseline", () => {
  renderWithQuery(<ExperimentView detail={detail} candidates={candidates} />);
  // The full tables sit behind a toggle; the studio above them is the default view.
  expect(screen.queryByRole("table", { name: "Optimization tournament" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Show data tables" }));

  const table = screen.getByRole("table", { name: "Optimization tournament" });
  const [first, second] = within(table).getAllByRole("row").slice(1) as [HTMLElement, HTMLElement];
  expect(within(first).getByText("Winner")).toBeDefined();
  expect(within(second).getByText("no_improvement")).toBeDefined();
  expect(within(first).getByText("2.3 MB")).toBeDefined();
  const comparison = screen.getByRole("table", { name: /Baseline versus candidate/ });
  expect(within(comparison).getByText(/6\.29×/)).toBeDefined();
  expect(within(comparison).getByText(/n\/a \(n<20\)/)).toBeDefined(); // p95 suppressed for n=12
  expect(screen.getByRole("img", { name: /speedup 6\.29×, 95% CI 5\.10× to 7\.00×/ })).toBeDefined();
  expect(screen.getByText(/Measured in the sandbox/)).toBeDefined();
  expect(screen.getByText(/not as a production guarantee/)).toBeDefined();
});

test("timeline describes optimization events in words", () => {
  const event = (type: string, payload: object) => ({ runId: "r", seq: 1, ts: "", type, payload }) as RunEvent;

  expect(describeEvent(event("approval.requested", { status: "pending", round: 0 })).text).toBe(
    "Approval needed for round 1",
  );
  expect(describeEvent(event("benchmark.progress", { state: "measuring", block: 3, blocksTotal: 12 })).text).toBe(
    "Benchmark measuring · block 3/12",
  );
  const verdict = describeEvent(
    event("verification.completed", { candidateKey: "oc_1", verdict: "rejected", reasons: [{ code: "regression" }] }),
  );
  expect(verdict).toEqual({ text: "oc_1: rejected (regression)", tone: "error" });
});

test("a noise-warning verification is labelled as such, never as plain verified", () => {
  render(<VerdictBadge status="verified_with_noise_warning" />);

  expect(screen.getByText("Verified · noise warning, 3 runs agree")).toBeDefined();
  expect(screen.queryByText("Verified · tested scope")).toBeNull();
});

test("approval card offers no decision once the expiry time has passed", () => {
  renderWithQuery(<ApprovalCard approval={{ ...approval, expiresAt: "2020-01-01T00:00:00Z" }} runId="run-1" />);
  expect(screen.getByText(/expiry time passed; no decision can be recorded/)).toBeTruthy();
  expect((screen.getByRole("button", { name: "Approve and run" }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole("button", { name: "Decline" }) as HTMLButtonElement).disabled).toBe(true);
});

test("approval card says a noisy result may be re-measured", () => {
  renderWithQuery(<ApprovalCard approval={approval} runId="run-1" />);

  expect(screen.getByText(/may be re-measured up to two more times/)).toBeDefined();
});

test("a replicated round shows the replication verdict, its range and every replicate", () => {
  const noisy = {
    ...detail,
    winner: null,
    replicate: 0,
    replication: {
      schemaVersion: 1,
      engineVersion: "bench@2",
      sourceExperimentId: "ex-1",
      replicatesRequired: 3,
      winner: "oc_000000000001",
      verdicts: [
        {
          arm: "oc_000000000001",
          verdict: "verified_with_noise_warning",
          reasons: [{ code: "insufficient_evidence", detail: "sample dispersion exceeded max_cv (robust CV up to 0.66); verified by agreement of 3 independent experiments" }],
          experimentIds: ["ex-1", "ex-2", "ex-3"],
          primaryParamSet: "hot",
          ciLow: 43.7,
          ciHigh: 67.4,
          maxRobustCv: 0.66,
        },
      ],
    },
    result: {
      ...(detail.result as object),
      winner: null,
      verdicts: [
        { arm: "oc_000000000001", verdict: "inconclusive", reasons: [{ code: "insufficient_evidence", detail: "hot: candidate robust CV 0.46 > 0.25" }], gate: 4 },
        { arm: "oc_000000000002", verdict: "rejected", reasons: [{ code: "no_improvement", detail: "CI below 1" }], gate: 6 },
      ],
    },
  } as unknown as ExperimentDetail;

  renderWithQuery(<ExperimentView detail={noisy} candidates={candidates} />);
  fireEvent.click(screen.getByRole("button", { name: "Show data tables" }));

  const table = screen.getByRole("table", { name: "Optimization tournament" });
  const first = within(table).getAllByRole("row")[1] as HTMLElement;
  expect(within(first).getByText("Verified · noise warning, 3 runs agree")).toBeDefined();
  expect(within(first).getByText("Winner")).toBeDefined();
  const note = screen.getByRole("region", { name: "Independent replication" });
  expect(within(note).getByText(/43\.7× – 67\.4×/)).toBeDefined();
  expect(within(note).getByText(/across 3 independent experiments/)).toBeDefined();
});

// Workstream 3: a plan diff chosen in the command palette (UI_UX §3.15).
const withPlans = {
  ...detail,
  blocks: [
    { arm: "baseline", phase: "plan", paramSet: "hot", planSha256: "base" },
    { arm: "oc_000000000001", phase: "plan", paramSet: "hot", planSha256: "c1" },
    { arm: "oc_000000000002", phase: "plan", paramSet: "hot", planSha256: "c2" },
  ],
} as unknown as ExperimentDetail;

test("focusSection selects the arm and focuses its candidate picker, then reports done once", async () => {
  const done = vi.fn();
  renderWithQuery(
    <ExperimentView detail={withPlans} candidates={candidates} runId="run-1" focusSection={{ section: "plan-diff", arm: "oc_000000000002" }} onFocusDone={done} />,
  );
  const picker = screen.getByRole("combobox", { name: "Candidate" }) as HTMLSelectElement;
  expect(picker.value).toBe("oc_000000000002");
  await vi.waitFor(() => expect(document.activeElement).toBe(picker));
  expect(done).toHaveBeenCalledTimes(1);
});

test("focusSection for an arm without a captured plan focuses nothing and still reports done", async () => {
  const done = vi.fn();
  renderWithQuery(<ExperimentView detail={detail} candidates={candidates} runId="run-1" focusSection={{ section: "plan-diff", arm: "oc_000000000001" }} onFocusDone={done} />);
  await vi.waitFor(() => expect(done).toHaveBeenCalledTimes(1));
  expect(screen.queryByRole("region", { name: "Plan diff" })).toBeNull();
});

test("a plan-diff jump by keyboard keeps the focus ring; by pointer it focuses without one, until focus leaves", async () => {
  const done = vi.fn();
  const view = renderWithQuery(
    <ExperimentView detail={withPlans} candidates={candidates} runId="run-1" focusSection={{ section: "plan-diff", arm: "oc_000000000002", via: "keyboard" }} onFocusDone={done} />,
  );
  const picker = screen.getByRole("combobox", { name: "Candidate" });
  await vi.waitFor(() => expect(document.activeElement).toBe(picker));
  expect(picker.hasAttribute("data-pointer-focus")).toBe(false);
  view.unmount();

  renderWithQuery(
    <ExperimentView detail={withPlans} candidates={candidates} runId="run-1" focusSection={{ section: "plan-diff", arm: "oc_000000000002", via: "pointer" }} onFocusDone={done} />,
  );
  const again = screen.getByRole("combobox", { name: "Candidate" });
  await vi.waitFor(() => expect(document.activeElement).toBe(again));
  expect(again.hasAttribute("data-pointer-focus")).toBe(true);
  again.blur();
  expect(again.hasAttribute("data-pointer-focus")).toBe(false);
});
