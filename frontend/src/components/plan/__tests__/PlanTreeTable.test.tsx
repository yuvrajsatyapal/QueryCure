import { afterEach, describe, expect, test, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PlanTreeTable } from "../PlanTreeTable";
import { metrics, plan } from "./fixture";

afterEach(cleanup);

describe("PlanTreeTable", () => {
  test("renders one treegrid row per node with nesting levels", () => {
    render(<PlanTreeTable plan={plan} metrics={metrics} />);

    const rows = within(screen.getByRole("treegrid")).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(3);
    expect(rows.map((r) => r.getAttribute("aria-level"))).toEqual(["1", "2", "3"]);
    expect(rows[2]!.textContent).toContain("Seq Scan");
    expect(rows[2]!.textContent).toContain("orders");
  });

  test("marks the hottest node in words, not only color", () => {
    render(<PlanTreeTable plan={plan} metrics={metrics} />);

    const hottest = screen.getByText("hottest").closest('[role="row"]');
    expect(hottest?.textContent).toContain("Seq Scan");
    expect(hottest?.textContent).toContain("83.0%");
  });

  test("compares estimated and actual rows per loop, like EXPLAIN does", () => {
    const looped = {
      ...plan,
      root: { ...plan.root, children: [{ ...plan.root.children![0]!, actualLoops: 3, actualRows: 7 }] },
    };
    render(<PlanTreeTable plan={looped} metrics={metrics} />);

    expect(screen.getByRole("columnheader", { name: "Est. rows / loop" })).toBeDefined();
    expect(screen.getByRole("columnheader", { name: "Actual rows / loop" })).toBeDefined();
    const sortRow = screen.getAllByRole("row").find((r) => r.textContent?.includes("Sort"));
    // Per-loop actual (7), not the 3-loop total the metrics carry (20).
    expect(within(sortRow!).getAllByRole("gridcell")[2]!.textContent).toBe("7");
  });

  test("shows estimate errors with direction and sort spills", () => {
    render(<PlanTreeTable plan={plan} metrics={metrics} />);

    expect(screen.getByText("10× under")).toBeDefined();
    expect(screen.getByText("25× over")).toBeDefined();
    expect(screen.getByText("spilled to disk")).toBeDefined();
  });

  test("keyboard: arrows move focus, left collapses, right expands", async () => {
    const user = userEvent.setup();
    render(<PlanTreeTable plan={plan} metrics={metrics} />);
    const rows = () => within(screen.getByRole("treegrid")).getAllByRole("row").slice(1);

    rows()[0]!.focus();
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(rows()[1]);

    await user.keyboard("{ArrowLeft}");
    expect(rows()).toHaveLength(2);
    expect(rows()[1]!.getAttribute("aria-expanded")).toBe("false");

    await user.keyboard("{ArrowRight}");
    expect(rows()).toHaveLength(3);

    await user.keyboard("{ArrowRight}");
    expect(document.activeElement).toBe(rows()[2]);
  });

  test("selecting a row reports the node", async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(<PlanTreeTable plan={plan} metrics={metrics} onSelect={onSelect} />);

    await user.click(screen.getByText("Sort"));

    expect(onSelect).toHaveBeenCalledWith(1);
  });

  test("plain EXPLAIN shows estimates and says timings are unavailable", () => {
    const plain = { ...plan, analyzed: false, hasTiming: false };
    const noTimes = metrics.map((m) => ({ ...m, selfTimeMs: null, selfTimeShare: null, inclusiveTimeMs: null }));

    render(<PlanTreeTable plan={plain} metrics={noTimes} />);

    expect(screen.getByText(/Estimates only/)).toBeDefined();
    expect(screen.queryByText("hottest")).toBeNull();
  });
});
