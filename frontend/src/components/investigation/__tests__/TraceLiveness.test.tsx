import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import type { RunEvent } from "@/lib/api/types";
import { buildTrace } from "@/lib/events/trace";
import { moving } from "@/test/motion";
import { renderWithQuery } from "@/test/render";
import { StepDetails } from "../StepDetails";
import { TraceGraph } from "../TraceGraph";
import { TraceTree } from "../TraceTree";

afterEach(cleanup);

const at = (ms: number) => new Date(Date.UTC(2026, 9, 26, 10, 0, 0, ms)).toISOString();
const ev = (seq: number, type: string, payload: Record<string, unknown>, ms: number) => ({ runId: "r", seq, ts: at(ms), type, payload }) as RunEvent;
// intake finished; query_analyzer is open with a tool call still running.
const events = [
  ev(1, "node.started", { node: "intake", agent: null, attempt: 1 }, 0),
  ev(2, "node.completed", { node: "intake", agent: null, attempt: 1, durationMs: 100 }, 100),
  ev(3, "node.started", { node: "query_analyzer", agent: "query_analyzer", attempt: 1 }, 200),
  ev(4, "tool.started", { tool: "get_plan_node", agent: "query_analyzer" }, 300),
];

const tree = (props: { active: boolean; live: boolean; stream?: "live" | "reconnecting" | "offline" | "closed" }) =>
  render(
    <TraceTree
      trace={buildTrace(events, { active: props.active })}
      events={events}
      runLabel="Run #1"
      live={props.live}
      stream={props.stream}
      active={props.active}
      selectedId="run"
      onSelect={vi.fn()}
    />,
  );

const row = (name: RegExp) => screen.getByRole("treeitem", { name });

test("with a confirmed live stream only the open spans move; closed spans and the legend stay still", () => {
  tree({ active: true, live: true, stream: "live" });
  expect(moving(row(/^query_analyzer/))).not.toEqual([]);
  expect(moving(row(/^get_plan_node/))).not.toEqual([]);
  expect(moving(row(/^intake/))).toEqual([]);
  expect(moving(screen.getByRole("list", { name: "Legend" }))).toEqual([]);
});

test("while the stream reconnects an open span is drawn as open but does not move", () => {
  const { container } = tree({ active: true, live: false, stream: "reconnecting" });
  expect(within(row(/^query_analyzer/)).getByText(/running/i)).toBeDefined();
  expect(moving(container)).toEqual([]);
});

test("an offline stream on a running run does not move", () => {
  const { container } = tree({ active: true, live: false, stream: "offline" });
  expect(moving(container)).toEqual([]);
});

test("a recorded trace never looks live: open spans read as unfinished and nothing moves", () => {
  const { container } = tree({ active: false, live: false, stream: "closed" });
  expect(within(row(/^query_analyzer/)).getByText(/did not finish/i)).toBeDefined();
  expect(moving(container)).toEqual([]);
});

test("the graph marks a running node, moving only with a live stream", () => {
  const trace = buildTrace(events, { active: true });
  const graph = (live: boolean) => render(<TraceGraph trace={trace} active live={live} selectedNode={null} onSelectNode={vi.fn()} />);
  const still = graph(false);
  expect(screen.getByRole("button", { name: /^query_analyzer, running/ })).toBeDefined();
  expect(moving(still.container)).toEqual([]);
  still.unmount();
  const live = graph(true);
  expect(moving(screen.getByRole("button", { name: /^query_analyzer, running/ }))).not.toEqual([]);
  expect(moving(screen.getByRole("button", { name: /^intake/ }))).toEqual([]);
  live.unmount();
});

test("step details describe a running step without animating it", () => {
  const trace = buildTrace(events, { active: true });
  const span = trace.children.find((c) => c.name === "query_analyzer")!;
  const { container } = renderWithQuery(<StepDetails span={span} runId="r" onBack={vi.fn()} onSelect={vi.fn()} onOpenEvidence={vi.fn()} />);
  expect(within(container).getAllByText("running").length).toBeGreaterThan(0);
  expect(moving(container)).toEqual([]);
});
