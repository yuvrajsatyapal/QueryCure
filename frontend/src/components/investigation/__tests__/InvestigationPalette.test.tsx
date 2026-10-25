import { afterEach, beforeAll, beforeEach, expect, test, vi } from "vitest";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useState } from "react";
import { renderWithQuery } from "@/test/render";
import { metrics, plan } from "@/components/plan/__tests__/fixture";
import type { ExperimentDetail, FindingsResponse } from "@/lib/api/types";

/** Workstream 3 (UI_UX §3.15): ⌘K on an investigation page searches the selected run first. */

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }), usePathname: () => "/app" }));
vi.mock("@/lib/events/useRunEvents", () => ({ useRunEvents: () => ({ events: [], live: false }) }));

const findingsFor: Record<string, FindingsResponse> = {
  "run-1": {
    hypotheses: [
      {
        key: "hy_1",
        rank: 1,
        statement: "A composite index on (customer_id, created_at) is missing.",
        category: "missing_index",
        supportingEvidence: ["ev_aaaaaaaaaaaa"],
        contradictingEvidence: [],
        confidence: "high",
        uncertaintyNotes: "",
        verificationMethod: "benchmark",
        proposedBy: ["index_strategist"],
      },
    ],
    findings: [{ key: "fd_1", agent: "query_analyzer", title: "Seq Scan dominates", detail: "d", severity: "high", evidenceIds: ["ev_aaaaaaaaaaaa"] }],
  } as FindingsResponse,
  "run-2": {
    hypotheses: [],
    findings: [{ key: "fd_2", agent: "query_analyzer", title: "Sort spills to disk", detail: "d", severity: "medium", evidenceIds: [] }],
  } as FindingsResponse,
};
const modes = { value: ["offline"] as string[] };
// Run 2's findings stay pending until a test releases them.
let releaseRun2: () => void = () => {};

vi.mock("@/lib/api/investigations", () => ({
  investigationKeys: {
    detail: (id: string) => ["investigations", id],
    list: (p: object) => ["investigations", "list", p],
    run: (id: string) => ["runs", id],
    findings: (id: string) => ["runs", id, "findings"],
    plans: (id: string) => ["runs", id, "plans"],
    evidence: (id: string, e: string) => ["runs", id, "evidence", e],
  },
  listInvestigations: vi.fn().mockResolvedValue({ items: [], nextCursor: null }),
  getInvestigation: vi.fn().mockImplementation(async () => ({
    id: "inv-1",
    title: "Slow orders page",
    objective: "Why?",
    modes: modes.value,
    latestRun: { id: "run-1" },
    runs: [
      { id: "run-1", runNumber: 1, kind: "initial", status: "completed", parentRunId: null },
      { id: "run-2", runNumber: 2, kind: "initial", status: "completed", parentRunId: null },
    ],
  })),
  getRun: vi.fn().mockImplementation(async (id: string) => ({
    id,
    runNumber: id === "run-1" ? 1 : 2,
    status: "completed",
    outcome: "verified_recommendation",
    budget: { llmCalls: 40, totalTokens: 400000, toolCalls: 80, toolCallsPerAgent: 8, wallClockSeconds: 1200 },
    usage: { llmCalls: 3, inputTokens: 1000, outputTokens: 200 },
    llmProvider: "openrouter",
    llmModel: "m",
    errorCode: null,
    errorMessage: null,
  })),
  getFindings: vi.fn().mockImplementation((id: string) =>
    id === "run-2" ? new Promise((resolve) => (releaseRun2 = () => resolve(findingsFor["run-2"]))) : Promise.resolve(findingsFor[id]),
  ),
  getRunPlans: vi.fn().mockResolvedValue({ items: [{ sha256: "planSHA", kind: "plan_analyze", role: "input.plan", plan, metrics }] }),
  getEvidence: vi.fn().mockResolvedValue({
    evidence: { id: "ev_aaaaaaaaaaaa", kind: "plan_node", locator: "/0/Plan/Plans/0/Plans/0", summary: "Seq Scan on orders", data: { nodeId: 2 }, provenance: "imported" },
    artifact: { sha256: "planSHA", kind: "plan_analyze" },
    citedByFindings: ["fd_1"],
    citedByHypotheses: ["hy_1"],
  }),
  cancelRun: vi.fn(),
}));

const experiment = {
  id: "ex-1",
  runId: "run-1",
  round: 0,
  replicate: 0,
  kind: "tournament",
  status: "completed",
  engineVersion: "bench@2",
  rowProfile: "qc-row-v1",
  environmentDigest: null,
  winner: null,
  errorCode: null,
  environment: null,
  config: { paramSets: [{ name: "hot" }] },
  provenance: "measured",
  blocks: [
    { arm: "baseline", phase: "plan", paramSet: "hot", planSha256: "base" },
    { arm: "oc_1", phase: "plan", paramSet: "hot", planSha256: "cand" },
  ],
  result: {
    builds: [],
    measurements: [],
    stats: [],
    verdicts: [{ arm: "oc_1", verdict: "verified", reasons: [], gate: null }],
    tournament: [{ arm: "oc_1", rank: 1, verdict: "verified", primaryCiLow: 2 }],
    winner: "oc_1",
  },
} as unknown as ExperimentDetail;

vi.mock("@/lib/api/optimization", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  getCandidates: vi.fn().mockResolvedValue({
    items: [{ key: "oc_1", kind: "create_index", ddl: ["CREATE INDEX ON orders (customer_id, created_at)"], querySql: null, status: "verified", addressesHypotheses: [] }],
  }),
  getApprovals: vi.fn().mockResolvedValue({ items: [] }),
  getExperiments: vi.fn().mockResolvedValue({ items: [{ id: "ex-1", round: 0, replicate: 0, status: "completed" }] }),
  getExperiment: vi.fn().mockImplementation(async () => experiment),
}));
vi.mock("@/lib/api/reports", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  getVerifications: vi.fn().mockResolvedValue({ items: [] }),
  getReport: vi.fn().mockRejectedValue(new Error("not sealed")),
  getPlanDiff: vi.fn().mockImplementation(() => new Promise(() => {})),
}));

