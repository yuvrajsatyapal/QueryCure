import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useMemo, type ReactNode } from "react";
import { renderWithQuery } from "@/test/render";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }), usePathname: () => "/app" }));
vi.mock("@/lib/api/investigations", () => ({
  investigationKeys: { list: (p: object) => ["investigations", "list", p] },
  listInvestigations: vi.fn(),
}));

import { listInvestigations } from "@/lib/api/investigations";
import { CommandProvider, useContextCommands, type Command } from "../CommandProvider";

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
