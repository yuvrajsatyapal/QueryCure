import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, expect, test } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { moving } from "@/test/motion";
import { RunStatusPill, StatusIcon, StatusOrb, StatusPill, type Tone } from "../StatusPill";

afterEach(cleanup);

const TONES: Tone[] = ["running", "success", "failed", "warning", "approval", "neutral"];

test("an orb is still unless it is told the activity is live", () => {
  for (const tone of TONES) {
    const { container } = render(<StatusOrb tone={tone} />);
    expect(moving(container)).toEqual([]);
    cleanup();
  }
});

test("only a running orb moves, and only when live", () => {
  const { container } = render(<StatusOrb tone="running" live />);
  expect(moving(container)).toHaveLength(1);
  cleanup();
  for (const tone of TONES.filter((t) => t !== "running")) {
    const { container: c } = render(<StatusOrb tone={tone} live />);
    expect(moving(c)).toEqual([]);
    cleanup();
  }
});

test("a small orb is a plain dot and never moves, so it never shows motion it cannot draw", () => {
  const { container } = render(<StatusOrb tone="running" live size={8} />);
  expect(moving(container)).toEqual([]);
  expect(container.querySelector(".qc-orb")).toBeNull();
});

test("an orb with a label names its state; without one it is decorative", () => {
  render(
    <>
      <StatusOrb tone="running" live label="Running, live" />
      <StatusOrb tone="success" />
    </>,
  );
  expect(screen.getByRole("img", { name: "Running, live" })).toBeDefined();
  expect(screen.getAllByRole("img")).toHaveLength(1);
});

test("a running status icon no longer spins by default", () => {
  const { container } = render(<StatusIcon tone="running" size={15} />);
  expect(moving(container)).toEqual([]);
  cleanup();
  const { container: live } = render(<StatusIcon tone="running" live size={15} />);
  expect(moving(live)).toHaveLength(1);
});

test("a terminal status icon keeps its own shape and never moves", () => {
  for (const tone of ["success", "failed", "neutral", "warning", "approval"] as Tone[]) {
    const { container } = render(<StatusIcon tone={tone} live />);
    expect(container.querySelector("svg")).not.toBeNull();
    expect(moving(container)).toEqual([]);
    cleanup();
  }
});

test("pills keep their words and are still unless told live", () => {
  const { container } = render(
    <>
      <StatusPill tone="running" label="Running" />
      <RunStatusPill status="running" />
      <RunStatusPill status="completed" />
    </>,
  );
  expect(screen.getAllByText("Running")).toHaveLength(2);
  expect(screen.getByText("Completed")).toBeDefined();
  expect(moving(container)).toEqual([]);
  cleanup();
  const { container: live } = render(<StatusPill tone="running" label="Running" live />);
  expect(moving(live)).toHaveLength(1);
});

test("reduced motion stops every live status animation outright", () => {
  const css = readFileSync(join(process.cwd(), "src/app/globals.css"), "utf8");
  const reduce = [...css.matchAll(/@media \(prefers-reduced-motion: reduce\) \{([\s\S]*?)\n\}/g)].map((m) => m[1]).join("\n");
  for (const cls of [".qc-orb-live", ".qc-seg-moving"]) expect(reduce).toContain(cls);
  expect(reduce).toMatch(/animation: none/);
});
