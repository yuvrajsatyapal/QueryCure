import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { renderWithQuery } from "@/test/render";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }), usePathname: () => "/app" }));
vi.mock("@/lib/api/investigations", () => ({
  investigationKeys: { list: (p: object) => ["investigations", "list", p] },
  listInvestigations: vi.fn(),
}));

import { listInvestigations } from "@/lib/api/investigations";
import { CommandProvider, useContextCommands, useRunScope, type Command, type RunScope, type ScopedItem } from "../CommandProvider";

const page = (items: { id: string; title: string }[]) =>
  ({
    items: items.map((i) => ({ ...i, objective: "o", modes: ["offline"], createdAt: "2026-10-20T00:00:00Z", latestRun: null })),
    nextCursor: null,
  }) as unknown as Awaited<ReturnType<typeof listInvestigations>>;

function Contextual({ run }: { run: () => void }) {
  const commands = useMemo<Command[]>(
    () => [{ id: "tab-plan", label: "Show Plan tab", group: "This investigation", keys: ["g", "p"], run }],
    [run],
  );
  useContextCommands("test", commands);
  return null;
}

function setup(extra?: ReactNode) {
  return renderWithQuery(
    <CommandProvider>
      <button type="button">before</button>
      <input aria-label="Some field" />
      <div className="cm-editor">
        <div className="cm-content" tabIndex={0} aria-label="SQL query" />
      </div>
      {extra}
    </CommandProvider>,
  );
}

beforeEach(() => {
  push.mockReset();
  vi.mocked(listInvestigations).mockReset().mockResolvedValue(page([{ id: "r1", title: "Recent orders run" }]));
});
afterEach(cleanup);

test("Ctrl+K opens the palette with focus in its combobox; Esc closes it and returns focus", async () => {
  setup();
  const before = screen.getByRole("button", { name: "before" });
  before.focus();

  fireEvent.keyDown(before, { key: "k", ctrlKey: true });
  const combo = screen.getByRole("combobox", { name: "Search commands and investigations" });
  expect(screen.getByRole("dialog", { name: "Command palette" }).getAttribute("aria-modal")).toBe("true");
  await waitFor(() => expect(document.activeElement).toBe(combo));

  fireEvent.keyDown(combo, { key: "Escape" });
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(document.activeElement).toBe(before);
});

test("the shortcut listener is attached once, marked ready only after it exists, and removed with the provider", async () => {
  const root = document.documentElement;
  const attach = window.addEventListener.bind(window);
  const add = vi.spyOn(window, "addEventListener");
  const remove = vi.spyOn(window, "removeEventListener");
  const markerWhenAttached: (string | null)[] = [];
  add.mockImplementation((...args: Parameters<Window["addEventListener"]>) => {
    if (args[0] === "keydown") markerWhenAttached.push(root.getAttribute("data-shortcuts"));
    attach(...args);
  });
  function Changing() {
    const [n, setN] = useState(0);
    const run = useMemo(() => () => n, [n]);
    return (
      <>
        <button type="button" onClick={() => setN((v) => v + 1)}>
          change commands
        </button>
        <Contextual run={run} />
      </>
    );
  }
  expect(root.hasAttribute("data-shortcuts")).toBe(false);
  const view = setup(<Changing />);
  expect(markerWhenAttached).toEqual([null]);
  expect(root.getAttribute("data-shortcuts")).toBe("ready");

  // New page commands re-register in the key map, never as a second window listener.
  fireEvent.click(screen.getByRole("button", { name: "change commands" }));
  await act(async () => {});
  expect(add.mock.calls.filter(([type]) => type === "keydown")).toHaveLength(1);
  // ⌘K toggles, so a duplicated listener would open and close the palette in one press.
  fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });
  expect(screen.getByRole("dialog", { name: "Command palette" })).toBeDefined();

  view.unmount();
  const handler = add.mock.calls.find(([type]) => type === "keydown")?.[1];
  expect(remove.mock.calls.filter(([type, fn]) => type === "keydown" && fn === handler)).toHaveLength(1);
  expect(root.hasAttribute("data-shortcuts")).toBe(false);
  add.mockRestore();
  remove.mockRestore();
});

