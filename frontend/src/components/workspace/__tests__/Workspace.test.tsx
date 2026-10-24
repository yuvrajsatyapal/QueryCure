import { afterEach, beforeAll, beforeEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQuery } from "@/test/render";
import { metrics, plan } from "@/components/plan/__tests__/fixture";
import { ApiError } from "@/lib/api/client";

const WORKLOAD_SQL = "SELECT * FROM orders WHERE customer_id = $1";
vi.mock("@/lib/api/optimization", () => ({
  optimizationKeys: { workloads: ["workloads"] },
  listWorkloads: vi.fn().mockResolvedValue({
    items: [
      {
        id: "orders_ecommerce",
        name: "orders_ecommerce",
        description: "Orders",
        injectedProblem: "missing index",
        scaleFactors: [0.1],
        defaultSeed: 7,
        availability: "live",
        tables: ["orders"],
        version: 1,
        exampleQueries: [{ name: "by_customer", sql: "SELECT * FROM orders WHERE customer_id = $1", paramSets: [{ name: "hot", values: [1], edgeCase: false }] }],
      },
    ],
  }),
}));
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

import { inspectPlan, inspectSql } from "@/lib/api/inspect";
import { createInvestigation } from "@/lib/api/investigations";
import { Workspace } from "../Workspace";

const analysis = (parameterCount = 0) =>
  ({
    statementType: "select", // the API sends the lower-case statement kind
    metadata: { tables: [{ name: "orders", schemaName: null }], parameterCount, columns: [], functions: [], functionsToResolve: [], limit: 20, orderBy: [] },
    fingerprint: { digest: "d", normalizedSql: "q" },
  }) as Awaited<ReturnType<typeof inspectSql>>;

beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});
beforeEach(() => {
  vi.mocked(inspectPlan).mockReset().mockResolvedValue({ artifactSha256: "abc", plan, metrics });
  vi.mocked(inspectSql).mockReset().mockResolvedValue(analysis());
  vi.mocked(createInvestigation).mockReset().mockResolvedValue({
    investigation: { id: "inv-1" },
    run: { id: "run-1" },
  } as Awaited<ReturnType<typeof createInvestigation>>);
  push.mockReset();
});
afterEach(cleanup);

async function toPlanSource(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Check and continue" }));
  await screen.findByLabelText("Plan JSON");
}

async function analyzeUpload(user: ReturnType<typeof userEvent.setup>, raw = "[{}]") {
  fireEvent.change(screen.getByLabelText("Plan JSON"), { target: { value: raw } });
  await user.click(screen.getByRole("button", { name: "Analyze plan" }));
  await screen.findByRole("treegrid");
}

test("the SQL step checks the query with the server validator and shows what it found", async () => {
  const user = userEvent.setup();
  renderWithQuery(<Workspace />);
  expect(screen.getByRole("listitem", { current: "step" }).textContent).toContain("SQL query");

  await toPlanSource(user);

  expect(vi.mocked(inspectSql)).toHaveBeenCalledWith(expect.stringContaining("FROM orders"));
  expect(screen.getByRole("listitem", { current: "step" }).textContent).toContain("Plan source");
  // The finished step keeps a summary and focus moves to the newly opened step.
  expect(screen.getByText(/SELECT · orders · 0 parameters/)).toBeDefined();
  expect(document.activeElement?.textContent).toContain("Plan source");
});

test("a query the validator refuses keeps the SQL step open with the API's message", async () => {
  vi.mocked(inspectSql).mockRejectedValue(new ApiError("SQL_NOT_ALLOWED", "Only SELECT statements are allowed.", 422, [], null));
  const user = userEvent.setup();
  renderWithQuery(<Workspace />);

  await user.click(screen.getByRole("button", { name: "Check and continue" }));

  expect((await screen.findByRole("alert")).textContent).toContain("Only SELECT statements are allowed.");
  expect(screen.getByRole("listitem", { current: "step" }).textContent).toContain("SQL query");
  expect(screen.queryByLabelText("Plan JSON")).toBeNull();
});

test("analyzing a pasted plan renders the tree; node selection and the graph share state", async () => {
  const user = userEvent.setup();
  renderWithQuery(<Workspace />);
  await toPlanSource(user);
  await analyzeUpload(user, '[{"Plan": {"Node Type": "Limit"}}]');

  expect(vi.mocked(inspectPlan)).toHaveBeenCalledWith('[{"Plan": {"Node Type": "Limit"}}]');
  expect(screen.getByText("hottest")).toBeDefined();
  await user.click(screen.getByText("Seq Scan"));
  expect(screen.getByRole("region", { name: "Plan node details" }).textContent).toContain("(customer_id = 1024)");

  await user.click(screen.getByRole("tab", { name: "Graph" }));
  expect(screen.queryByRole("treegrid")).toBeNull();
  const cards = screen.getAllByTestId("plan-node");
  expect(cards.map((c) => c.dataset.nodeId).sort()).toEqual(plan.nodes.map((n) => String(n.id)).sort());
});

