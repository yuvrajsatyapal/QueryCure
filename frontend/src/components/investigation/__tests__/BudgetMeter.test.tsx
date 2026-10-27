import { afterEach, expect, test } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import type { RunDetail } from "@/lib/api/types";
import { RunStats } from "../BudgetMeter";

afterEach(cleanup);

const budget = { llmCalls: 40, totalTokens: 400000, toolCalls: 80, toolCallsPerAgent: 8, wallClockSeconds: 1200 };

function run(over: Partial<RunDetail>): RunDetail {
  return {
    id: "run-1",
    runNumber: 1,
    kind: "initial",
    status: "completed",
    startedAt: "2026-10-27T10:00:00.000Z",
    finishedAt: "2026-10-27T10:00:30.000Z",
    budget,
    usage: {},
    ...over,
  } as RunDetail;
}

function strip() {
  return screen.getByRole("region", { name: "Budget" });
}

test.each(["completed", "running", "failed"])("a %s experiment replay shows LLM calls and tokens as not used, not as budget meters", (status) => {
  render(<RunStats run={run({ kind: "experiment_replay", status, usage: { llmCalls: 0, inputTokens: 0, outputTokens: 0, toolCalls: 2 } })} events={[]} nowMs={null} />);

  expect(within(strip()).queryByRole("meter", { name: "LLM calls" })).toBeNull();
  expect(within(strip()).queryByRole("meter", { name: "Tokens" })).toBeNull();
  expect(within(strip()).getAllByText("Not used")).toHaveLength(2);
  expect(within(strip()).queryByText("/ 40")).toBeNull();
  expect(within(strip()).queryByText("/ 400K")).toBeNull();
  for (const label of ["LLM calls", "Tokens"]) {
    expect(within(strip()).getByText(label).parentElement?.getAttribute("title")).toBe("Experiment replays make no model calls");
  }
  // Tool calls are still metered against the run's budget.
  expect(within(strip()).getByRole("meter", { name: "Tool calls" }).getAttribute("aria-valuenow")).toBe("2");
});

test("an experiment replay with no usage recorded yet also reads not used", () => {
  render(<RunStats run={run({ kind: "experiment_replay", status: "queued", usage: {} })} events={[]} nowMs={null} />);

  expect(within(strip()).getAllByText("Not used")).toHaveLength(2);
});

test.each(["initial", "reinvestigation"])("an ordinary %s run keeps its usage meters against the budget", (kind) => {
  render(<RunStats run={run({ kind, usage: { llmCalls: 7, inputTokens: 12000, outputTokens: 3000, toolCalls: 11 } })} events={[]} nowMs={null} />);

  expect(within(strip()).queryByText("Not used")).toBeNull();
  const calls = within(strip()).getByRole("meter", { name: "LLM calls" });
  expect(calls.getAttribute("aria-valuenow")).toBe("7");
  expect(calls.getAttribute("aria-valuemax")).toBe("40");
  const tokens = within(strip()).getByRole("meter", { name: "Tokens" });
  expect(tokens.getAttribute("aria-valuenow")).toBe("15000");
  expect(tokens.getAttribute("aria-valuemax")).toBe("400000");
  expect(within(strip()).getByText("/ 400K")).toBeDefined();
});

test("an ordinary run that made no model calls still shows zero against its budget", () => {
  render(<RunStats run={run({ kind: "initial", usage: { llmCalls: 0, inputTokens: 0, outputTokens: 0 } })} events={[]} nowMs={null} />);

  expect(within(strip()).getByRole("meter", { name: "LLM calls" }).getAttribute("aria-valuenow")).toBe("0");
  expect(within(strip()).queryByText("Not used")).toBeNull();
});

test("recorded model usage on an experiment replay is shown, never hidden behind not used", () => {
  render(<RunStats run={run({ kind: "experiment_replay", usage: { llmCalls: 1, inputTokens: 50, outputTokens: 10 } })} events={[]} nowMs={null} />);

  expect(within(strip()).getByRole("meter", { name: "LLM calls" }).getAttribute("aria-valuenow")).toBe("1");
  expect(within(strip()).getByRole("meter", { name: "Tokens" }).getAttribute("aria-valuenow")).toBe("60");
  expect(within(strip()).queryByText("Not used")).toBeNull();
});