test("Ctrl+K also works from inside a text field", () => {
  setup();
  fireEvent.keyDown(screen.getByLabelText("Some field"), { key: "k", ctrlKey: true });
  expect(screen.getByRole("dialog", { name: "Command palette" })).toBeDefined();
});

test("typing filters commands; arrows move the active option and Enter runs it", async () => {
  const user = userEvent.setup();
  setup();
  fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });
  const combo = screen.getByRole("combobox");

  await user.type(combo, "go to");
  const options = screen.getAllByRole("option");
  expect(options.map((o) => o.textContent)).toEqual(expect.arrayContaining([expect.stringContaining("Go to History")]));
  expect(combo.getAttribute("aria-activedescendant")).toBe(options[0]?.id);
  await user.keyboard("{ArrowDown}");
  expect(combo.getAttribute("aria-activedescendant")).toBe(options[1]?.id);
  expect(options[1]?.getAttribute("aria-selected")).toBe("true");

  await user.clear(combo);
  await user.type(combo, "history");
  await user.keyboard("{Enter}");
  expect(push).toHaveBeenCalledWith("/app/history");
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("the palette lists recent investigations, then searches titles through the API", async () => {
  const user = userEvent.setup();
  setup();
  fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });
  expect(await screen.findByRole("option", { name: /Recent orders run/ })).toBeDefined();
  expect(vi.mocked(listInvestigations)).toHaveBeenCalledWith({ limit: 5 }, expect.anything());

  vi.mocked(listInvestigations).mockResolvedValue(page([{ id: "inv-9", title: "Slow invoices" }]));
  await user.type(screen.getByRole("combobox"), "invoices");
  await screen.findByRole("option", { name: /Slow invoices/ });
  expect(vi.mocked(listInvestigations)).toHaveBeenLastCalledWith({ q: "invoices", limit: 8 }, expect.anything());

  await user.keyboard("{Enter}");
  expect(push).toHaveBeenCalledWith("/app/investigations/inv-9");
});

test("an empty search says so instead of showing nothing", async () => {
  vi.mocked(listInvestigations).mockResolvedValue(page([]));
  const user = userEvent.setup();
  setup();
  fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });
  await user.type(screen.getByRole("combobox"), "zzzz");
  expect(await screen.findByText("No matching investigations.")).toBeDefined();
});

test("g h navigates, but not while typing in a field or the SQL editor", () => {
  setup();
  const field = screen.getByLabelText("Some field");
  fireEvent.keyDown(field, { key: "g" });
  fireEvent.keyDown(field, { key: "h" });
  fireEvent.keyDown(screen.getByLabelText("SQL query"), { key: "c" });
  expect(push).not.toHaveBeenCalled();

  fireEvent.keyDown(document.body, { key: "g" });
  fireEvent.keyDown(document.body, { key: "h" });
  expect(push).toHaveBeenCalledWith("/app/history");
  fireEvent.keyDown(document.body, { key: "c" });
  expect(push).toHaveBeenLastCalledWith("/app/investigations/new");
});

test("shortcuts do nothing while a modal dialog is open", () => {
  setup();
  fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });
  fireEvent.keyDown(document.body, { key: "c" });
  expect(push).not.toHaveBeenCalled();
});

test("? opens the shortcuts dialog listing the bound keys, focused on Close", () => {
  setup();
  fireEvent.keyDown(document.body, { key: "?", shiftKey: true });
  const dialog = screen.getByRole("dialog", { name: "Keyboard shortcuts" });
  expect(dialog.textContent).toContain("Go to History");
  expect(dialog.textContent).toContain("Command palette");
  expect(document.activeElement).toBe(screen.getByRole("button", { name: "Close keyboard shortcuts" }));
});

