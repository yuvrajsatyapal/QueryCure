import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { RunSummary } from "@/lib/api/types";
import { RunPicker, runRelation } from "../RunPicker";

afterEach(cleanup);

function run(overrides: Partial<RunSummary>): RunSummary {
  return {
    id: "run-1",
    investigationId: "inv-1",
    runNumber: 1,
    kind: "initial",
    status: "completed",
    outcome: "verified_recommendation",
    createdAt: "2026-10-13T12:00:00Z",
    startedAt: null,
    finishedAt: null,
    parentRunId: null,
    finalized: true,
    replay: null,
    ...overrides,
  };
}

const original = run({});
const replay = run({
  id: "run-2",
  runNumber: 2,
  kind: "experiment_replay",
  outcome: null,
  parentRunId: "run-1",
  replay: { attemptId: "att-1", status: "reproduced_with_drift", sourceExperimentId: "exp-1" },
});
const again = run({ id: "run-3", runNumber: 3, kind: "reinvestigation", status: "failed", outcome: null, parentRunId: "run-1", finalized: false });

test("a single run needs no picker", () => {
  const { container } = render(<RunPicker runs={[original]} selectedId="run-1" onSelect={vi.fn()} />);
  expect(container.innerHTML).toBe("");
});

test("lists runs newest first and tells original, replay and re-investigation apart", () => {
  render(<RunPicker runs={[original, replay, again]} selectedId="run-1" onSelect={vi.fn()} />);
  const nav = screen.getByRole("navigation", { name: "Runs of this investigation" });
  const items = within(nav).getAllByRole("button");
  expect(items.map((b) => b.textContent)).toEqual([
    expect.stringContaining("#3AI re-investigationof run #1"),
    expect.stringContaining("#2Experiment replayof run #1"),
    expect.stringContaining("#1Original run"),
  ]);
  expect(items[1]?.textContent).toContain("reproduced with drift");
  expect(items[0]?.textContent).toContain("failed");
  expect(items[2]?.textContent).toContain("followed by #2 (experiment replay), #3 (ai re-investigation)");
  expect(items[2]?.getAttribute("aria-current")).toBe("true");
  // The selected, sealed run links to its historical report.
  expect(within(nav).getByRole("link", { name: "Open this run's report" }).getAttribute("href")).toBe("/app/reports/run-1");
});

test("selecting a run reports its id, and an unsealed run offers no report link", async () => {
  const onSelect = vi.fn();
  render(<RunPicker runs={[original, replay, again]} selectedId="run-3" onSelect={onSelect} />);
  expect(screen.queryByRole("link", { name: "Open this run's report" })).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: /^#2/ }));
  expect(onSelect).toHaveBeenCalledWith("run-2");
});

test("a parent that is no longer listed is said so, not hidden", () => {
  expect(runRelation(run({ id: "x", parentRunId: "gone" }), [original])).toBe("of a run that is no longer available");
});
