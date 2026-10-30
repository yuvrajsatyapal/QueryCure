import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { moving } from "@/test/motion";
import { renderWithQuery, testQueryClient } from "@/test/render";
import fixtures from "@/test/fixtures/report-v2.json";

vi.mock("@/lib/api/reports", async (orig) => ({
  ...(await orig<typeof import("@/lib/api/reports")>()),
  getReport: vi.fn(),
}));
vi.mock("@/lib/api/investigations", () => ({
  listInvestigations: vi.fn(),
  deleteInvestigation: vi.fn().mockResolvedValue(undefined),
  restoreInvestigation: vi.fn().mockResolvedValue({}),
}));

import { deleteInvestigation, listInvestigations, restoreInvestigation } from "@/lib/api/investigations";
import { getReport, reportKeys } from "@/lib/api/reports";
import { HistoryView } from "../HistoryView";

const item = (n: number) => ({
  id: `inv-${n}`,
  title: `Investigation ${n}`,
  objective: "o",
  modes: ["offline"],
  createdAt: "2026-10-12T10:00:00.000Z",
  latestRun: {
    id: `run-${n}`,
    investigationId: `inv-${n}`,
    runNumber: 1,
    kind: "initial",
    status: "completed",
    outcome: "unverified_recommendations",
    createdAt: "2026-10-12T10:00:00.000Z",
    startedAt: null,
    finishedAt: null, finalized: false,
  },
});

beforeEach(() => {
  vi.mocked(listInvestigations).mockReset();
  vi.mocked(deleteInvestigation).mockClear();
  vi.mocked(restoreInvestigation).mockClear();
});
afterEach(cleanup);

test("pages load with the cursor returned by the previous page", async () => {
  vi.mocked(listInvestigations)
    .mockResolvedValueOnce({ items: [item(1), item(2)], nextCursor: "c1" })
    .mockResolvedValueOnce({ items: [item(3)], nextCursor: null });
  const user = userEvent.setup();
  renderWithQuery(<HistoryView />);

  expect(await screen.findByText("Investigation 2")).toBeDefined();
  // Scoped to the rows: the Outcome filter also lists "unverified recommendations".
  expect(within(screen.getByRole("region", { name: "October 2026" })).getAllByText("Unverified recommendations")).toHaveLength(2);
  await user.click(screen.getByRole("button", { name: "Load more" }));

  expect(await screen.findByText("Investigation 3")).toBeDefined();
  expect(vi.mocked(listInvestigations).mock.calls[1]?.[0]).toMatchObject({ cursor: "c1" });
  expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
});

test("delete can be undone", async () => {
  vi.mocked(listInvestigations).mockResolvedValue({ items: [item(1)], nextCursor: null });
  const user = userEvent.setup();
  renderWithQuery(<HistoryView />);

  await user.click(await screen.findByRole("button", { name: "Delete Investigation 1" }));
  expect(vi.mocked(deleteInvestigation)).toHaveBeenCalledWith("inv-1");
  await user.click(await screen.findByRole("button", { name: "Undo" }));

  expect(vi.mocked(restoreInvestigation)).toHaveBeenCalledWith("inv-1");
});

test("an empty history explains itself and links to a new investigation", async () => {
  vi.mocked(listInvestigations).mockResolvedValue({ items: [], nextCursor: null });
  renderWithQuery(<HistoryView />);

  expect(await screen.findByText(/No investigations yet/)).toBeDefined();
  expect(screen.getByRole("link", { name: "Start one" }).getAttribute("href")).toBe(
    "/app/investigations/new",
  );
});

test("filters are sent to the API", async () => {
  vi.mocked(listInvestigations).mockResolvedValue({ items: [], nextCursor: null });
  const user = userEvent.setup();
  renderWithQuery(<HistoryView />);

  await user.selectOptions(screen.getByLabelText("Status"), "failed");
  await user.type(screen.getByLabelText("Search titles"), "orders");

  await vi.waitFor(() =>
    expect(vi.mocked(listInvestigations).mock.calls.at(-1)?.[0]).toMatchObject({
      q: "orders",
      status: "failed",
    }),
  );
});

test("the outcome filter is sent to the API, and Clear filters resets every filter", async () => {
  vi.mocked(listInvestigations).mockResolvedValue({ items: [], nextCursor: null });
  const user = userEvent.setup();
  renderWithQuery(<HistoryView />);

  await user.selectOptions(screen.getByLabelText("Outcome"), "no_action_needed");
  await user.selectOptions(screen.getByLabelText("Status"), "completed");
  await vi.waitFor(() =>
    expect(vi.mocked(listInvestigations).mock.calls.at(-1)?.[0]).toMatchObject({ outcome: "no_action_needed", status: "completed" }),
  );
  expect(await screen.findByText(/match these filters/)).toBeDefined();

  await user.click(screen.getByRole("button", { name: "Clear filters" }));
  await vi.waitFor(() => {
    const last = vi.mocked(listInvestigations).mock.calls.at(-1)?.[0];
    expect(last?.outcome).toBeUndefined();
    expect(last?.status).toBeUndefined();
  });
  expect(screen.queryByRole("button", { name: "Clear filters" })).toBeNull();
});

