import { afterEach, expect, test, vi } from "vitest";
import { cleanup, screen, within } from "@testing-library/react";
import { renderWithQuery } from "@/test/render";
import { DashboardView } from "../DashboardView";

const { page } = vi.hoisted(() => ({
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
}));

vi.mock("@/lib/api/investigations", () => ({
  listInvestigations: vi.fn(async ({ status }: { status?: string }) => {
    switch (status) {
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
}));

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
