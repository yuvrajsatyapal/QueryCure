import { afterEach, beforeAll, describe, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { PlanGraph } from "../PlanGraph";
import { metrics, plan } from "./fixture";

beforeAll(() => {
  // React Flow measures its container; jsdom has no layout engine.
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});
afterEach(cleanup);

describe("PlanGraph", () => {
  test("renders one card per plan node, the same set the tree shows", () => {
    render(<PlanGraph plan={plan} metrics={metrics} />);

    const cards = screen.getAllByTestId("plan-node");
    expect(cards.map((c) => c.getAttribute("data-node-id")).sort()).toEqual(["0", "1", "2"]);
    expect(within(cards.find((c) => c.dataset.nodeId === "2")!).getByText("Seq Scan")).toBeDefined();
  });

  test("accents exactly one hottest node and says so in words", () => {
    render(<PlanGraph plan={plan} metrics={metrics} />);

    const hottest = screen.getAllByTestId("plan-node").filter((c) => c.dataset.hottest === "true");
    expect(hottest).toHaveLength(1);
    expect(hottest[0]!.dataset.nodeId).toBe("2");
    expect(within(hottest[0]!).getByText("hottest")).toBeDefined();
  });

  test("shows the misestimate on the card", () => {
    render(<PlanGraph plan={plan} metrics={metrics} />);

    const scan = screen.getAllByTestId("plan-node").find((c) => c.dataset.nodeId === "2")!;
    expect(within(scan).getByText("10× under")).toBeDefined();
  });

  test("clicking a card selects that node", () => {
    const onSelect = vi.fn();
    render(<PlanGraph plan={plan} metrics={metrics} onSelect={onSelect} />);

    // A bare click: user-event's mousedown has view=null in jsdom, which d3-zoom's pan handler dereferences.
    fireEvent.click(screen.getAllByTestId("plan-node").find((c) => c.dataset.nodeId === "1")!);
    expect(onSelect).toHaveBeenCalledWith(1);
  });

  test("points keyboard and screen-reader users to the tree view", () => {
    render(<PlanGraph plan={plan} metrics={metrics} />);

    expect(screen.getByRole("figure", { name: /plan graph/i })).toBeDefined();
    expect(screen.getByText(/tree view.*keyboard/i)).toBeDefined();
  });
});