test("rows are grouped under a heading for their creation month, with the order stated", async () => {
  vi.mocked(listInvestigations).mockResolvedValue({ items: [item(1), item(2)], nextCursor: "c" });
  renderWithQuery(<HistoryView />);
  const group = await screen.findByRole("region", { name: "October 2026" });
  expect(group.querySelectorAll("li")).toHaveLength(2);
  expect(screen.getByText(/2 shown · more available · newest first/)).toBeDefined();
});

test("a row whose last snapshot says running reads Running and stays still", async () => {
  const running = { ...item(7), latestRun: { ...item(7).latestRun, status: "running", outcome: null } };
  vi.mocked(listInvestigations).mockResolvedValue({ items: [running], nextCursor: null });
  const { container } = renderWithQuery(<HistoryView />);
  const row = (await screen.findByText("Investigation 7")).closest("li")!;
  expect(within(row).getByText("Running", { selector: ".sr-only" })).toBeDefined();
  expect(moving(container)).toEqual([]);
});

const replay = (n: number, run: Record<string, unknown>) => {
  const base = item(n);
  return { ...base, latestRun: { ...base.latestRun, runNumber: 2, kind: "experiment_replay", finalized: true, outcome: "verified_recommendation", ...run } };
};
const sealed = (name: "1_reproduced_original" | "2_performance_drift" | "legacy_v1_replay") => {
  const r = fixtures[name] as unknown as { builderVersion: string; schemaVersion: number };
  return { runId: "x", builderVersion: r.builderVersion, reportSchemaVersion: r.schemaVersion, report: r };
};

test("replay rows never read as a verified recommendation from their stored outcome (REPLAY_OUTCOME_AUDIT §18.1)", async () => {
  vi.mocked(listInvestigations).mockResolvedValue({
    items: [
      replay(1, {}),
      replay(2, { outcome: "inconclusive" }),
      replay(3, { id: "run-3" }),
      replay(4, { id: "run-4", outcome: "inconclusive" }),
      replay(5, { id: "run-5" }),
      replay(6, { status: "running", outcome: null, finalized: false }),
      replay(7, { status: "failed", outcome: null }),
      replay(8, { status: "cancelled", outcome: null }),
      { ...item(9), latestRun: { ...item(9).latestRun, outcome: "verified_recommendation" } },
    ],
    nextCursor: null,
  });
  // Reports this session already loaded are used; nothing is fetched for a list row.
  const client = testQueryClient();
  client.setQueryData(reportKeys.report("run-3"), sealed("1_reproduced_original"));
  client.setQueryData(reportKeys.report("run-4"), sealed("2_performance_drift"));
  client.setQueryData(reportKeys.report("run-5"), sealed("legacy_v1_replay"));
  renderWithQuery(<HistoryView />, client);

  const rows = await screen.findAllByRole("listitem");
  const label = (title: string) => rows.find((r) => within(r).queryByText(title))?.textContent ?? "";
  expect(label("Investigation 1")).toContain("Replay completed");
  expect(label("Investigation 2")).toContain("Replay completed");
  expect(label("Investigation 3")).toContain("Original recommendation reproduced");
  expect(label("Investigation 4")).toContain("Performance drift detected");
  expect(label("Investigation 5")).toContain("Legacy replay · verified recommendation");
  expect(label("Investigation 6")).toContain("Running");
  expect(label("Investigation 7")).toContain("Replay failed");
  expect(label("Investigation 8")).toContain("Replay cancelled");
  expect(label("Investigation 9")).toContain("Verified recommendation");
  for (const n of [1, 2, 3, 4, 6, 7, 8]) expect(label(`Investigation ${n}`)).not.toMatch(/verified recommendation/i);
  expect(vi.mocked(getReport)).not.toHaveBeenCalled();
});

test("the verified filter says that replay rows match it by their stored outcome", async () => {
  vi.mocked(listInvestigations).mockResolvedValue({ items: [replay(1, {})], nextCursor: null });
  const user = userEvent.setup();
  renderWithQuery(<HistoryView />);
  await screen.findByText("Investigation 1");
  expect(screen.queryByText(/match this filter by their stored outcome/)).toBeNull();
  await user.selectOptions(screen.getByRole("combobox", { name: "Outcome" }), "verified_recommendation");
  expect(await screen.findByText(/match this filter by their stored outcome/)).toBeDefined();
});
