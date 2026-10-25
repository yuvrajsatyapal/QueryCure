import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQuery } from "@/test/render";
import type { ExperimentDetail, OptimizationCandidate, PlanDiff } from "@/lib/api/types";
import { PlanCompare } from "@/components/tournament/PlanCompare";
import { PlanDiffTable } from "../PlanDiffView";

const getPlanDiff = vi.fn();
vi.mock("@/lib/api/reports", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  getPlanDiff: (...args: unknown[]) => getPlanDiff(...args),
}));

afterEach(() => {
  cleanup();
  getPlanDiff.mockReset();
});

const d = (fromValue: number | null, toValue: number | null) => ({ fromValue, toValue, ratio: fromValue && toValue ? fromValue / toValue : null });
const none = d(null, null);
const m = (over: Record<string, ReturnType<typeof d>>) => ({
  inclusiveTimeMs: none, selfTimeMs: none, totalActualRows: none, planRows: none, actualLoops: none, totalCost: none, selfSharedBlocks: none, selfTempWrittenBlocks: none, ...over,
});
const base = { fromId: 1, toId: 1, fromLocator: "/0", toLocator: "/0", relation: null, indexFrom: null, indexTo: null, changes: [] as string[] };

const analyzed = {
  summary: {
    same: 1, changed: 0, added: 1, removed: 2, addedNodeTypes: ["Index Scan"], removedNodeTypes: ["Seq Scan", "Sort"], indexesUsedFrom: [], indexesUsedTo: ["o_idx"], newIndexesUsed: ["o_idx"],
    executionTimeMs: d(0.32, 0.04), planningTimeMs: none, rootTotalCost: d(1500, 12),
  },
  nodes: [
    { ...base, status: "same", nodeTypeFrom: "Limit", nodeTypeTo: "Limit", depth: 0, metrics: m({ totalActualRows: d(50, 50) }) },
    { ...base, status: "removed", toId: null, toLocator: null, nodeTypeFrom: "Sort", nodeTypeTo: null, depth: 1, metrics: m({ totalActualRows: d(50, null), selfTimeMs: d(0.2, null) }) },
    { ...base, status: "removed", toId: null, toLocator: null, nodeTypeFrom: "Seq Scan", nodeTypeTo: null, relation: "orders", depth: 2, metrics: m({ totalActualRows: d(1200, null) }) },
    { ...base, status: "added", fromId: null, fromLocator: null, nodeTypeFrom: null, nodeTypeTo: "Index Scan", relation: "orders", indexTo: "o_idx", depth: 1, metrics: m({ totalActualRows: d(null, 50), selfTimeMs: d(null, 0.03) }) },
  ],
} as unknown as PlanDiff;

