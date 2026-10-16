import { afterEach, beforeAll, expect, test, vi } from "vitest";
import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQuery } from "@/test/render";
import { metrics, plan } from "@/components/plan/__tests__/fixture";
import type { RunEvent } from "@/lib/api/types";

const events: RunEvent[] = [
  { runId: "run-1", seq: 1, ts: "2026-10-12T10:00:00.000Z", type: "run.status_changed", payload: { from: null, to: "queued" } },
  { runId: "run-1", seq: 2, ts: "2026-10-12T10:00:01.000Z", type: "agent.summary", payload: { agent: "query_analyzer", text: "Seq Scan dominates." } },
  { runId: "run-1", seq: 3, ts: "2026-10-12T10:00:02.000Z", type: "error", payload: { node: "index_strategist", code: "AGENT_FAILED", message: "no output" } },
] as RunEvent[];

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }) }));
vi.mock("@/lib/events/useRunEvents", () => ({ useRunEvents: () => ({ events, live: true }) }));
vi.mock("@/lib/api/investigations", () => ({
  investigationKeys: {
    detail: (id: string) => ["investigations", id],
    run: (id: string) => ["runs", id],
    findings: (id: string) => ["runs", id, "findings"],
    plans: (id: string) => ["runs", id, "plans"],
    evidence: (id: string, e: string) => ["runs", id, "evidence", e],
  },
  getInvestigation: vi.fn().mockResolvedValue({
    id: "inv-1",
    title: "Slow orders page",
    objective: "Why?",
    modes: ["offline"],
    latestRun: { id: "run-1" },
    runs: [],
  }),
  getRun: vi.fn().mockResolvedValue({
    id: "run-1",
    runNumber: 1,
    status: "running",
    outcome: null,
    budget: { llmCalls: 40, totalTokens: 400000, toolCalls: 80, toolCallsPerAgent: 8, wallClockSeconds: 1200 },
    usage: { llmCalls: 3, inputTokens: 1000, outputTokens: 200 },
    llmProvider: "openrouter",
    llmModel: "nvidia/nemotron-3-super-120b-a12b:free",
    errorCode: null,
  }),
  getFindings: vi.fn().mockResolvedValue({
    hypotheses: [
      {
        key: "hy_1",
        rank: 1,
        statement: "A composite index on (customer_id, created_at) is missing.",
        category: "missing_index",
        supportingEvidence: ["ev_aaaaaaaaaaaa"],
        contradictingEvidence: [],
        confidence: "high",
        uncertaintyNotes: "not benchmarked",
        verificationMethod: "benchmark",
        proposedBy: ["index_strategist"],
      },
    ],
    findings: [
      { key: "fd_1", agent: "query_analyzer", title: "Seq Scan dominates", detail: "d", severity: "high", evidenceIds: ["ev_aaaaaaaaaaaa"] },
    ],
  }),
  getRunPlans: vi.fn().mockResolvedValue({
    items: [{ sha256: "planSHA", kind: "plan_analyze", role: "input.plan", plan, metrics }],
  }),
  getEvidence: vi.fn().mockResolvedValue({
    evidence: { id: "ev_aaaaaaaaaaaa", kind: "plan_node", locator: "/0/Plan/Plans/0/Plans/0", summary: "Seq Scan on orders", data: { nodeId: 2 }, provenance: "imported", artifactSha256: "planSHA" },
    artifact: { sha256: "planSHA", kind: "plan_analyze" },
    citedByFindings: ["fd_1"],
    citedByHypotheses: ["hy_1"],
  }),
  cancelRun: vi.fn(),
}));

import { InvestigationView } from "../InvestigationView";

beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});
afterEach(cleanup);

test("hypotheses are shown as unverified claims with their evidence", async () => {
  renderWithQuery(<InvestigationView id="inv-1" />);

  expect(await screen.findByText(/composite index on \(customer_id, created_at\)/)).toBeDefined();
  expect(screen.getByText(/Hypothesis · high · unverified/)).toBeDefined();
  expect(screen.getAllByRole("button", { name: "Evidence ev_aaaaaaaaaaaa" }).length).toBe(2);
});

test("an evidence chip opens the Plan tab with the cited node selected", async () => {
  const user = userEvent.setup();
  renderWithQuery(<InvestigationView id="inv-1" />);

  const [chip] = await screen.findAllByRole("button", { name: "Evidence ev_aaaaaaaaaaaa" });
  await user.click(chip!);

  expect(screen.getByRole("tab", { name: "Plan" }).getAttribute("aria-selected")).toBe("true");
  const selected = within(await screen.findByRole("treegrid"))
    .getAllByRole("row")
    .filter((r) => r.getAttribute("aria-selected") === "true");
  expect(selected).toHaveLength(1);
  expect(selected[0]?.textContent).toMatch(/Seq Scan/);
  expect(screen.getByLabelText("Selected evidence").textContent).toMatch(/Seq Scan on orders/);
});

test("the timeline states events in words, errors included", async () => {
  renderWithQuery(<InvestigationView id="inv-1" />);

  const timeline = await screen.findByRole("region", { name: "Agent timeline" });
  expect(within(timeline).getByText("query_analyzer: Seq Scan dominates.")).toBeDefined();
  expect(within(timeline).getByText(/Error in index_strategist: AGENT_FAILED/)).toBeDefined();
  expect(within(timeline).getByText("● live")).toBeDefined();
});

test("budget and model are shown, and a running run can be cancelled", async () => {
  renderWithQuery(<InvestigationView id="inv-1" />);

  expect(await screen.findByRole("button", { name: "Cancel run" })).toBeDefined();
  expect(screen.getByRole("meter", { name: "LLM calls" }).getAttribute("aria-valuenow")).toBe("3");
  expect(screen.getByText(/nemotron-3-super-120b-a12b:free via openrouter/)).toBeDefined();
});
