import { afterEach, describe, expect, test } from "vitest";
import { createSequenceMatcher, filterCommands, isTypingTarget } from "../keyboard";

afterEach(() => {
  document.body.innerHTML = "";
});

describe("isTypingTarget", () => {
  test("text fields, selects, contenteditable and CodeMirror count as typing", () => {
    document.body.innerHTML = `
      <input id="text" /><input id="box" type="checkbox" /><textarea id="area"></textarea><select id="sel"></select>
      <div id="ce" contenteditable="true"></div>
      <div class="cm-editor"><div id="cm" class="cm-content"></div></div>
      <button id="btn"></button>`;
    const el = (id: string) => document.getElementById(id);
    expect(isTypingTarget(el("text"))).toBe(true);
    expect(isTypingTarget(el("area"))).toBe(true);
    expect(isTypingTarget(el("sel"))).toBe(true);
    expect(isTypingTarget(el("cm"))).toBe(true);
    expect(isTypingTarget(el("box"))).toBe(false);
    expect(isTypingTarget(el("btn"))).toBe(false);
    expect(isTypingTarget(null)).toBe(false);
  });
});

describe("createSequenceMatcher", () => {
  const bindings = [
    { id: "dashboard", keys: ["g", "d"] },
    { id: "next", keys: ["]"] },
    { id: "create", keys: ["c"] },
  ];

  test("single keys and two-key sequences resolve to their command", () => {
    let now = 0;
    const match = createSequenceMatcher(() => bindings, 1000, () => now);
    expect(match("]")).toBe("next");
    expect(match("g")).toBeNull();
    now = 500;
    expect(match("d")).toBe("dashboard");
  });

  test("a sequence expires after the timeout and an unknown key resets it", () => {
    let now = 0;
    const match = createSequenceMatcher(() => bindings, 1000, () => now);
    match("g");
    now = 1500;
    expect(match("d")).toBeNull();
    match("g");
    expect(match("x")).toBeNull();
    // After a reset the single-key binding still works.
    expect(match("c")).toBe("create");
  });

  test("bindings are read on every key so contextual commands can come and go", () => {
    let current = bindings;
    const match = createSequenceMatcher(() => current, 1000, () => 0);
    expect(match("]")).toBe("next");
    current = [];
    expect(match("]")).toBeNull();
  });
});

describe("filterCommands", () => {
  const commands = [
    { id: "new", label: "New investigation", keywords: ["create", "start"] },
    { id: "history", label: "Go to History" },
    { id: "dark", label: "Switch to dark theme" },
  ];

  test("an empty query keeps every command in order", () => {
    expect(filterCommands(commands, "  ").map((c) => c.id)).toEqual(["new", "history", "dark"]);
  });

  test("every query word must appear, case-insensitively, in the label or keywords", () => {
    expect(filterCommands(commands, "HIST").map((c) => c.id)).toEqual(["history"]);
    expect(filterCommands(commands, "dark theme").map((c) => c.id)).toEqual(["dark"]);
    expect(filterCommands(commands, "create").map((c) => c.id)).toEqual(["new"]);
    expect(filterCommands(commands, "dark history")).toEqual([]);
  });
});