test("page commands join the palette and the key map only while mounted", async () => {
  const run = vi.fn();
  const view = setup(<Contextual run={run} />);
  fireEvent.keyDown(document.body, { key: "g" });
  fireEvent.keyDown(document.body, { key: "p" });
  expect(run).toHaveBeenCalledTimes(1);

  fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });
  expect(screen.getByRole("group", { name: "This investigation" }).textContent).toContain("Show Plan tab");
  fireEvent.keyDown(screen.getByRole("combobox"), { key: "Escape" });

  view.rerender(
    <CommandProvider>
      <span />
    </CommandProvider>,
  );
  await act(async () => {});
  fireEvent.keyDown(document.body, { key: "g" });
  fireEvent.keyDown(document.body, { key: "p" });
  expect(run).toHaveBeenCalledTimes(1);
});

test("the results region is a tab stop that keeps arrow and Enter handling, and Tab stays in the palette", async () => {
  const user = userEvent.setup();
  setup();
  fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });
  const combo = screen.getByRole("combobox");
  await waitFor(() => expect(document.activeElement).toBe(combo));

  await user.tab();
  const results = screen.getByRole("region", { name: "Results" });
  expect(document.activeElement).toBe(results);
  await user.keyboard("{ArrowDown}");
  expect(combo.getAttribute("aria-activedescendant")).toBe(screen.getAllByRole("option")[1]?.id);

  // Focus is trapped: Tab from the last stop wraps to the combobox.
  await user.tab();
  expect(document.activeElement).toBe(combo);
});

// --- Run scope (UI_UX §3.15, workstream 3) ---

const item = (runId: string, key: string, label: string, run = vi.fn(), group: ScopedItem["group"] = "Findings"): ScopedItem => ({
  id: `finding-${key}`,
  runId,
  group,
  label,
  detail: "High severity",
  keywords: [key],
  target: { kind: "finding", key },
  run,
});
const scopeOf = (runId: string, label: string, items: ScopedItem[], loading = false): RunScope => ({ runId, label, loading, items });

function Scoped({ scope }: { scope: RunScope | null }) {
  useRunScope(scope);
  return null;
}

test("from a run, the palette opens scoped to it: the run's results, no investigation search, a named scope chip", async () => {
  const run = vi.fn();
  const user = userEvent.setup();
  setup(<Scoped scope={scopeOf("run-3", "Run 3", [item("run-3", "fd_1", "Seq Scan dominates", run)])} />);
  fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });

  const combo = screen.getByRole("combobox", { name: "Search Run 3 and commands" });
  expect(screen.getByRole("button", { name: "Leave Run 3 scope and search everywhere" })).toBeDefined();
  const findings = screen.getByRole("group", { name: "Findings" });
  expect(within(findings).getByRole("option", { name: /Seq Scan dominates/ }).textContent).toContain("High severity");
  // Existing commands stay available in the scope.
  expect(screen.getByRole("option", { name: /New investigation/ })).toBeDefined();
  await act(async () => {});
  expect(vi.mocked(listInvestigations)).not.toHaveBeenCalled();
  expect(screen.queryByText("Recent investigations")).toBeNull();

  await user.type(combo, "fd_1");
  expect(screen.getAllByRole("option")).toHaveLength(1);
  await user.keyboard("{Enter}");
  expect(run).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("the scope chip and Backspace in an empty field leave the scope; a command returns to it; each change is announced", async () => {
  const user = userEvent.setup();
  setup(<Scoped scope={scopeOf("run-3", "Run 3", [item("run-3", "fd_1", "Seq Scan dominates")])} />);
  fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });

  await user.click(screen.getByRole("button", { name: "Leave Run 3 scope and search everywhere" }));
  const combo = screen.getByRole("combobox", { name: "Search commands and investigations" });
  expect(document.activeElement).toBe(combo);
  expect(screen.queryByRole("group", { name: "Findings" })).toBeNull();
  expect(await screen.findByRole("option", { name: /Recent orders run/ })).toBeDefined();
  expect(screen.getByText("Searching everywhere")).toBeDefined();

  await user.type(combo, "run 3 only");
  await user.keyboard("{Enter}");
  expect(screen.getByRole("dialog", { name: "Command palette" })).toBeDefined();
  expect(screen.getByRole("combobox", { name: "Search Run 3 and commands" })).toBeDefined();
  expect((screen.getByRole("combobox") as HTMLInputElement).value).toBe("");
  expect(screen.getByText("Searching Run 3")).toBeDefined();

  await user.keyboard("{Backspace}");
  expect(screen.getByRole("combobox", { name: "Search commands and investigations" })).toBeDefined();
});

