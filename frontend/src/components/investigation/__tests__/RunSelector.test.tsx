import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
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
    outcome: "verified_recommendation",
    parentRunId: null,
    replay: null,
    finalized: true,
    createdAt: "2026-10-12T10:00:00Z",
    startedAt: null,
    finishedAt: null,
    ...o,
  }) as RunSummary;

const original = run({});
const replay = run({
  id: "run-2",
  runNumber: 2,
  kind: "experiment_replay",
  outcome: null,
  parentRunId: "run-1",
  replay: { attemptId: "att-1", status: "reproduced_with_drift", sourceExperimentId: "exp-1" },
});
const again = run({ id: "run-3", runNumber: 3, kind: "reinvestigation", status: "running", outcome: null, parentRunId: "run-1", finalized: false });
const all = [original, replay, again];

function setup(runs: RunSummary[], selectedId: string) {
  const user = userEvent.setup();
  const onSelect = vi.fn();
  render(
    <div>
      <button type="button">before</button>
      <RunSelector runs={runs} selectedId={selectedId} onSelect={onSelect} />
      <button type="button">after</button>
    </div>,
  );
  const trigger = screen.getByRole("button", { name: /^run \d/ });
  return { user, onSelect, trigger };
}

const menu = () => screen.getByRole("menu", { name: "Runs of this investigation" });
const items = () => within(menu()).getAllByRole("menuitemradio");

test("the trigger names the selected run and says how many there are", () => {
  const { trigger } = setup(all, "run-2");
  expect(trigger.textContent).toContain("run 2 · Experiment replay of run #1");
  expect(trigger.textContent).toContain("of 3");
  expect(trigger.getAttribute("aria-haspopup")).toBe("menu");
  expect(trigger.getAttribute("aria-expanded")).toBe("false");
  expect(screen.queryByRole("menu")).toBeNull();
});

