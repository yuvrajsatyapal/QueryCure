import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { ILLUSTRATIVE_BENCH } from "@/lib/landing/bench";
import Page from "../page";

// jsdom lacks the observers and animation APIs the landing sections use; these inert stubs never fire,
// so the page renders its static, first-frame state.
class Inert {
  observe() {}
  unobserve() {}
  disconnect() {}
}
beforeEach(() => {
  vi.stubGlobal("IntersectionObserver", Inert);
  vi.stubGlobal("ResizeObserver", Inert);
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {} }));
  Element.prototype.animate = () => ({ finished: new Promise(() => {}), cancel() {}, pause() {}, play() {} }) as unknown as Animation;
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("landing page states the product and links only to real app routes", () => {
  render(<Page />);
  expect(screen.getByRole("heading", { level: 1, name: /Find out why your PostgreSQL queries are slow/ })).toBeDefined();
  for (const link of screen.getAllByRole("link")) {
    const href = link.getAttribute("href") ?? "";
    if (href.startsWith("https://github.com/yuvrajsatyapal/QueryCure")) continue;
    expect(["/", "/demo", "/app", "/sign-in"].includes(href) || href.startsWith("#"), `unexpected link ${href}`).toBe(true);
  }
  expect(screen.getAllByRole("link", { name: /Explore Demo/ })[0]?.getAttribute("href")).toBe("/demo");
  expect(screen.getAllByRole("link", { name: "Open QueryCure" })[0]?.getAttribute("href")).toBe("/app");
  expect(screen.getByRole("link", { name: "Get Started" }).getAttribute("href")).toBe("/sign-in");
  // The public-demo limits are stated, not implied.
  expect(screen.getByText(/The public demo uses prerecorded investigations, labelled as such/)).toBeDefined();
});

test("the X-Ray result is labelled as a separate illustrative benchmark, never a measurement of the plan", () => {
  const { container } = render(<Page />);
  const xray = container.querySelector(".xr") as HTMLElement;
  const x = within(xray);
  expect(x.getByText("Illustrative verified outcome")).toBeDefined();
  expect(x.getByText(/Separate illustrative benchmark, not this plan/)).toBeDefined();
  expect(x.getByText("From a separate illustrative benchmark, not a measurement of this plan")).toBeDefined();
  expect(x.getByText(`${ILLUSTRATIVE_BENCH.ratio.toFixed(2)}×`)).toBeDefined();
  expect(x.getByText(/Illustrative example, not a live benchmark/)).toBeDefined();
  // No unqualified verification claim inside the X-Ray.
  expect(x.queryByText(/^Verified within tested scope$/)).toBeNull();
});

test("Before/After is a pressed-state toggle", () => {
  render(<Page />);
  const group = screen.getByRole("group", { name: "Execution plan" });
  const before = within(group).getByRole("button", { name: "Before" });
  const after = within(group).getByRole("button", { name: "After" });
  expect(before.getAttribute("aria-pressed")).toBe("true");
  fireEvent.click(after);
  expect(after.getAttribute("aria-pressed")).toBe("true");
  expect(before.getAttribute("aria-pressed")).toBe("false");
});
