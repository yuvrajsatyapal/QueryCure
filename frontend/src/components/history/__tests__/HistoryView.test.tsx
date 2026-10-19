import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { cleanup, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQuery } from "@/test/render";

vi.mock("@/lib/api/investigations", () => ({
  listInvestigations: vi.fn(),
  deleteInvestigation: vi.fn().mockResolvedValue(undefined),
  restoreInvestigation: vi.fn().mockResolvedValue({}),
}));

import { deleteInvestigation, listInvestigations, restoreInvestigation } from "@/lib/api/investigations";
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
  expect(screen.getAllByText("unverified recommendations")).toHaveLength(2);
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