test("runs are grouped: investigation runs (original and re-investigations), then experiment replays", async () => {
  const { user, trigger } = setup(all, "run-1");
  await user.click(trigger);
  const groups = within(menu()).getAllByRole("group");
  expect(groups.map((g) => g.getAttribute("aria-label") ?? document.getElementById(g.getAttribute("aria-labelledby") ?? "")?.textContent)).toEqual([
    "Investigation runs",
    "Experiment replays",
  ]);
  const [investigations, replays] = groups;
  // Newest first within a group.
  expect(within(investigations!).getAllByRole("menuitemradio").map((i) => i.textContent)).toEqual([
    expect.stringMatching(/^#3AI re-investigationof run #1/),
    expect.stringMatching(/^#1Original run/),
  ]);
  expect(within(replays!).getAllByRole("menuitemradio").map((i) => i.textContent)).toEqual([expect.stringMatching(/^#2Experiment replayof run #1/)]);
});

test("each run says its recorded status, outcome or replay result, children, and age", async () => {
  const { user, trigger } = setup(all, "run-1");
  await user.click(trigger);
  const [three, one, two] = items();
  expect(three?.textContent).toContain("Running");
  expect(one?.textContent).toContain("Completed");
  expect(one?.textContent).toContain("verified recommendation");
  expect(one?.textContent).toContain("followed by #2 (experiment replay), #3 (ai re-investigation)");
  expect(two?.textContent).toContain("reproduced with drift");
  const time = one?.querySelector("time");
  expect(time?.getAttribute("dateTime")).toBe("2026-10-12T10:00:00Z");
  expect(time?.getAttribute("title")).toBeTruthy();
});

test("status orbs in the menu are still: the selector only has recorded run metadata", async () => {
  const { user, trigger } = setup(all, "run-1");
  await user.click(trigger);
  const orbs = menu().querySelectorAll("[data-motion]");
  expect(orbs.length).toBe(3);
  for (const orb of orbs) expect(orb.getAttribute("data-motion")).toBe("still");
  expect(items()[0]?.querySelector('[data-tone="running"]')).not.toBeNull();
});

test("the selected run is checked, marked with a check icon, and not by color alone", async () => {
  const { user, trigger } = setup(all, "run-2");
  await user.click(trigger);
  const checked = items().filter((i) => i.getAttribute("aria-checked") === "true");
  expect(checked.map((i) => i.textContent)).toEqual([expect.stringMatching(/^#2/)]);
  expect(checked[0]?.querySelector("[data-selected-mark]")).not.toBeNull();
  for (const i of items().filter((x) => x !== checked[0])) {
    expect(i.getAttribute("aria-checked")).toBe("false");
    expect(i.querySelector("[data-selected-mark]")).toBeNull();
  }
});

test("a parent that is no longer listed is said so, not hidden", async () => {
  const orphan = run({ id: "run-5", runNumber: 5, kind: "experiment_replay", parentRunId: "gone", replay: { attemptId: "a", status: "inconclusive", sourceExperimentId: "e" } });
  const { user, trigger } = setup([original, orphan], "run-5");
  expect(trigger.textContent).toContain("run 5 · Experiment replay of a run that is no longer available");
  await user.click(trigger);
  expect(items()[1]?.textContent).toContain("of a run that is no longer available");
  expect(items()[1]?.textContent).toContain("replay inconclusive");
});

test("only groups with runs are shown", async () => {
  const reinvestigation = run({ id: "run-2", runNumber: 2, kind: "reinvestigation", parentRunId: "run-1" });
  const { user, trigger } = setup([original, reinvestigation], "run-1");
  await user.click(trigger);
  expect(within(menu()).getAllByRole("group")).toHaveLength(1);
  expect(within(menu()).queryByText("Experiment replays")).toBeNull();
});

test("a single run is a label, not a dropdown; no runs renders nothing", () => {
  const { container, rerender } = render(<RunSelector runs={[original]} selectedId="run-1" onSelect={vi.fn()} />);
  expect(screen.getByText("run 1 · Original run")).toBeDefined();
  expect(screen.queryByRole("button")).toBeNull();
  rerender(<RunSelector runs={[]} selectedId={null} onSelect={vi.fn()} />);
  expect(container.innerHTML).toBe("");
});

test("opening moves focus to the selected run; arrows (wrapping), Home and End move between runs across groups", async () => {
  const { user, trigger } = setup(all, "run-1");
  trigger.focus();
  await user.keyboard("{Enter}");
  expect(trigger.getAttribute("aria-expanded")).toBe("true");
  const [three, one, two] = items();
  expect(document.activeElement).toBe(one);
  await user.keyboard("{ArrowDown}");
  expect(document.activeElement).toBe(two);
  await user.keyboard("{ArrowDown}");
  expect(document.activeElement).toBe(three);
  await user.keyboard("{ArrowUp}");
  expect(document.activeElement).toBe(two);
  await user.keyboard("{Home}");
  expect(document.activeElement).toBe(three);
  await user.keyboard("{End}");
  expect(document.activeElement).toBe(two);
  // Roving tab stop: only the selected run is in the tab order, so the scrolling list is keyboard-reachable.
  expect(items().filter((i) => i.tabIndex === 0)).toEqual([one]);
});

test("Space opens too, and ArrowDown on the trigger opens it", async () => {
  const { user, trigger } = setup(all, "run-2");
  trigger.focus();
  await user.keyboard(" ");
  expect(document.activeElement?.textContent).toMatch(/^#2/);
  await user.keyboard("{Escape}");
  await user.keyboard("{ArrowDown}");
  expect(screen.getByRole("menu")).toBeDefined();
  expect(document.activeElement?.textContent).toMatch(/^#2/);
});

test("Enter or Space selects the focused run, closes, and returns focus to the trigger", async () => {
  const { user, onSelect, trigger } = setup(all, "run-1");
  trigger.focus();
  await user.keyboard("{Enter}{ArrowDown}{Enter}");
  expect(onSelect).toHaveBeenCalledWith("run-2");
  expect(screen.queryByRole("menu")).toBeNull();
  expect(document.activeElement).toBe(trigger);
  await user.keyboard("{Enter}{Home} ");
  expect(onSelect).toHaveBeenLastCalledWith("run-3");
});

test("pointer selection reports the run and closes", async () => {
  const { user, onSelect, trigger } = setup(all, "run-1");
  await user.click(trigger);
  await user.click(screen.getByRole("menuitemradio", { name: /^#2/ }));
  expect(onSelect).toHaveBeenCalledWith("run-2");
  expect(screen.queryByRole("menu")).toBeNull();
});

test("Escape closes the menu and returns focus to the trigger", async () => {
  const { user, trigger } = setup(all, "run-1");
  await user.click(trigger);
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("menu")).toBeNull();
  expect(document.activeElement).toBe(trigger);
});

test("Tab closes the menu and continues from the trigger, without trapping focus", async () => {
  const { user, trigger } = setup(all, "run-1");
  await user.click(trigger);
  await user.tab();
  expect(screen.queryByRole("menu")).toBeNull();
  expect(document.activeElement?.textContent).not.toMatch(/^#/);
  expect(document.body.contains(document.activeElement)).toBe(true);
});

test("a click outside closes the menu", async () => {
  const { user, onSelect, trigger } = setup(all, "run-1");
  await user.click(trigger);
  await user.click(screen.getByRole("button", { name: "after" }));
  expect(screen.queryByRole("menu")).toBeNull();
  expect(onSelect).not.toHaveBeenCalled();
});

test("a long list scrolls inside the menu, not the page", async () => {
  const many = Array.from({ length: 30 }, (_, i) =>
    run({ id: `run-${i + 1}`, runNumber: i + 1, kind: i === 0 ? "initial" : "reinvestigation", parentRunId: i === 0 ? null : "run-1" }),
  );
  const { user, trigger } = setup(many, "run-30");
  await user.click(trigger);
  expect(items()).toHaveLength(30);
  const scroller = menu().closest("[data-run-menu]");
  expect(scroller?.className).toMatch(/overflow-y-auto/);
  expect(scroller?.className).toMatch(/overscroll-contain/);
});

test("the selected sealed run's report link sits beside the trigger, outside the menu", async () => {
  const { user, trigger } = setup(all, "run-2");
  const link = screen.getByRole("link", { name: "Open this run's report" });
  expect(link.getAttribute("href")).toBe("/app/reports/run-2");
  await user.click(trigger);
  expect(within(menu()).queryByRole("link")).toBeNull();
});

test("an unsealed run offers no report link", () => {
  setup(all, "run-3");
  expect(screen.queryByRole("link", { name: "Open this run's report" })).toBeNull();
});

test("a long trigger label wraps instead of widening the page", () => {
  const orphan = run({ id: "run-5", runNumber: 5, kind: "experiment_replay", parentRunId: "gone" });
  const { trigger } = setup([original, orphan], "run-5");
  expect(trigger.className).toMatch(/whitespace-normal/);
  expect(trigger.className).toMatch(/max-w-full/);
});

test("a historical replay with a stored verified outcome is tagged legacy; the outcome text is kept", async () => {
  const legacy = run({ id: "run-4", runNumber: 4, kind: "experiment_replay", parentRunId: "run-1", outcome: "verified_recommendation" });
  const user = userEvent.setup();
  render(
    <RunSelector runs={[original, legacy]} selectedId="run-1" onSelect={vi.fn()} replayReports={new Map([["run-4", { builderVersion: "report-builder@1", replayTitle: null }]])} />,
  );
  await user.click(screen.getByRole("button", { name: /^run \d/ }));
  const [row1, row4] = items();
  expect(row4?.textContent).toContain("verified recommendation");
  const tag = within(row4 as HTMLElement).getByText("legacy replay");
  expect(tag.getAttribute("title")).toBe(
    "Earlier replay classification. This report used an older outcome rule based on the replay's measurement, not its comparison with the original investigation. It does not independently verify a recommendation.",
  );
  expect(within(row1 as HTMLElement).queryByText("legacy replay")).toBeNull();
});

test("a schema-2 replay that reproduced the original says so, never 'verified recommendation'; the original run keeps its label", async () => {
  const replay = run({ id: "run-4", runNumber: 4, kind: "experiment_replay", parentRunId: "run-1", outcome: "verified_recommendation" });
  const user = userEvent.setup();
  render(
    <RunSelector
      runs={[original, replay]}
      selectedId="run-1"
      onSelect={vi.fn()}
      replayReports={new Map([["run-4", { builderVersion: "report-builder@2", replayTitle: "Original recommendation reproduced" }]])}
    />,
  );
  await user.click(screen.getByRole("button", { name: /^run \d/ }));
  const [row1, row4] = items();
  expect(row4?.textContent).toContain("· Original recommendation reproduced");
  expect(row4?.textContent?.toLowerCase()).not.toContain("verified recommendation");
  expect(within(row4 as HTMLElement).queryByText("legacy replay")).toBeNull();
  expect(row1?.textContent).toContain(original.outcome!.replaceAll("_", " "));
});

test("a sealed verified replay whose report is not loaded shows no outcome yet", async () => {
  const replay = run({ id: "run-4", runNumber: 4, kind: "experiment_replay", parentRunId: "run-1", outcome: "verified_recommendation" });
  const user = userEvent.setup();
  render(<RunSelector runs={[original, replay]} selectedId="run-1" onSelect={vi.fn()} />);
  await user.click(screen.getByRole("button", { name: /^run \d/ }));
  expect(items()[1]?.textContent?.toLowerCase()).not.toContain("verified recommendation");
});
