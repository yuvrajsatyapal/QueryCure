import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { RunSummary } from "@/lib/api/types";
import { RunSelector } from "../RunSelector";

afterEach(cleanup);

const run = (o: Partial<RunSummary>): RunSummary =>
  ({
    id: "run-1",
    investigationId: "inv",
    runNumber: 1,
    kind: "initial",
    status: "completed",
    outcome: null,
    parentRunId: null,
    replay: null,
    finalized: true,
    createdAt: "2026-10-12T10:00:00Z",
    startedAt: null,
    finishedAt: null,
    ...o,
  }) as RunSummary;
const runs = [run({}), run({ id: "run-2", runNumber: 2, kind: "experiment_replay", parentRunId: "run-1" })];

test("the header dropdown opens the run list, selects, and closes", async () => {
  const user = userEvent.setup();
  const onSelect = vi.fn();
  render(<RunSelector runs={runs} selectedId="run-1" onSelect={onSelect} />);

  const trigger = screen.getByRole("button", { name: /run 1 · Original run/ });
  expect(trigger.getAttribute("aria-expanded")).toBe("false");
  expect(screen.queryByRole("navigation", { name: "Runs of this investigation" })).toBeNull();

  await user.click(trigger);
  expect(trigger.getAttribute("aria-expanded")).toBe("true");
  await user.click(screen.getByRole("button", { name: /^#2/ }));
  expect(onSelect).toHaveBeenCalledWith("run-2");
  expect(screen.queryByRole("navigation", { name: "Runs of this investigation" })).toBeNull();
});

test("Escape closes the list and returns focus to the trigger", async () => {
  const user = userEvent.setup();
  render(<RunSelector runs={runs} selectedId="run-1" onSelect={vi.fn()} />);
  const trigger = screen.getByRole("button", { name: /run 1/ });
  await user.click(trigger);
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("navigation", { name: "Runs of this investigation" })).toBeNull();
  expect(document.activeElement).toBe(trigger);
});

test("a single run is a label, not a dropdown", () => {
  render(<RunSelector runs={[runs[0]!]} selectedId="run-1" onSelect={vi.fn()} />);
  expect(screen.getByText("run 1 · Original run")).toBeDefined();
  expect(screen.queryByRole("button")).toBeNull();
});