import { getExperiment } from "@/lib/api/optimization";
import { CommandProvider } from "@/components/command/CommandProvider";
import { InvestigationView } from "../InvestigationView";

let selectRun: (id: string) => void = () => {};
function Page() {
  const [run, setRun] = useState<string | undefined>(undefined);
  useEffect(() => {
    selectRun = setRun;
  }, [setRun]);
  return <InvestigationView id="inv-1" requestedRunId={run} />;
}
const render = () =>
  renderWithQuery(
    <CommandProvider>
      <Page />
    </CommandProvider>,
  );
const openPalette = () => fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });

beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});
beforeEach(() => {
  modes.value = ["offline"];
  vi.mocked(getExperiment).mockClear();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("the palette opens scoped to the selected run and lists its findings, hypotheses and cited evidence", async () => {
  render();
  await screen.findByText("Seq Scan dominates");
  openPalette();

  expect(screen.getByRole("combobox", { name: "Search Run #1 and commands" })).toBeDefined();
  expect(within(screen.getByRole("group", { name: "Findings" })).getByRole("option", { name: /Seq Scan dominates/ })).toBeDefined();
  expect(within(screen.getByRole("group", { name: "Hypotheses" })).getByRole("option", { name: /composite index/ }).textContent).toContain("unverified");
  // Evidence is not prefetched: the cited ID is listed and says its details load when opened.
  const evidence = within(screen.getByRole("group", { name: "Evidence" })).getByRole("option", { name: /ev_aaaaaaaaaaaa/ });
  expect(evidence.textContent).toContain("Details load when opened");
  // The tab commands are still there.
  expect(screen.getByRole("option", { name: /Show Plan tab/ })).toBeDefined();
});

test("choosing a finding shows the Findings tab and moves focus to that finding", async () => {
  const user = userEvent.setup();
  render();
  await screen.findByText("Seq Scan dominates");
  fireEvent.click(screen.getByRole("tab", { name: "Plan" }));
  openPalette();
  await user.type(screen.getByRole("combobox"), "fd_1");
  await user.keyboard("{Enter}");

  expect(screen.getByRole("tab", { name: "Findings" }).getAttribute("aria-selected")).toBe("true");
  await waitFor(() => expect((document.activeElement as HTMLElement | null)?.dataset.claim).toBe("fd_1"));
});

test("choosing cited evidence opens it on the plan, as an evidence chip does", async () => {
  const user = userEvent.setup();
  render();
  await screen.findByText("Seq Scan dominates");
  openPalette();
  await user.type(screen.getByRole("combobox"), "ev_aaaa");
  // Claims citing the ID match too; the evidence item itself is in its own group.
  expect(screen.getByRole("group", { name: "Findings" })).toBeDefined();
  await user.click(within(screen.getByRole("group", { name: "Evidence" })).getByRole("option"));

  await waitFor(() => expect(screen.getByRole("tab", { name: "Plan" }).getAttribute("aria-selected")).toBe("true"));
  expect(screen.getByLabelText("Selected evidence").textContent).toMatch(/Seq Scan on orders/);
});

test("switching runs replaces the scope: the new run loads, and the old run's results never show", async () => {
  render();
  await screen.findByText("Seq Scan dominates");
  act(() => selectRun("run-2"));
  openPalette();

  expect(screen.getByRole("combobox", { name: "Search Run #2 and commands" })).toBeDefined();
  expect(screen.getByRole("status", { name: "Loading Run #2" })).toBeDefined();
  expect(screen.queryByRole("option", { name: /Seq Scan dominates/ })).toBeNull();

  await act(async () => releaseRun2());
  expect(await screen.findByRole("option", { name: /Sort spills to disk/ })).toBeDefined();
  expect(screen.queryByRole("option", { name: /Seq Scan dominates/ })).toBeNull();
});

test("sandbox runs list candidates with their recorded status, and a plan diff opens the collapsed section focused on that candidate", async () => {
  modes.value = ["sandbox_benchmark"];
  // Phone width: the studio's plan-diff section is a closed disclosure until something opens it.
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query === "(max-width: 767px)",
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
  const user = userEvent.setup();
  render();
  await screen.findByText("Seq Scan dominates");
  expect(vi.mocked(getExperiment)).not.toHaveBeenCalled();
  openPalette();

  const candidate = await within(await screen.findByRole("group", { name: "Candidates" })).findByRole("option", { name: /Composite index on orders/ });
  expect(candidate.textContent).toContain("Verified · tested scope");
  expect(candidate.textContent).not.toMatch(/×/);
  // The round's plan captures are read once, only because the palette is open.
  const diff = await within(await screen.findByRole("group", { name: "Plan diffs" })).findByRole("option", { name: /baseline → oc_1/ });
  expect(vi.mocked(getExperiment)).toHaveBeenCalledTimes(1);

  await user.click(diff);
  expect(screen.getByRole("tab", { name: "Tournament" }).getAttribute("aria-selected")).toBe("true");
  const section = await screen.findByText("Execution-plan differences");
  await waitFor(() => expect(section.closest("details")?.open).toBe(true));
  await waitFor(() => expect(document.activeElement?.textContent).toBe("Plan diff · baseline → oc_1"));
  // Chosen with the pointer: focused for assistive tech, without a lingering focus ring.
  expect(document.activeElement?.hasAttribute("data-pointer-focus")).toBe(true);
});