test("an upload source needs an analyzed plan before it can continue", async () => {
  const user = userEvent.setup();
  renderWithQuery(<Workspace />);
  await toPlanSource(user);

  const next = screen.getByRole("button", { name: "Continue" });
  expect(next).toHaveProperty("disabled", true);
  expect(document.getElementById(next.getAttribute("aria-describedby") ?? "")?.textContent).toMatch(/Analyze a plan first/);
  // The keyboard shortcut reaches the same guard and says why.
  fireEvent.keyDown(screen.getByLabelText("Plan JSON"), { key: "Enter", ctrlKey: true, metaKey: true });
  expect(screen.getByRole("alert").textContent).toMatch(/Analyze a plan first/);
  expect(screen.getByRole("listitem", { current: "step" }).textContent).toContain("Plan source");
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

test("Continue stays disabled while the plan analysis is pending and cannot advance the wizard", async () => {
  const pending = deferred<Awaited<ReturnType<typeof inspectPlan>>>();
  vi.mocked(inspectPlan).mockReturnValue(pending.promise);
  const user = userEvent.setup();
  renderWithQuery(<Workspace />);
  await toPlanSource(user);
  fireEvent.change(screen.getByLabelText("Plan JSON"), { target: { value: "[{}]" } });
  await user.click(screen.getByRole("button", { name: "Analyze plan" }));

  const next = await screen.findByRole("button", { name: "Analyzing plan…" });
  expect(next).toHaveProperty("disabled", true);
  expect(screen.getByRole("button", { name: "Analyzing…" })).toHaveProperty("disabled", true);
  await user.click(next);
  fireEvent.keyDown(screen.getByLabelText("Plan JSON"), { key: "Enter", ctrlKey: true, metaKey: true });
  expect(screen.getByRole("listitem", { current: "step" }).textContent).toContain("Plan source");
  expect(screen.queryByRole("alert")).toBeNull();
  expect(vi.mocked(inspectPlan)).toHaveBeenCalledTimes(1);

  pending.resolve({ artifactSha256: "abc", plan, metrics });
  const ready = await screen.findByRole("button", { name: "Continue" });
  await waitFor(() => expect(ready).toHaveProperty("disabled", false));
  await user.click(ready);
  expect(screen.getByRole("listitem", { current: "step" }).textContent).toContain("Investigation mode");
});

test("a failed analysis explains the error, keeps Continue disabled and can be retried", async () => {
  vi.mocked(inspectPlan).mockRejectedValueOnce(new ApiError("PLAN_INVALID", "The plan JSON is not EXPLAIN output.", 422, [], null));
  const user = userEvent.setup();
  renderWithQuery(<Workspace />);
  await toPlanSource(user);
  fireEvent.change(screen.getByLabelText("Plan JSON"), { target: { value: "[{}]" } });
  await user.click(screen.getByRole("button", { name: "Analyze plan" }));

  expect((await screen.findByRole("alert")).textContent).toContain("The plan JSON is not EXPLAIN output.");
  expect(screen.getByRole("button", { name: "Continue" })).toHaveProperty("disabled", true);
  await user.click(screen.getByRole("button", { name: "Retry analysis" }));
  await screen.findByRole("treegrid");
  expect(screen.getByRole("button", { name: "Continue" })).toHaveProperty("disabled", false);
});

test("editing the plan after it was analyzed needs a new analysis; a late response for old text does not count", async () => {
  const pending = deferred<Awaited<ReturnType<typeof inspectPlan>>>();
  const user = userEvent.setup();
  renderWithQuery(<Workspace />);
  await toPlanSource(user);
  await analyzeUpload(user, "[1]");
  expect(screen.getByRole("button", { name: "Continue" })).toHaveProperty("disabled", false);

  fireEvent.change(screen.getByLabelText("Plan JSON"), { target: { value: "[2]" } });
  const next = screen.getByRole("button", { name: "Continue" });
  expect(next).toHaveProperty("disabled", true);
  expect(document.getElementById(next.getAttribute("aria-describedby") ?? "")?.textContent).toMatch(/changed since it was analyzed/);

  // Analyze "[2]", then edit to "[3]" before the response arrives: the "[2]" result is stale.
  vi.mocked(inspectPlan).mockReturnValue(pending.promise);
  await user.click(screen.getByRole("button", { name: "Analyze plan" }));
  fireEvent.change(screen.getByLabelText("Plan JSON"), { target: { value: "[3]" } });
  pending.resolve({ artifactSha256: "def", plan, metrics });
  await waitFor(() => expect(screen.getByRole("button", { name: "Analyze plan" })).toHaveProperty("disabled", false));
  expect(screen.getByRole("button", { name: "Continue" })).toHaveProperty("disabled", true);
});

test("modes the source cannot support are disabled and say why", async () => {
  const user = userEvent.setup();
  renderWithQuery(<Workspace />);
  await toPlanSource(user);
  await analyzeUpload(user);
  await user.click(screen.getByRole("button", { name: "Continue" }));

  expect(screen.getByRole("radio", { name: /Offline/ })).toHaveProperty("checked", true);
  const live = screen.getByRole("radio", { name: /Live inspection/ });
  expect(live).toHaveProperty("disabled", true);
  expect(live.getAttribute("aria-describedby")).toBe("mode-live_inspection");
  expect(document.getElementById("mode-live_inspection")?.textContent).toBe("Choose a connection in Plan source.");
  expect(screen.getByRole("radio", { name: /Sandbox benchmark/ })).toHaveProperty("disabled", true);
});

test("a blank title starts with the deterministic suggestion, the plan, param sets and an idempotency key", async () => {
  const user = userEvent.setup();
  renderWithQuery(<Workspace />);
  await toPlanSource(user);
  await analyzeUpload(user);
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.type(screen.getByLabelText("Parameter set 1 name"), "hot_customer");
  fireEvent.change(screen.getByLabelText("Parameter set 1 values"), { target: { value: "[1024]" } });
  await user.click(screen.getByRole("button", { name: "Continue" }));

  const titleInput = screen.getByLabelText("Title");
  expect(titleInput.getAttribute("placeholder")).toBe("orders · where customer_id · order by created_at · limit 20");
  await user.click(screen.getByRole("button", { name: "Start investigation" }));

  const [input, key] = vi.mocked(createInvestigation).mock.calls[0] ?? [];
  expect(input).toMatchObject({
    title: "orders · where customer_id · order by created_at · limit 20",
    modes: ["offline"],
    paramSets: [{ name: "hot_customer", values: [1024] }],
    planArtifactSha256: "abc",
  });
  expect(input).not.toHaveProperty("connectionId");
  expect(key).toMatch(/^[0-9a-f-]{36}$/);
  expect(push).toHaveBeenCalledWith("/app/investigations/inv-1");
});

test("a typed title overrides the suggestion", async () => {
  const user = userEvent.setup();
  renderWithQuery(<Workspace />);
  await toPlanSource(user);
  await user.click(screen.getByRole("radio", { name: /No plan/ }));
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.type(screen.getByLabelText("Title"), "Slow orders page");
  await user.click(screen.getByRole("button", { name: "Start investigation" }));

  const [input] = vi.mocked(createInvestigation).mock.calls[0] ?? [];
  expect(input).toMatchObject({ title: "Slow orders page", modes: ["offline"] });
  expect(input).not.toHaveProperty("planArtifactSha256");
});

test("an invalid parameter set is explained and the mode step stays open", async () => {
  const user = userEvent.setup();
  renderWithQuery(<Workspace />);
  await toPlanSource(user);
  await user.click(screen.getByRole("radio", { name: /No plan/ }));
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.type(screen.getByLabelText("Parameter set 1 name"), "p");
  fireEvent.change(screen.getByLabelText("Parameter set 1 values"), { target: { value: "1024" } });
  await user.click(screen.getByRole("button", { name: "Continue" }));

  expect(screen.getByRole("alert").textContent).toMatch(/JSON array/);
  expect(screen.getByRole("listitem", { current: "step" }).textContent).toContain("Investigation mode");
  expect(vi.mocked(createInvestigation)).not.toHaveBeenCalled();
});

test("a workload example replaces the SQL; review checks it again and starts a sandbox run", async () => {
  const user = userEvent.setup();
  renderWithQuery(<Workspace />);
  await toPlanSource(user);
  await user.click(screen.getByRole("radio", { name: /Demo workload/ }));
  await user.selectOptions(await screen.findByLabelText("Workload"), "orders_ecommerce");

  expect(screen.getByText(/replaced with this workload's example/)).toBeDefined();
  await user.click(screen.getByRole("button", { name: "Continue" }));
  expect(screen.getByRole("radio", { name: /Sandbox benchmark/ })).toHaveProperty("checked", true);
  await user.click(screen.getByLabelText(/Pre-authorize sandbox experiments/));
  await user.click(screen.getByRole("button", { name: "Continue" }));

  await waitFor(() => expect(vi.mocked(inspectSql)).toHaveBeenLastCalledWith(WORKLOAD_SQL));
  const startButton = screen.getByRole("button", { name: "Start investigation" });
  await waitFor(() => expect(startButton).toHaveProperty("disabled", false));
  await user.click(startButton);

  const [input] = vi.mocked(createInvestigation).mock.calls[0] ?? [];
  expect(input).toMatchObject({
    title: "orders · where customer_id",
    query: WORKLOAD_SQL,
    modes: ["sandbox_benchmark"],
    workloadId: "orders_ecommerce:sf=0.1:seed=7",
    preAuthorizeDemoSandbox: true,
    paramSets: [{ name: "hot", values: [1] }],
  });
});

test("Ctrl/Cmd+Enter advances outside the SQL editor", async () => {
  const user = userEvent.setup();
  renderWithQuery(<Workspace />);
  await toPlanSource(user);
  await user.click(screen.getByRole("radio", { name: /No plan/ }));

  fireEvent.keyDown(screen.getByRole("radio", { name: /No plan/ }), { key: "Enter", ctrlKey: true, metaKey: true });

  await waitFor(() => expect(screen.getByRole("listitem", { current: "step" }).textContent).toContain("Investigation mode"));
});
