import { afterEach, describe, expect, test, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import type { PlanTree } from "@/lib/api/types";
import { PlanExplorer } from "../PlanExplorer";
import { metrics, plan } from "./fixture";

afterEach(cleanup);

const rows = () => within(screen.getByRole("treegrid")).getAllByRole("row").slice(1);

function Harness({ initial = null as number | null, tree = plan as PlanTree, onSelect = vi.fn() as (id: number) => void }) {
  const [selected, setSelected] = useState<number | null>(initial);
  return (
    <>
      <button type="button" onClick={() => setSelected(2)}>
        select scan
      </button>
      <PlanExplorer
        plan={tree}
        metrics={metrics}
        selectedId={selected}
        onSelect={(id) => {
          setSelected(id);
          onSelect(id);
        }}
        label="uploaded plan"
      />
    </>
  );
}

describe("PlanExplorer", () => {
  test("summarizes the plan and counts flagged nodes in words", () => {
    render(<Harness />);

    const summary = screen.getByRole("group", { name: "Plan summary" });
    expect(summary.textContent).toContain("3 nodes");
    expect(summary.textContent).toContain("execution 121 ms");
    expect(summary.textContent).toContain("1 expensive");
    expect(summary.textContent).toContain("1 row misestimate");
  });

  test("Collapse all and Expand all change the visible rows", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: "Collapse all" }));
    expect(rows()).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "Expand all" }));
    expect(rows()).toHaveLength(3);
  });

  test("a node selected from elsewhere is revealed inside a collapsed parent", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: "Collapse all" }));
    await user.click(screen.getByRole("button", { name: "select scan" }));

    const selected = rows().filter((r) => r.getAttribute("aria-selected") === "true");
    expect(selected).toHaveLength(1);
    expect(selected[0]!.textContent).toContain("Seq Scan");
  });

  test("Jump to hottest selects the node with the largest self time", async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(<Harness onSelect={onSelect} />);

    await user.click(screen.getByRole("button", { name: "Jump to hottest node" }));
    expect(onSelect).toHaveBeenCalledWith(2);
  });

  test("flags expensive nodes and misestimates in words, never colour alone", () => {
    render(<Harness />);

    const scan = rows().find((r) => r.textContent?.includes("Seq Scan"));
    expect(within(scan!).getByText("hottest")).toBeDefined();
    expect(within(scan!).getByText("expensive")).toBeDefined();
    expect(within(scan!).getByText("10× under")).toBeDefined();
    expect(within(scan!).getByText("significant")).toBeDefined();
  });

  test("a never-executed node says so and is not counted as a misestimate", () => {
    const never: PlanTree = {
      ...plan,
      nodes: plan.nodes.map((n) => (n.id === 1 ? { ...n, actualLoops: 0, actualRows: 0 } : n)),
      root: { ...plan.root, children: [{ ...plan.root.children![0]!, actualLoops: 0, actualRows: 0 }] },
    };
    render(<Harness tree={never} />);

    expect(screen.getByText("never executed")).toBeDefined();
    expect(screen.getByRole("group", { name: "Plan summary" }).textContent).toContain("1 row misestimate");
  });

  test("full width opens a dialog, and Escape returns focus to the button", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    const open = screen.getByRole("button", { name: "Full width" });
    await user.click(open);
    const dialog = screen.getByRole("dialog", { name: "Execution plan, full width" });
    expect(within(dialog).getByRole("treegrid")).toBeDefined();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(open);
  });

  test("plain EXPLAIN flags no node and labels the cost as cumulative", () => {
    const estimated: PlanTree = { ...plan, analyzed: false, hasTiming: false, executionTimeMs: null };
    const noTiming = metrics.map((m) => ({ ...m, selfTimeMs: null, selfTimeShare: null, inclusiveTimeMs: null, estimateErrorRatio: null, estimateDirection: null }));
    render(<PlanExplorer plan={estimated} metrics={noTiming} selectedId={null} onSelect={() => {}} />);

    const tree = screen.getByRole("treegrid");
    expect(within(tree).queryByText("hottest")).toBeNull();
    expect(within(tree).queryByText("expensive")).toBeNull();
    expect(screen.queryByRole("button", { name: "Jump to hottest node" })).toBeNull();
    expect(screen.getByRole("columnheader", { name: "Est. cost (cumulative)" })).toBeDefined();
  });
});
