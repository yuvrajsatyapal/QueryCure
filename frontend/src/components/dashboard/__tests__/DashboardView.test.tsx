import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { cleanup, screen, within } from "@testing-library/react";
import { renderWithQuery } from "@/test/render";
import { DashboardView } from "../DashboardView";

const { page, recent, run } = vi.hoisted(() => {
  const run = (id: string, status: string, extra: Record<string, unknown> = {}) => ({
    id: `inv-${id}`,
    title: `Investigation ${id}`,
    objective: "o",
    modes: ["sandbox_benchmark"],
    createdAt: "2026-10-19T10:00:00Z",
    latestRun: {
      id: `run-${id}`,
      investigationId: `inv-${id}`,
      kind: "investigation",
      runNumber: 1,
      status,
      outcome: null,
      finalized: false,
      createdAt: "2026-10-19T10:00:00Z",
      startedAt: null,
      finishedAt: null,
      ...extra,
    },
  });
  return {
    run,
    page: (n: number, more = false) => ({
      items: Array.from({ length: n }, (_, i) => ({
        id: `inv-${n}-${i}`,
        title: `Investigation ${i}`,
        objective: "o",
        modes: ["offline"],
        createdAt: "2026-10-19T10:00:00Z",
        latestRun: null,
      })),
      nextCursor: more ? "next" : null,
    }),
    recent: { items: [] as unknown[], nextCursor: null },
  };
});

vi.mock("@/lib/api/investigations", async (orig) => ({
  ...(await orig<typeof import("@/lib/api/investigations")>()),
  listInvestigations: vi.fn(async ({ status }: { status?: string }) => {
    switch (status) {
      case undefined:
        return recent;
      case "running":
        return page(2);
      case "queued":
        return page(1);
      case "completed":
        return page(100, true);
      case "failed":
        return page(3);
      default:
        return page(0);
    }
  }),
  getRun: vi.fn(async () => ({ usage: { llmCalls: 14, toolCalls: 22 }, budget: { llmCalls: 40, toolCalls: 60 } })),
}));

vi.mock("@/lib/api/optimization", async (orig) => ({
  ...(await orig<typeof import("@/lib/api/optimization")>()),
  getApprovals: vi.fn(async () => ({
    items: [{ id: "ap", status: "pending", round: 0, expiresAt: "2999-01-01T00:00:00Z", payload: { candidates: [{}, {}, {}] } }],
  })),
}));

beforeEach(() => {
  recent.items = [];
});
afterEach(cleanup);

test("status counts are exact unless the endpoint has more, then a lower bound", async () => {
  renderWithQuery(<DashboardView />);
  const tiles = await screen.findByRole("region", { name: "Investigations by status" });
  const value = (label: string) => within(tiles).getByText(label).parentElement?.lastElementChild?.textContent;

  expect(await within(tiles).findByText("100+")).toBeDefined();
  expect(value("Running")).toBe("3");
  expect(value("Needs approval")).toBe("0");
  expect(value("Completed")).toBe("100+ (at least 100)");
  expect(value("Failed")).toBe("3");
  expect(screen.getByText(/means at least 100/)).toBeDefined();
});

test("active investigations put the approval first and show recorded usage and the approval's expiry", async () => {
  recent.items = [run("r", "running", { startedAt: "2026-10-19T10:00:00Z" }), run("done", "completed", { outcome: "verified_recommendation" }), run("a", "awaiting_approval")];
  renderWithQuery(<DashboardView />);
  const panel = await screen.findByRole("region", { name: "Active investigations" });
  const rows = await within(panel).findAllByRole("listitem");
  expect(rows).toHaveLength(2);
  expect(within(rows[0]!).getByRole("link", { name: "Investigation a" })).toBeDefined();
  expect(await within(rows[0]!).findByText("Round 1 · 3 candidates")).toBeDefined();
  expect(within(rows[0]!).getByText(/^expires in /)).toBeDefined();
  expect(within(rows[0]!).getByRole("link", { name: "Review candidates" })).toBeDefined();
  expect(await within(rows[1]!).findByRole("meter", { name: "LLM calls" })).toHaveProperty("ariaValueNow", "14");
  expect(within(rows[1]!).getByRole("meter", { name: "Tools" })).toHaveProperty("ariaValueMax", "60");
});

test("with nothing in flight the panel offers ways to start instead of an empty list", async () => {
  recent.items = [run("done", "completed", { outcome: "no_action_needed" })];
  renderWithQuery(<DashboardView />);
  const panel = await screen.findByRole("region", { name: "Active investigations" });
  expect(await within(panel).findByText(/Nothing in flight/)).toBeDefined();
  expect(within(panel).getByRole("link", { name: /Connect a database/ })).toBeDefined();
});

test("run outcomes count only concluded runs, in words with an icon", async () => {
  recent.items = [
    run("v", "completed", { outcome: "verified_recommendation" }),
    run("i", "completed", { outcome: "inconclusive" }),
    run("f", "failed"),
    run("live", "running"),
  ];
  renderWithQuery(<DashboardView />);
  const panel = await screen.findByRole("region", { name: "Run outcomes" });
  expect(await within(panel).findByText(/^3 concluded · latest run of each of the 25 most recent investigations, not a time window\./)).toBeDefined();
  // A sample of recent investigations, never presented as the 24-hour window the active panel uses.
  expect(within(panel).getByText("Sample · 25 most recent")).toBeDefined();
  expect(within(panel).queryByText(/24 h/)).toBeNull();
  expect(within(panel).getByRole("img", { name: "1 Verified recommendation, 1 Inconclusive, 1 Failed" })).toBeDefined();
});

test("when the list can't load, panels say so instead of showing empty states", async () => {
  const { listInvestigations } = await import("@/lib/api/investigations");
  vi.mocked(listInvestigations).mockRejectedValue(new Error("The metadata database is unavailable."));
  renderWithQuery(<DashboardView />);
  expect((await screen.findAllByText(/Not available while the investigation list can.t be loaded/)).length).toBe(3);
  expect(screen.queryByText(/Nothing in flight/)).toBeNull();
  expect(screen.queryByText(/Nothing investigated yet/)).toBeNull();
});
