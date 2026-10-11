import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQuery } from "@/test/render";
import { metrics, plan } from "@/components/plan/__tests__/fixture";

vi.mock("@/lib/api/inspect", () => ({
  inspectPlan: vi.fn(),
  inspectSql: vi.fn(),
}));
vi.mock("@/lib/api/connections", () => ({
  connectionKeys: { all: ["connections"] },
  listConnections: vi.fn().mockResolvedValue({ items: [], nextCursor: null }),
  explainOnConnection: vi.fn(),
}));

import { inspectPlan } from "@/lib/api/inspect";
import { Workspace } from "../Workspace";

beforeEach(() => vi.mocked(inspectPlan).mockReset());
afterEach(cleanup);

test("pasting a plan and analyzing it renders the tree from the API response", async () => {
  vi.mocked(inspectPlan).mockResolvedValue({ artifactSha256: "abc", plan, metrics });
  const user = userEvent.setup();
  renderWithQuery(<Workspace />);
  const raw = '[{"Plan": {"Node Type": "Limit"}}]';

  fireEvent.change(screen.getByLabelText("Plan JSON"), { target: { value: raw } });
  await user.click(screen.getByRole("button", { name: "Analyze plan" }));

  expect(vi.mocked(inspectPlan)).toHaveBeenCalledWith(raw);
  expect(await screen.findByRole("treegrid")).toBeDefined();
  expect(screen.getByText("hottest")).toBeDefined();
});

test("selecting a node shows its details", async () => {
  vi.mocked(inspectPlan).mockResolvedValue({ artifactSha256: "abc", plan, metrics });
  const user = userEvent.setup();
  renderWithQuery(<Workspace />);

  fireEvent.change(screen.getByLabelText("Plan JSON"), { target: { value: "[]" } });
  await user.click(screen.getByRole("button", { name: "Analyze plan" }));
  await user.click(await screen.findByText("Seq Scan"));

  const details = screen.getByRole("region", { name: "Plan node details" });
  expect(details.textContent).toContain("(customer_id = 1024)");
  expect(details.textContent).toContain("995,000");
});

test("investigations are clearly not available yet", () => {
  renderWithQuery(<Workspace />);

  const start = screen.getByRole("button", { name: /Start investigation/ });
  expect(start.hasAttribute("disabled")).toBe(true);
  expect(screen.getByText(/arrive in Phase 2/)).toBeDefined();
});
