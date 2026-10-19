import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import type { RunEvent } from "@/lib/api/types";
import { buildTrace } from "@/lib/events/trace";
import { renderWithQuery } from "@/test/render";
import { StepDetails } from "../StepDetails";
import { TraceTree } from "../TraceTree";

vi.mock("@/lib/api/investigations", () => ({
  investigationKeys: { evidence: (r: string, e: string) => ["runs", r, "evidence", e] },
  getEvidence: vi.fn(async (_run: string, id: string) => {
    if (id === "ev_missing00000") throw new Error("gone");
    return {
      evidence: { id, kind: "plan_node", locator: "/0", summary: "Seq Scan on orders", data: { nodeId: 2 }, provenance: "imported", artifactSha256: "p" },
      artifact: { sha256: "p", kind: "plan_analyze" },
      citedByFindings: [],
      citedByHypotheses: [],
    };
  }),
}));

afterEach(cleanup);

const at = (s: number) => new Date(Date.UTC(2026, 9, 12, 10, 0, s)).toISOString();
const events = [
  { runId: "r", seq: 1, ts: at(0), type: "node.started", payload: { node: "query_analyzer", agent: "query_analyzer", attempt: 1 } },
  { runId: "r", seq: 2, ts: at(1), type: "tool.started", payload: { tool: "get_plan_node", agent: "query_analyzer" } },
  {
    runId: "r",
    seq: 3,
    ts: at(2),
    type: "tool.completed",
    payload: { tool: "get_plan_node", agent: "query_analyzer", status: "ok", durationMs: 1200, evidenceIds: ["ev_aaaaaaaaaaaa", "ev_missing00000"] },
  },
  { runId: "r", seq: 4, ts: at(3), type: "node.completed", payload: { node: "query_analyzer", agent: "query_analyzer", attempt: 1, durationMs: 3000 } },
] as RunEvent[];
const trace = buildTrace(events, { active: false });

// "Select from outside" stands in for a finding's "Show step".
function Harness() {
  const [selected, setSelected] = useState("run");
  return (
    <>
      <button type="button" onClick={() => setSelected(trace.children[0]!.children[0]!.id)}>
        Select from outside
      </button>
      <TraceTree trace={trace} events={events} runLabel="Run #1" live={false} active={false} selectedId={selected} onSelect={setSelected} />
    </>
  );
}

test("the tree is a keyboard tree: arrows move selection, left collapses and climbs, right expands", async () => {
  const user = userEvent.setup();
  render(<Harness />);
  const tree = screen.getByRole("tree", { name: "Run steps" });
  expect(within(screen.getByRole("region", { name: "Agent timeline" })).getByText("1 nodes · 1 tool calls · 3.0s")).toBeDefined();
  const item = (name: RegExp) => within(tree).getByRole("treeitem", { name });

  expect(item(/Run #1/).getAttribute("aria-selected")).toBe("true");
  item(/Run #1/).focus();
  await user.keyboard("{ArrowDown}");
  expect(item(/^query_analyzer/).getAttribute("aria-selected")).toBe("true");
  expect(document.activeElement).toBe(item(/^query_analyzer/));
  await user.keyboard("{ArrowRight}");
  expect(item(/get_plan_node/).getAttribute("aria-selected")).toBe("true");
  await user.keyboard("{ArrowLeft}");
  expect(item(/^query_analyzer/).getAttribute("aria-selected")).toBe("true");
  await user.keyboard("{ArrowLeft}");
  expect(item(/^query_analyzer/).getAttribute("aria-expanded")).toBe("false");
  expect(within(tree).queryByRole("treeitem", { name: /get_plan_node/ })).toBeNull();
  await user.keyboard("{ArrowRight}");
  expect(item(/get_plan_node/)).toBeDefined();
  await user.keyboard("{Home}");
  expect(item(/Run #1/).getAttribute("aria-selected")).toBe("true");
});

test("a row selected from outside is revealed inside a collapsed node", async () => {
  const user = userEvent.setup();
  render(<Harness />);
  await user.click(screen.getByRole("button", { name: "Collapse all" }));
  expect(screen.queryByRole("treeitem", { name: /get_plan_node/ })).toBeNull();
  await user.click(screen.getByRole("button", { name: "Select from outside" }));
  expect(screen.getByRole("treeitem", { name: /get_plan_node/ }).getAttribute("aria-selected")).toBe("true");
});

test("step details show recorded fields and name what is not available", async () => {
  const user = userEvent.setup();
  const onOpenEvidence = vi.fn();
  const tool = trace.children[0]!.children[0]!;
  renderWithQuery(<StepDetails span={tool} runId="r" onBack={vi.fn()} onSelect={vi.fn()} onOpenEvidence={onOpenEvidence} />);
  const panel = screen.getByRole("region", { name: "Selection details" });

  expect(within(panel).getByText("Called by").nextSibling?.textContent).toBe("query_analyzer");
  expect(within(panel).getByText(/stored redacted on the server and not exposed to the browser/)).toBeDefined();

  await user.click(within(panel).getByRole("tab", { name: "Output" }));
  expect(within(panel).getByText("Status").nextSibling?.textContent).toBe("ok");
  expect(within(panel).getByText("Latency").nextSibling?.textContent).toBe("1.2s");

  await user.click(within(panel).getByRole("tab", { name: /Evidence/ }));
  expect(await within(panel).findByText("Seq Scan on orders")).toBeDefined();
  expect(await within(panel).findByText(/Could not load this evidence/)).toBeDefined();
  await user.click(within(panel).getByRole("button", { name: /Show in plan/ }));
  expect(onOpenEvidence).toHaveBeenCalledWith("ev_aaaaaaaaaaaa");
});

test("an agent step says its prompt and raw output are not available", async () => {
  const user = userEvent.setup();
  renderWithQuery(<StepDetails span={trace.children[0]!} runId="r" onBack={vi.fn()} onSelect={vi.fn()} onOpenEvidence={vi.fn()} />);
  expect(screen.getByText(/Model prompt/)).toBeDefined();
  await user.click(screen.getByRole("tab", { name: "Output" }));
  expect(screen.getByText(/Raw model output/)).toBeDefined();
  expect(screen.getByText("Recorded during this step (1)")).toBeDefined();
});