test("Backspace with text in the field edits the text and keeps the scope", async () => {
  const user = userEvent.setup();
  setup(<Scoped scope={scopeOf("run-3", "Run 3", [item("run-3", "fd_1", "Seq Scan dominates")])} />);
  fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });
  await user.type(screen.getByRole("combobox"), "se{Backspace}");
  expect(screen.getByRole("combobox", { name: "Search Run 3 and commands" })).toBeDefined();
});

let setHarnessScope: (scope: RunScope) => void = () => {};
function ScopeHarness({ initial }: { initial: RunScope }) {
  const [scope, setScope] = useState(initial);
  useEffect(() => {
    setHarnessScope = setScope;
  }, [setScope]);
  useRunScope(scope);
  return null;
}

test("run-scoped results follow the selected run: a run still loading shows its loading state, never the previous run's results", () => {
  setup(<ScopeHarness initial={scopeOf("run-3", "Run 3", [item("run-3", "fd_1", "Seq Scan dominates")])} />);
  fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });
  expect(screen.getByRole("option", { name: /Seq Scan dominates/ })).toBeDefined();

  act(() => setHarnessScope(scopeOf("run-4", "Run 4", [], true)));
  expect(screen.queryByRole("option", { name: /Seq Scan dominates/ })).toBeNull();
  expect(screen.getByRole("combobox", { name: "Search Run 4 and commands" })).toBeDefined();
  expect(screen.getByRole("status", { name: "Loading Run 4" })).toBeDefined();

  // Items stamped with another run are never shown, even if passed by mistake.
  act(() => setHarnessScope(scopeOf("run-4", "Run 4", [item("run-3", "fd_1", "Seq Scan dominates"), item("run-4", "fd_9", "Hash join spills")])));
  expect(screen.queryByRole("option", { name: /Seq Scan dominates/ })).toBeNull();
  expect(screen.getByRole("option", { name: /Hash join spills/ })).toBeDefined();
});

test("a run with nothing matching says so; long groups are capped and say how many are hidden", async () => {
  const user = userEvent.setup();
  const many = Array.from({ length: 7 }, (_, i) => item("run-3", `fd_${i}`, `Finding number ${i}`));
  setup(<Scoped scope={scopeOf("run-3", "Run 3", many)} />);
  fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });
  const findings = screen.getByRole("group", { name: "Findings" });
  expect(within(findings).getAllByRole("option")).toHaveLength(5);
  expect(findings.textContent).toContain("2 more · type to narrow");

  await user.type(screen.getByRole("combobox"), "zzzz");
  expect(screen.getByText("Nothing in Run 3 matches.")).toBeDefined();
});

test("Esc from a scoped palette still returns focus to where it was", async () => {
  setup(<Scoped scope={scopeOf("run-3", "Run 3", [item("run-3", "fd_1", "Seq Scan dominates")])} />);
  const before = screen.getByRole("button", { name: "before" });
  before.focus();
  fireEvent.keyDown(before, { key: "k", ctrlKey: true });
  await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("combobox")));
  fireEvent.keyDown(screen.getByRole("combobox"), { key: "Escape" });
  expect(document.activeElement).toBe(before);
});

