import { afterEach, expect, test, vi } from "vitest";
import { cleanup, screen, within } from "@testing-library/react";
import { renderWithQuery } from "@/test/render";
import { ConnectionsView } from "../ConnectionsView";

const { conn } = vi.hoisted(() => ({
  conn: (id: string, lastTestStatus: string | null) => ({
  id,
  name: `db-${id}`,
  host: "127.0.0.1",
  port: 5432,
  dbname: "app",
  username: "inspector",
  sslmode: "disable",
  environment: "development",
  purpose: "inspection",
  hasPassword: true,
  capabilities: null,
  lastTestStatus,
  lastTestedAt: lastTestStatus ? "2026-10-19T10:00:00Z" : null,
  createdAt: "2026-10-19T09:00:00Z",
  }),
}));

vi.mock("@/lib/api/connections", () => ({
  connectionKeys: { all: ["connections"] },
  listConnections: vi.fn().mockResolvedValue({ items: [conn("a", "ok"), conn("b", "refused"), conn("c", "failed"), conn("d", null)] }),
  createConnection: vi.fn(),
  deleteConnection: vi.fn(),
  testConnection: vi.fn(),
}));

afterEach(cleanup);

test("each saved connection states its last test result in words", async () => {
  renderWithQuery(<ConnectionsView />);
  const list = await screen.findByRole("list", { name: "Saved connections" });
  const rows = within(list).getAllByRole("listitem");
  expect(rows.map((r) => within(r).getByText(/Test passed|Role refused|Test failed|Never tested/).textContent)).toEqual([
    "Test passed",
    "Role refused",
    "Test failed",
    "Never tested",
  ]);
  expect(within(rows[0]!).getByText("inspector@127.0.0.1:5432/app · tls disable")).toBeDefined();
});