test("side by side keeps each plan in its own column and marks one-sided nodes", () => {
  render(<PlanDiffTable diff={analyzed} />);
  const table = screen.getByRole("table", { name: /side by side/ });
  expect(within(table).getAllByText("not in candidate")).toHaveLength(2);
  expect(within(table).getByText("not in baseline")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Side by side" }).getAttribute("aria-pressed")).toBe("true");
  // Plan-capture figures carry their source; the planner cost is an estimate.
  expect(screen.getByText("One EXPLAIN ANALYZE capture after timing")).toBeTruthy();
  expect(screen.getByText("Planner estimate, cost units")).toBeTruthy();
  expect(screen.queryByRole("note")).toBeNull();
});

test("unified reads baseline → candidate in one list", async () => {
  const user = userEvent.setup();
  render(<PlanDiffTable diff={analyzed} />);
  await user.click(screen.getByRole("button", { name: "Unified" }));
  const table = screen.getByRole("table", { name: /one list/ });
  expect(within(table).getByText("1,200 → —")).toBeTruthy();
  expect(within(table).getByText("— → 50")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Unified" }).getAttribute("aria-pressed")).toBe("true");
});

test("a change marker opens the node's recorded metrics and closing returns focus to it", async () => {
  const user = userEvent.setup();
  render(<PlanDiffTable diff={analyzed} />);
  const chip = screen.getByRole("button", { name: "Sort, removed: show recorded metrics" });
  await user.click(chip);
  expect(chip.getAttribute("aria-expanded")).toBe("true");
  const panel = screen.getByRole("region", { name: "Recorded metrics · Sort" });
  // Cards and table both render; a container query shows one (jsdom has no layout).
  expect(within(panel).getAllByText("Self time")).toHaveLength(2);
  expect(within(panel).getAllByText("measured").length).toBeGreaterThan(0);
  // Unrecorded metrics are not listed as zeros.
  expect(within(panel).queryByText("Total cost")).toBeNull();
  await user.click(within(panel).getByRole("button", { name: "Close node metrics" }));
  expect(screen.queryByRole("region", { name: "Recorded metrics · Sort" })).toBeNull();
  expect(document.activeElement).toBe(chip);
});

test("the metric panel is reachable and closable by keyboard alone", async () => {
  const user = userEvent.setup();
  render(<PlanDiffTable diff={analyzed} />);
  const chip = screen.getByRole("button", { name: "Index Scan, added: show recorded metrics" });
  chip.focus();
  await user.keyboard("{Enter}");
  expect(screen.getByRole("region", { name: "Recorded metrics · Index Scan" })).toBeTruthy();
  await user.keyboard("{Enter}");
  expect(screen.queryByRole("region", { name: "Recorded metrics · Index Scan" })).toBeNull();
});

test("plans without EXPLAIN ANALYZE actuals say their rows are estimates", () => {
  const estimates = {
    summary: { ...analyzed.summary, executionTimeMs: none, rootTotalCost: d(1500, 12) },
    nodes: [{ ...base, status: "same", nodeTypeFrom: "Seq Scan", nodeTypeTo: "Seq Scan", relation: "orders", depth: 0, metrics: m({ planRows: d(1000, 1000), totalCost: d(1500, 12) }) }],
  } as unknown as PlanDiff;
  render(<PlanDiffTable diff={estimates} />);
  expect(screen.getByRole("note").textContent).toMatch(/Neither plan has EXPLAIN ANALYZE actuals/);
  expect(screen.getAllByText("~1,000")).toHaveLength(2);
  expect(screen.queryByText("Execution time")).toBeNull();
});

test("the benchmark median is shown beside, and labelled apart from, the plan capture", () => {
  render(<PlanDiffTable diff={analyzed} benchmark={{ baselineNs: 4_100_000, candidateNs: 310_000, nBaseline: 30, nCandidate: 30 }} />);
  const card = screen.getByRole("group", { name: "Benchmark median" });
  expect(within(card).getByText("4.10 ms")).toBeTruthy();
  expect(within(card).getByText("0.31 ms")).toBeTruthy();
  expect(within(card).getByText("measured")).toBeTruthy();
  expect(within(card).getByText(/n 30 \/ 30; this decides the verdict/)).toBeTruthy();
  // Recorded medians only: no speed-up or percentage is derived on the card.
  expect(card.textContent).not.toMatch(/×|%|faster|slower/);
});

test("each summary figure is a card: title and source tag, labelled baseline and candidate values, then its source", () => {
  render(<PlanDiffTable diff={analyzed} benchmark={{ baselineNs: 4_100_000, candidateNs: 310_000, nBaseline: 30, nCandidate: 30 }} />);
  const expected: [string, string, string, string][] = [
    ["Benchmark median", "measured", "4.10 ms", "0.31 ms"],
    ["Execution time", "measured", "0.32 ms", "0.04 ms"],
    ["Root cost", "estimate", "1,500.00", "12.00"],
  ];
  for (const [title, kind, from, to] of expected) {
    const card = screen.getByRole("group", { name: title });
    expect(within(card).getByText(kind)).toBeTruthy();
    const terms = within(card).getAllByRole("term").map((t) => t.textContent);
    expect(terms).toEqual(["Baseline", "Candidate"]);
    const values = within(card).getAllByRole("definition");
    expect(values.map((v) => v.textContent)).toEqual([from, to]);
    // Number and unit stay on one line; figures use tabular numerals.
    for (const v of values) expect(v.className).toMatch(/whitespace-nowrap.*tabular-nums|tabular-nums.*whitespace-nowrap/);
    // Values wrap as whole columns (candidate under baseline) rather than being clipped.
    expect(values[0]?.parentElement?.parentElement?.className).toContain("flex-wrap");
  }
  // Card heights are never fixed, so long descriptions are not cut off.
  for (const card of screen.getAllByRole("group")) expect(card.className).not.toMatch(/\bh-\d|max-h|line-clamp|truncate|overflow-hidden/);
});

test("the figure grid follows the diff's own width, not the viewport: one card per row, two from 33 rem", () => {
  render(<PlanDiffTable diff={analyzed} />);
  const grid = screen.getByRole("group", { name: "Execution time" }).parentElement as HTMLElement;
  expect(grid.className).toContain("grid-cols-1");
  expect(grid.className).toContain("@[33rem]/diff:grid-cols-2");
  expect(grid.className).not.toMatch(/(^|\s)(sm|md|lg|xl):/);
  expect(grid.closest(".\\@container\\/diff")).toBeTruthy();
});

test("the change summary may break an index name after an underscore without changing its text", () => {
  const diff = { ...analyzed, summary: { ...analyzed.summary, newIndexesUsed: ["orders_customer_id_created_at_idx"] } } as PlanDiff;
  render(<PlanDiffTable diff={diff} />);
  const summary = screen.getByText((_, el) => el?.tagName === "SPAN" && el.textContent === "Seq Scan, Sort removed; Index Scan added; new index used: orders_customer_id_created_at_idx");
  expect(summary.querySelectorAll("wbr")).toHaveLength(5);
});

test("a long index name is truncated in the row and given in full in the node panel", async () => {
  const user = userEvent.setup();
  const long = "idx_orders_customer_id_created_at_status_including_total_amount";
  const diff = {
    ...analyzed,
    nodes: [{ ...base, status: "added", fromId: null, fromLocator: null, nodeTypeFrom: null, nodeTypeTo: "Index Scan", relation: "orders", indexTo: long, depth: 0, metrics: m({ selfTimeMs: d(null, 0.03) }) }],
  } as unknown as PlanDiff;
  render(<PlanDiffTable diff={diff} />);
  const where = screen.getByTitle(`orders · ${long}`);
  expect(where.className).toContain("truncate");
  await user.click(screen.getByRole("button", { name: "Index Scan, added: show recorded metrics" }));
  const panel = screen.getByRole("region", { name: "Recorded metrics · Index Scan" });
  expect(within(panel).getByText(`none → ${long}`)).toBeTruthy();
  expect(within(panel).getByText("orders")).toBeTruthy();
});

test("node metrics are stacked cards for narrow panels, with every value and its source", async () => {
  const user = userEvent.setup();
  render(<PlanDiffTable diff={analyzed} />);
  await user.click(screen.getByRole("button", { name: "Sort, removed: show recorded metrics" }));
  const cards = screen.getByRole("list", { name: "Recorded metrics for Sort" });
  const self = within(cards).getByText("Self time").closest("li") as HTMLElement;
  expect(within(self).getByText("Baseline")).toBeTruthy();
  expect(within(self).getByText("0.20 ms")).toBeTruthy();
  expect(within(self).getByText("Candidate")).toBeTruthy();
  expect(within(self).getByText("measured")).toBeTruthy();
  // The table is still rendered for wider panels (shown by a container query).
  expect(screen.getByRole("region", { name: "Metric table · Sort" }).className).toContain("@md/metrics:block");
});

const candidate = (key: string, ddl: string) =>
  ({ id: key, key, kind: "create_index", ddl: [ddl], querySql: null }) as unknown as OptimizationCandidate;
const sha = (c: string) => c.repeat(64);
const block = (arm: string, paramSet: string, planSha256: string | null) => ({ arm, paramSet, phase: "plan", planSha256, block: 0, latenciesNs: [] });
const detail = (blocks: ReturnType<typeof block>[]) =>
  ({
    id: "exp-1",
    blocks,
    result: {
      stats: [{ arm: "oc_a", paramSet: "hot", speedup: 10, ciLow: 8, ciHigh: 12, baseline: { medianNs: 4_000_000, n: 30 }, candidate: { medianNs: 400_000, n: 30 } }],
    },
  }) as unknown as ExperimentDetail;

test("PlanCompare picks candidate and parameter set, and asks for the matching plans", async () => {
  const user = userEvent.setup();
  getPlanDiff.mockResolvedValue({ runId: "run-1", fromSha256: sha("a"), toSha256: sha("b"), diff: analyzed });
  const onSelectArm = vi.fn();
  renderWithQuery(
    <PlanCompare
      runId="run-1"
      detail={detail([block("baseline", "hot", sha("a")), block("baseline", "cold", sha("c")), block("oc_a", "hot", sha("b")), block("oc_a", "cold", sha("d")), block("oc_b", "hot", sha("e"))])}
      candidates={[candidate("oc_a", "CREATE INDEX ON orders (customer_id)"), candidate("oc_b", "CREATE INDEX ON orders (created_at)")]}
      arm="oc_a"
      onSelectArm={onSelectArm}
      compact={false}
    />,
  );
  await screen.findByText("Benchmark median");
  expect(getPlanDiff).toHaveBeenLastCalledWith("run-1", sha("a"), sha("b"), expect.anything());

  await user.selectOptions(screen.getByRole("combobox", { name: "Parameter set" }), "cold");
  expect(getPlanDiff).toHaveBeenLastCalledWith("run-1", sha("c"), sha("d"), expect.anything());
  // No benchmark statistic for this set: the card is left out, not invented.
  await screen.findByText("Execution time");
  expect(screen.queryByText("Benchmark median")).toBeNull();

  await user.selectOptions(screen.getByRole("combobox", { name: "Candidate" }), "oc_b");
  expect(onSelectArm).toHaveBeenCalledWith("oc_b");
});

test("PlanCompare says so when the baseline plan for a parameter set is missing", () => {
  renderWithQuery(
    <PlanCompare runId="run-1" detail={detail([block("oc_a", "hot", sha("b"))])} candidates={[]} arm="oc_a" onSelectArm={() => undefined} compact />,
  );
  expect(screen.getByRole("note").textContent).toBe("No baseline plan was captured for parameter set hot, so there is nothing to compare.");
  expect(getPlanDiff).not.toHaveBeenCalled();
});

test("PlanCompare opens the unified layout on phones", async () => {
  getPlanDiff.mockResolvedValue({ runId: "run-1", fromSha256: sha("a"), toSha256: sha("b"), diff: analyzed });
  renderWithQuery(
    <PlanCompare runId="run-1" detail={detail([block("baseline", "hot", sha("a")), block("oc_a", "hot", sha("b"))])} candidates={[]} arm="oc_a" onSelectArm={() => undefined} compact />,
  );
  expect(await screen.findByRole("table", { name: /one list/ })).toBeTruthy();
});
