import { afterEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import type { RunEvent } from "@/lib/api/types";
import { buildTrace } from "@/lib/events/trace";
import { BottomSheet } from "@/components/ui/BottomSheet";
import { ContextMenu } from "@/components/ui/ContextMenu";
import { StepDetails } from "../StepDetails";
import { TraceGraph } from "../TraceGraph";
import { TraceTree } from "../TraceTree";

afterEach(cleanup);

const at = (ms: number) => new Date(Date.UTC(2026, 9, 24, 10) + ms).toISOString();
let seq = 0;
const ev = (type: string, payload: Record<string, unknown>, ms: number) => ({ runId: "r", seq: ++seq, ts: at(ms), type, payload }) as RunEvent;
const events = [
  ev("node.started", { node: "intake", agent: null, attempt: 1 }, 0),
  ev("node.completed", { node: "intake", agent: null, attempt: 1, durationMs: 100 }, 100),
  ev("node.started", { node: "approval_gate", agent: null, attempt: 1 }, 200),
  ev("approval.requested", { status: "pending", round: 0 }, 300),
];
const trace = buildTrace(events, { active: true });

test("the graph shows the compiled topology with recorded states, and arrow keys move between nodes", async () => {
  const user = userEvent.setup();
  const onSelectNode = vi.fn();
  function Harness() {
    const [node, setNode] = useState<string | null>("intake");
    return (
      <TraceGraph
        trace={trace}
        active
        selectedNode={node}
        onSelectNode={(n) => {
          setNode(n);
          onSelectNode(n);
        }}
      />
    );
  }
  render(<Harness />);
  const graph = screen.getByRole("region", { name: "Agent graph" });
  expect(within(graph).getByRole("button", { name: /^intake, done, 100ms/ })).toBeDefined();
  expect(within(graph).getByRole("button", { name: /^approval_gate, waiting on you/ })).toBeDefined();
  // Never "skipped" or "queued": only what the events say.
  expect(within(graph).getByRole("button", { name: "workload_investigator, not reached" })).toBeDefined();
  within(graph).getByRole("button", { name: /^intake/ }).focus();
  await user.keyboard("{ArrowRight}");
  expect(onSelectNode).toHaveBeenLastCalledWith("collect_context");
  expect(document.activeElement?.getAttribute("data-node")).toBe("collect_context");
});

test("the selected graph node's full name and details are shown untruncated, whatever the zoom", async () => {
  const user = userEvent.setup();
  function Harness() {
    const [node, setNode] = useState<string | null>(null);
    return <TraceGraph trace={trace} active selectedNode={node} onSelectNode={setNode} />;
  }
  render(<Harness />);
  const graph = screen.getByRole("region", { name: "Agent graph" });
  const status = within(graph).getByRole("status", { name: "Selected node" });
  expect(status.textContent).toMatch(/Select a node for its full name/);
  await user.click(within(graph).getByRole("button", { name: /^workload_investigator/ }));
  expect(status.textContent).toContain("workload_investigator");
  expect(status.textContent).toContain("not reached");
  await user.click(within(graph).getByRole("button", { name: /^approval_gate/ }));
  expect(status.textContent).toContain("approval_gate");
  expect(status.textContent).toContain("waiting on you");
  // Zooming to the smallest scale keeps the strip; it is not scaled with the canvas.
  for (let i = 0; i < 8; i++) await user.click(within(graph).getByRole("button", { name: "Zoom out" }));
  expect(status.textContent).toContain("approval_gate");
  expect(status.closest("[style*='scale']")).toBeNull();
  // A touch hint that dragging pans the canvas; decorative, so hidden from assistive tech.
  expect(within(graph).getByText("Drag to explore").closest("[aria-hidden='true']")).not.toBeNull();
});

test("right-click and Shift+F10 on a trace row ask for its actions", async () => {
  const user = userEvent.setup();
  const onMenu = vi.fn();
  render(<TraceTree trace={trace} events={events} runLabel="Run #1" live active selectedId="run" onSelect={vi.fn()} onMenu={onMenu} />);
  const row = screen.getByRole("treeitem", { name: /^intake/ });
  fireEvent.contextMenu(row, { clientX: 40, clientY: 50 });
  expect(onMenu).toHaveBeenLastCalledWith(row.getAttribute("data-span"), { x: 40, y: 50 });
  screen.getByRole("treeitem", { name: /Run #1/ }).focus();
  await user.keyboard("{Shift>}{F10}{/Shift}");
  expect(onMenu).toHaveBeenLastCalledWith("run", expect.objectContaining({ x: expect.any(Number) }));
  // The approval wait is drawn from recorded times and the legend names it.
  expect(within(screen.getByRole("list", { name: "Legend" })).getByText("Waiting on you")).toBeDefined();
});

test("the context menu is keyboard operable and returns focus to its opener", async () => {
  const user = userEvent.setup();
  const copy = vi.fn();
  function Harness() {
    const [open, setOpen] = useState(false);
    return (
      <>
        <button type="button" onClick={() => setOpen(true)}>
          Open
        </button>
        {open ? (
          <ContextMenu
            label="Step actions"
            at={{ x: 10, y: 10 }}
            onClose={() => setOpen(false)}
            items={[
              { id: "a", label: "Inspect", onSelect: vi.fn() },
              { id: "b", label: "Disabled", disabled: true, onSelect: vi.fn() },
              { id: "c", label: "Copy step name", onSelect: copy },
            ]}
          />
        ) : null}
      </>
    );
  }
  render(<Harness />);
  const opener = screen.getByRole("button", { name: "Open" });
  await user.click(opener);
  const menu = screen.getByRole("menu", { name: "Step actions" });
  expect(document.activeElement).toBe(within(menu).getByRole("menuitem", { name: "Inspect" }));
  await user.keyboard("{ArrowDown}");
  expect(document.activeElement).toBe(within(menu).getByRole("menuitem", { name: "Copy step name" }));
  await user.keyboard("{Enter}");
  expect(copy).toHaveBeenCalled();
  expect(screen.queryByRole("menu")).toBeNull();
  await user.click(opener);
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("menu")).toBeNull();
  expect(document.activeElement).toBe(opener);
});

test("the bottom sheet is a modal dialog that Esc closes", async () => {
  const user = userEvent.setup();
  const onClose = vi.fn();
  render(
    <BottomSheet label="Step details: intake" onClose={onClose}>
      <button type="button">Inside</button>
    </BottomSheet>,
  );
  const dialog = screen.getByRole("dialog", { name: "Step details: intake" });
  expect(dialog.getAttribute("aria-modal")).toBe("true");
  expect(document.activeElement).toBe(within(dialog).getByRole("button", { name: "Close details" }));
  await user.keyboard("{Escape}");
  expect(onClose).toHaveBeenCalled();
});

test("a focus request moves focus to the selected graph node (Show in graph)", () => {
  const onFocusDone = vi.fn();
  const props = { trace, active: true, selectedNode: "approval_gate", onSelectNode: vi.fn(), onFocusDone };
  const { rerender } = render(<TraceGraph {...props} />);
  // Mounting alone does not steal focus.
  expect(document.activeElement).toBe(document.body);
  rerender(<TraceGraph {...props} focusRequest />);
  expect(document.activeElement?.getAttribute("data-node")).toBe("approval_gate");
  expect(onFocusDone).toHaveBeenCalledOnce();
  // The menu switches views, so the graph usually mounts with the request already set.
  cleanup();
  render(<TraceGraph {...props} selectedNode="intake" focusRequest />);
  expect(document.activeElement?.getAttribute("data-node")).toBe("intake");
});

test("a long approval wait offers a labelled compressed time scale; linear stays the default", async () => {
  const user = userEvent.setup();
  seq = 0;
  const waited = [
    ev("node.started", { node: "intake", agent: null, attempt: 1 }, 0),
    ev("node.completed", { node: "intake", agent: null, attempt: 1, durationMs: 100 }, 100),
    ev("node.started", { node: "approval_gate", agent: null, attempt: 1 }, 200),
    ev("approval.requested", { status: "pending", round: 0 }, 300),
    ev("approval.decided", { status: "approved", round: 0 }, 600_000),
    ev("node.completed", { node: "approval_gate", agent: null, attempt: 1, durationMs: 10 }, 600_010),
    ev("run.concluded", { outcome: "inconclusive" }, 600_100),
  ];
  render(<TraceTree trace={buildTrace(waited, { active: false })} events={waited} runLabel="Run #1" live={false} active={false} selectedId="run" onSelect={vi.fn()} />);
  const scale = screen.getByRole("group", { name: "Time scale" });
  expect(within(scale).getByRole("button", { name: "Linear" }).getAttribute("aria-pressed")).toBe("true");
  expect(screen.queryByRole("note")).toBeNull();
  await user.click(within(scale).getByRole("button", { name: "Compress waits" }));
  expect(screen.getByRole("note").textContent).toMatch(/Compressed time\..*not elapsed time/);
  // The narrow-pane wording still says the axis is not linear.
  expect(screen.getByRole("note").textContent).toMatch(/Not to scale across ≈ breaks/);
  expect(within(screen.getByRole("list", { name: "Legend" })).getByText("Compressed wait, not to scale")).toBeDefined();
  // A run without a dominating wait has no compression control at all.
  cleanup();
  const short = waited.slice(0, 2);
  render(<TraceTree trace={buildTrace(short, { active: false })} events={short} runLabel="Run #1" live={false} active={false} selectedId="run" onSelect={vi.fn()} />);
  expect(screen.queryByRole("group", { name: "Time scale" })).toBeNull();
});

test("in the sheet the inspector has one header row: name, Actions and a single Close", () => {
  const intake = trace.children.find((c) => c.name === "intake")!;
  const onClose = vi.fn();
  render(
    <BottomSheet label="Step details: intake" onClose={onClose} ownHeader>
      <StepDetails span={intake} runId="r" embedded onBack={vi.fn()} onSelect={vi.fn()} onOpenEvidence={vi.fn()} onActions={vi.fn()} onClose={onClose} />
    </BottomSheet>,
  );
  const dialog = screen.getByRole("dialog", { name: "Step details: intake" });
  expect(within(dialog).getAllByRole("button", { name: "Close details" })).toHaveLength(1);
  expect(within(dialog).queryByRole("button", { name: /Back to run results/ })).toBeNull();
  expect(within(dialog).getByRole("button", { name: "Actions" }).getAttribute("aria-haspopup")).toBe("menu");
  expect(document.activeElement).toBe(within(dialog).getByRole("button", { name: "Close details" }));
  fireEvent.click(within(dialog).getByRole("button", { name: "Close details" }));
  expect(onClose).toHaveBeenCalled();
});
