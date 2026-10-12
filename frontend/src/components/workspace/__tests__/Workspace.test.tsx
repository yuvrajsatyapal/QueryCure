import { afterEach, beforeAll, beforeEach, expect, test, vi } from "vitest";
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

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/api/investigations", () => ({
  investigationKeys: { models: ["settings", "models"] },
  createInvestigation: vi.fn(),
  getModels: vi.fn().mockResolvedValue({
    provider: "openrouter",
    model: "x/y:free",
    fallbackModel: null,
    configured: true,
  }),
}));

import { inspectPlan } from "@/lib/api/inspect";
import { createInvestigation } from "@/lib/api/investigations";
import { Workspace } from "../Workspace";

beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});
beforeEach(() => {
  vi.mocked(inspectPlan).mockReset();
  vi.mocked(createInvestigation).mockReset();
  push.mockReset();
});
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

test("graph view shows the same nodes and shares the selection with the tree", async () => {
  vi.mocked(inspectPlan).mockResolvedValue({ artifactSha256: "abc", plan, metrics });
  const user = userEvent.setup();
  renderWithQuery(<Workspace />);

  fireEvent.change(screen.getByLabelText("Plan JSON"), { target: { value: "[]" } });
  await user.click(screen.getByRole("button", { name: "Analyze plan" }));
  await user.click(await screen.findByRole("tab", { name: "Graph" }));

  expect(screen.queryByRole("treegrid")).toBeNull();
  const cards = screen.getAllByTestId("plan-node");
  expect(cards.map((c) => c.dataset.nodeId).sort()).toEqual(plan.nodes.map((n) => String(n.id)).sort());

  fireEvent.click(cards.find((c) => c.dataset.nodeId === "2")!);
  expect(screen.getByRole("region", { name: "Plan node details" }).textContent).toContain("(customer_id = 1024)");

  await user.click(screen.getByRole("tab", { name: "Tree" }));
  expect(screen.getByRole("row", { selected: true }).textContent).toContain("Seq Scan");
});

test("starting an investigation sends the uploaded plan, param sets and an idempotency key", async () => {
  vi.mocked(inspectPlan).mockResolvedValue({ artifactSha256: "abc", plan, metrics });
  vi.mocked(createInvestigation).mockResolvedValue({
    investigation: { id: "inv-1" },
    run: { id: "run-1" },
  } as Awaited<ReturnType<typeof createInvestigation>>);
  const user = userEvent.setup();
  renderWithQuery(<Workspace />);
  fireEvent.change(screen.getByLabelText("Plan JSON"), { target: { value: "[{}]" } });
  await user.click(screen.getByRole("button", { name: "Analyze plan" }));
  await screen.findByRole("treegrid");

  await user.click(screen.getByRole("button", { name: "New investigation" }));
  await user.type(screen.getByLabelText("Title"), "Slow orders page");
  await user.type(screen.getByLabelText("Parameter set 1 name"), "hot_customer");
  fireEvent.change(screen.getByLabelText("Parameter set 1 values"), { target: { value: "[1024]" } });
  await user.click(screen.getByRole("button", { name: "Start investigation" }));

  const [input, key] = vi.mocked(createInvestigation).mock.calls[0] ?? [];
  expect(input).toMatchObject({
    title: "Slow orders page",
    modes: ["offline"],
    paramSets: [{ name: "hot_customer", values: [1024] }],
    planArtifactSha256: "abc",
  });
  expect(key).toMatch(/^[0-9a-f-]{36}$/);
  expect(push).toHaveBeenCalledWith("/app/investigations/inv-1");
});

test("an invalid parameter set is explained and nothing is sent", async () => {
  const user = userEvent.setup();
  renderWithQuery(<Workspace />);

  await user.click(screen.getByRole("button", { name: "New investigation" }));
  await user.type(screen.getByLabelText("Title"), "t");
  await user.type(screen.getByLabelText("Parameter set 1 name"), "p");
  fireEvent.change(screen.getByLabelText("Parameter set 1 values"), { target: { value: "1024" } });
  await user.click(screen.getByRole("button", { name: "Start investigation" }));

  expect((await screen.findByRole("alert")).textContent).toMatch(/JSON array/);
  expect(vi.mocked(createInvestigation)).not.toHaveBeenCalled();
});