// --- Workstream 3 polish ---

test("in a run scope, run results come first, then this investigation's commands, then Actions and Navigate", () => {
  setup(
    <>
      <Contextual run={vi.fn()} />
      <Scoped scope={scopeOf("run-3", "Run 3", [item("run-3", "fd_1", "Seq Scan dominates"), item("run-3", "hy_1", "Index missing", vi.fn(), "Hypotheses")])} />
    </>,
  );
  fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });
  const groups = within(screen.getByRole("listbox")).getAllByRole("group").map((g) => g.getAttribute("aria-labelledby") && document.getElementById(g.getAttribute("aria-labelledby") ?? "")?.textContent);
  expect(groups).toEqual(["Findings", "Hypotheses", "This investigation", "Actions", "Navigate"]);
});

test("outside a run scope the command groups keep their order", async () => {
  setup(<Contextual run={vi.fn()} />);
  fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });
  await screen.findByRole("option", { name: /Recent orders run/ });
  const groups = within(screen.getByRole("listbox")).getAllByRole("group").map((g) => document.getElementById(g.getAttribute("aria-labelledby") ?? "")?.textContent);
  expect(groups).toEqual(["Actions", "Navigate", "This investigation", "Recent investigations"]);
});

test("investigations sharing a title show their creation time so they can be told apart", async () => {
  vi.mocked(listInvestigations).mockResolvedValue({
    items: [
      { id: "a1", title: "Slow orders page", objective: "o", modes: ["offline"], createdAt: "2026-10-20T09:00:00Z", latestRun: null },
      { id: "b2", title: "Slow orders page", objective: "o", modes: ["offline"], createdAt: "2026-10-22T16:45:00Z", latestRun: null },
      { id: "c3", title: "Unique title", objective: "o", modes: ["offline"], createdAt: "2026-10-22T16:45:00Z", latestRun: null },
    ],
    nextCursor: null,
  } as unknown as Awaited<ReturnType<typeof listInvestigations>>);
  setup();
  fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });
  const same = await screen.findAllByRole("option", { name: /Slow orders page/ });
  expect(same).toHaveLength(2);
  expect(same[0]?.textContent).toMatch(/Oct 20/);
  expect(same[1]?.textContent).toMatch(/Oct 22/);
  expect(screen.getByRole("option", { name: /Unique title/ }).textContent).not.toMatch(/Oct/);
  // No extra request: the detail comes from the list response.
  expect(vi.mocked(listInvestigations)).toHaveBeenCalledTimes(1);
});

test("an empty run-scoped search offers searching all investigations, keeping the query", async () => {
  vi.mocked(listInvestigations).mockResolvedValue(page([{ id: "inv-7", title: "Hash join spills" }]));
  const user = userEvent.setup();
  setup(<Scoped scope={scopeOf("run-3", "Run 3", [item("run-3", "fd_1", "Seq Scan dominates")])} />);
  fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });
  const combo = screen.getByRole("combobox");
  await user.type(combo, "hash join");

  expect(screen.getByText("Nothing in Run 3 matches.")).toBeDefined();
  const widen = screen.getByRole("option", { name: "Search all investigations for “hash join”" });
  expect(combo.getAttribute("aria-activedescendant")).toBe(widen.id);
  await user.keyboard("{Enter}");

  expect(screen.getByRole("combobox", { name: "Search commands and investigations" })).toBeDefined();
  expect((screen.getByRole("combobox") as HTMLInputElement).value).toBe("hash join");
  expect(screen.getByText("Searching everywhere")).toBeDefined();
  expect(await screen.findByRole("option", { name: /Hash join spills/ })).toBeDefined();
  expect(vi.mocked(listInvestigations)).toHaveBeenLastCalledWith({ q: "hash join", limit: 8 }, expect.anything());
});

