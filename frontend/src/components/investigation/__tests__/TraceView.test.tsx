import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { RunEvent } from "@/lib/api/types";
import { TraceView } from "../TraceView";

afterEach(cleanup);

const at = (s: number) => new Date(Date.UTC(2026, 9, 12, 10, 0, s)).toISOString();
const events = [
  { runId: "r", seq: 1, ts: at(0), type: "node.started", payload: { node: "query_analyzer", agent: "query_analyzer", attempt: 1 } },
  { runId: "r", seq: 2, ts: at(1), type: "tool.started", payload: { tool: "get_plan_node", agent: "query_analyzer" } },
  { runId: "r", seq: 3, ts: at(2), type: "tool.completed", payload: { tool: "get_plan_node", agent: "query_analyzer", status: "ok", durationMs: 1200, evidenceIds: ["ev_aaaaaaaaaaaa"] } },
  { runId: "r", seq: 4, ts: at(3), type: "node.completed", payload: { node: "query_analyzer", agent: "query_analyzer", attempt: 1, durationMs: 3000 } },
] as RunEvent[];

test("a span expands into its details and its evidence opens", async () => {
  const user = userEvent.setup();
  const onEvidence = vi.fn();
  render(<TraceView events={events} live={false} active={false} onEvidence={onEvidence} />);

  const trace = screen.getByRole("region", { name: "Agent timeline" });
  expect(within(trace).getByText("1 nodes · 1 tool calls · 3.0s")).toBeDefined();
  expect(within(trace).queryByText(/Raw events/)).toBeNull();

  await user.click(within(trace).getByRole("button", { name: /get_plan_node/ }));
  expect(within(trace).getByText("Raw events (2)")).toBeDefined();
  expect(within(trace).getByText("1.2s", { selector: "dd" })).toBeDefined();
  await user.click(within(trace).getByRole("button", { name: "ev_aaaaaaaaaaaa" }));
  expect(onEvidence).toHaveBeenCalledWith("ev_aaaaaaaaaaaa");
});

test("collapsing a node hides its tool calls", async () => {
  const user = userEvent.setup();
  render(<TraceView events={events} live={false} active={false} />);

  expect(screen.getByText("get_plan_node")).toBeDefined();
  await user.click(screen.getByRole("button", { name: "Collapse query_analyzer" }));
  expect(screen.queryByText("get_plan_node")).toBeNull();
});
