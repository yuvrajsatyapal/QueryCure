import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MEASURED, formatMs } from "@/lib/landing/xrayMeasured";
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
    // Dataset citation required by the CC BY 4.0 licence.
    if (href === "https://doi.org/10.24432/C5CG6D") continue;
    expect(["/", "/app", "/sign-in"].includes(href) || href.startsWith("#"), `unexpected link ${href}`).toBe(true);
  }
  expect(screen.queryByRole("link", { name: /demo/i })).toBeNull();
  expect(screen.getAllByRole("link", { name: "Open QueryCure" })[0]?.getAttribute("href")).toBe("/app");
  expect(screen.getByRole("link", { name: "Get Started" }).getAttribute("href")).toBe("/sign-in");
});

test("the X-Ray shows the recorded PostgreSQL run and says what it is and is not", () => {
  const { container } = render(<Page />);
  const xray = container.querySelector(".xr") as HTMLElement;
  const x = within(xray);
  expect(x.getByText(`Measured on ${MEASURED.engine}`)).toBeDefined();
  expect(x.getByText(/independently of QueryCure.s investigation verdict/)).toBeDefined();
  expect(x.getByText(`≈${Math.round(MEASURED.ratio).toLocaleString("en-US")}×`)).toBeDefined();
  expect(x.getByText("query execution speedup")).toBeDefined();
  expect(x.getByText("6 µs")).toBeDefined();
  expect(x.getByText(/After measurement rounded to 1 µs; speedup is approximate/)).toBeDefined();
  expect(x.getByText(/Server-side execution time only; excludes network and client overhead/)).toBeDefined();
  expect(x.getByText(/synthetic/i, { selector: ".xr-foot" })).toBeDefined();
  // No seeded-benchmark wording, and no unqualified verification claim, inside the X-Ray.
  expect(xray.textContent).not.toMatch(/illustrative/i);
  expect(x.queryByText(/^Verified within tested scope$/)).toBeNull();
});

test("every number in the X-Ray comes from the recorded run", () => {
  const { container } = render(<Page />);
  const text = (container.querySelector(".xr") as HTMLElement).textContent ?? "";
  expect(text).toContain(`${MEASURED.before.examined.toLocaleString("en-US")} examined`);
  expect(text).toContain(`${MEASURED.before.discarded.toLocaleString("en-US")} rows read`);
  expect(text).toContain(`range ${formatMs(MEASURED.before.minMs)} – ${formatMs(MEASURED.before.maxMs)} ms`);
  expect(text).toContain(`median of ${MEASURED.runs} runs per plan`);
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
