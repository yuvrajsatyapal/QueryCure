import { afterEach, expect, test, vi } from "vitest";
import { cleanup, screen, within } from "@testing-library/react";
import { CommandProvider } from "@/components/command/CommandProvider";
import { moving } from "@/test/motion";
import { renderWithQuery } from "@/test/render";
import { SideNav } from "../SideNav";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }), usePathname: () => "/app" }));

const { items } = vi.hoisted(() => ({ items: [] as unknown[] }));
vi.mock("@/lib/api/investigations", async (orig) => ({
  ...(await orig<typeof import("@/lib/api/investigations")>()),
  listInvestigations: vi.fn(async () => ({ items, nextCursor: null })),
}));

const inv = (id: string, status: string) => ({
  id,
  title: `Investigation ${id}`,
  objective: "o",
  modes: ["offline"],
  createdAt: "2026-10-19T10:00:00Z",
  latestRun: { id: `run-${id}`, investigationId: id, kind: "investigation", runNumber: 1, status, outcome: null, finalized: false, createdAt: "2026-10-19T10:00:00Z", startedAt: null, finishedAt: null },
});

const renderNav = (collapsed = false) =>
  renderWithQuery(
    <CommandProvider>
      <SideNav collapsed={collapsed} />
    </CommandProvider>,
  );

afterEach(() => {
  cleanup();
  items.length = 0;
});

test("every section is a real link (no dead or placeholder entries)", () => {
  const { container } = renderNav();

  expect(screen.getByRole("link", { name: "Dashboard" }).getAttribute("href")).toBe("/app");
  expect(screen.getByRole("link", { name: "History" }).getAttribute("href")).toBe("/app/history");
  expect(screen.getByRole("link", { name: "Settings" }).getAttribute("href")).toBe("/app/settings");
  expect(screen.getByRole("link", { name: "Demo gallery" }).getAttribute("href")).toBe("/demo");
  expect(container.querySelector("[aria-disabled]")).toBeNull();
});

test("active runs list only in-flight investigations, approvals first, with the status in words", async () => {
  items.push(inv("done", "completed"), inv("r", "running"), inv("a", "awaiting_approval"));
  renderNav();
  const list = await screen.findByRole("list", { name: "Active runs" });
  const links = within(list).getAllByRole("link");
  expect(links.map((l) => l.getAttribute("href"))).toEqual(["/app/investigations/a", "/app/investigations/r"]);
  expect(within(links[0]!).getByText("approval")).toBeDefined();
  expect(within(links[1]!).getByText("running")).toBeDefined();
});

test("a polled running entry is shown as running but never animates, expanded or collapsed", async () => {
  items.push(inv("r", "running"), inv("q", "queued"));
  const { container, unmount } = renderNav();
  const list = await screen.findByRole("list", { name: "Active runs" });
  expect(within(list).getByText("running")).toBeDefined();
  expect(moving(container)).toEqual([]);
  unmount();
  const rail = renderNav(true);
  expect(await screen.findByRole("link", { name: "Investigation r, Running" })).toBeDefined();
  expect(moving(rail.container)).toEqual([]);
});

test("the collapsed rail keeps every destination reachable by name", async () => {
  items.push(inv("r", "running"));
  renderNav(true);
  expect(screen.getByRole("link", { name: "Dashboard" })).toBeDefined();
  expect(screen.getByRole("link", { name: "New investigation" })).toBeDefined();
  expect(screen.getByRole("button", { name: "Search or jump to…" })).toBeDefined();
  expect(screen.queryByText("Workspace")).toBeNull();
  expect(await screen.findByRole("link", { name: "Investigation r, Running" })).toBeDefined();
});