test("leaving the scope resets the active option to the first result", async () => {
  const user = userEvent.setup();
  const many = Array.from({ length: 3 }, (_, i) => item("run-3", `fd_${i}`, `Finding number ${i}`));
  setup(<Scoped scope={scopeOf("run-3", "Run 3", many)} />);
  fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });
  await user.keyboard("{ArrowDown}{ArrowDown}");
  await user.click(screen.getByRole("button", { name: "Leave Run 3 scope and search everywhere" }));
  const combo = screen.getByRole("combobox");
  expect(combo.getAttribute("aria-activedescendant")).toBe(screen.getAllByRole("option")[0]?.id);
});

test("arrows keep the active option scrolled into view, and a pointer resting on the list does not steal it", async () => {
  const scrolled: string[] = [];
  const original = Element.prototype.scrollIntoView;
  Element.prototype.scrollIntoView = function (this: Element) {
    scrolled.push(this.id);
  };
  try {
    const user = userEvent.setup();
    const many = Array.from({ length: 12 }, (_, i) => item("run-3", `fd_${i}`, `Finding number ${i}`));
    setup(<Scoped scope={scopeOf("run-3", "Run 3", many)} />);
    fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });
    const combo = screen.getByRole("combobox");
    const options = () => screen.getAllByRole("option");

    fireEvent.mouseMove(options()[0] as HTMLElement, { clientX: 10, clientY: 10 });
    await user.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}");
    expect(combo.getAttribute("aria-activedescendant")).toBe(options()[3]?.id);
    expect(scrolled.at(-1)).toBe(options()[3]?.id);
    // Browsers replay a mousemove at the same point after scrolling; it must not move the selection.
    fireEvent.mouseMove(options()[0] as HTMLElement, { clientX: 10, clientY: 10 });
    expect(combo.getAttribute("aria-activedescendant")).toBe(options()[3]?.id);
    // A real pointer move still selects what is under it.
    fireEvent.mouseMove(options()[1] as HTMLElement, { clientX: 10, clientY: 40 });
    expect(combo.getAttribute("aria-activedescendant")).toBe(options()[1]?.id);

    // End wraps to the last option, ArrowDown wraps to the first; Enter runs exactly the highlighted one.
    await user.keyboard("{End}{ArrowDown}");
    expect(combo.getAttribute("aria-activedescendant")).toBe(options()[0]?.id);
    await user.keyboard("{Enter}");
    expect(many[0]?.run).toHaveBeenCalledTimes(1);
    expect(many.slice(1).every((m) => vi.mocked(m.run).mock.calls.length === 0)).toBe(true);
  } finally {
    Element.prototype.scrollIntoView = original;
  }
});

test("a pointer choice tells the run-scoped item it came from the pointer; Enter says keyboard", async () => {
  const run = vi.fn();
  const user = userEvent.setup();
  setup(<Scoped scope={scopeOf("run-3", "Run 3", [item("run-3", "fd_1", "Seq Scan dominates", run)])} />);
  fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });
  await user.click(screen.getByRole("option", { name: /Seq Scan dominates/ }));
  expect(run).toHaveBeenLastCalledWith("pointer");

  fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });
  await user.keyboard("{Enter}");
  expect(run).toHaveBeenLastCalledWith("keyboard");
});

test("the creation time of a same-titled investigation is its own untruncated part of the detail", async () => {
  vi.mocked(listInvestigations).mockResolvedValue({
    items: ["a1", "b2"].map((id, i) => ({ id, title: "Same", objective: "o", modes: ["offline"], createdAt: `2026-10-2${i}T09:00:00Z`, latestRun: null })),
    nextCursor: null,
  } as unknown as Awaited<ReturnType<typeof listInvestigations>>);
  setup();
  fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });
  const [first] = await screen.findAllByRole("option", { name: /Same/ });
  const stamp = within(first as HTMLElement).getByText(/Oct 20/);
  expect(stamp.className).toContain("shrink-0");
  expect(stamp.className).not.toContain("truncate");
});
