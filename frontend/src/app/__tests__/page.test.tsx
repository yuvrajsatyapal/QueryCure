import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { ApiError } from "@/lib/api/client";
import { createSession, getAuthOptions, getMe } from "@/lib/api/session";
import { renderWithQuery } from "@/test/render";
import { MEASURED, formatMs } from "@/lib/landing/xrayMeasured";
import Page from "../page";

vi.mock("@/lib/api/session", () => ({ getMe: vi.fn(), createSession: vi.fn(), getAuthOptions: vi.fn(), logout: vi.fn() }));

// jsdom lacks the observers and animation APIs the landing sections use; these inert stubs never fire,
// so the page renders its static, first-frame state.
class Inert {
  observe() {}
  unobserve() {}
  disconnect() {}
}
beforeEach(() => {
  // Signed out, open deployment, unless a test says otherwise.
  vi.mocked(getMe).mockRejectedValue(new ApiError("UNAUTHENTICATED", "no", 401, [], null));
  vi.mocked(getAuthOptions).mockResolvedValue({ restrictedAccess: false, githubLogin: true, googleLogin: true });
  vi.stubGlobal("IntersectionObserver", Inert);
  vi.stubGlobal("ResizeObserver", Inert);
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {} }));
  Element.prototype.animate = () => ({ finished: new Promise(() => {}), cancel() {}, pause() {}, play() {} }) as unknown as Animation;
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.resetAllMocks();
});

test("landing page states the product and links only to real app routes", async () => {
  renderWithQuery(<Page />);
  expect(screen.getByRole("heading", { level: 1, name: /Find out why your PostgreSQL queries are slow/ })).toBeDefined();
  await waitFor(() => expect(screen.getAllByRole("link", { name: "Get started" }).length).toBeGreaterThan(0));
  for (const link of screen.getAllByRole("link")) {
    const href = link.getAttribute("href") ?? "";
    if (href.startsWith("https://github.com/yuvrajsatyapal/QueryCure")) continue;
    // Dataset citation required by the CC BY 4.0 licence.
    if (href === "https://doi.org/10.24432/C5CG6D") continue;
    expect(["/", "/app", "/sign-in"].includes(href) || href.startsWith("#"), `unexpected link ${href}`).toBe(true);
  }
  expect(screen.queryByRole("link", { name: /demo/i })).toBeNull();
  expect(screen.getAllByRole("link", { name: "Open QueryCure" })[0]?.getAttribute("href")).toBe("/app");
  expect(screen.getAllByRole("link", { name: "Get started" })[0]?.getAttribute("href")).toBe("/sign-in");
});

test("a signed-in visitor sees the dashboard entry point, never Get started or Sign in", async () => {
  vi.mocked(getMe).mockReset().mockResolvedValue({ user: { id: "u1", kind: "oauth", displayName: "Ada Lovelace" }, profile: "demo", features: {} } as never);
  renderWithQuery(<Page />);
  await waitFor(() => expect(screen.getAllByRole("link", { name: "Open dashboard" }).length).toBeGreaterThan(0));
  expect(screen.queryByRole("link", { name: /Get started|Sign in|Open QueryCure/ })).toBeNull();
  expect(screen.getByRole("button", { name: "Sign out" })).toBeDefined();
  expect(createSession).not.toHaveBeenCalled();
});

test("before the session is known the page makes no account claim and starts no session", () => {
  vi.mocked(getMe).mockReset().mockReturnValue(new Promise(() => {}));
  renderWithQuery(<Page />);
  expect(screen.queryByRole("link", { name: /Open QueryCure|Get started|Sign in|Open dashboard/ })).toBeNull();
  expect(createSession).not.toHaveBeenCalled();
});

test("the landing page stays a server render; only the auth slots are client components", () => {
  const read = (file: string) => readFileSync(resolve(__dirname, "../../components/landing", file), "utf8");
  expect(readFileSync(resolve(__dirname, "../page.tsx"), "utf8")).not.toMatch(/^["']use client["']/m);
  expect(read("StaticSections.tsx")).not.toMatch(/^["']use client["']/m);
  expect(read("LandingAuth.tsx")).toMatch(/^["']use client["']/m);
  // The landing page reads the session; it never creates one.
  expect(read("LandingAuth.tsx") + read("useLandingAuth.ts")).not.toMatch(/createSession/);
});

test("the X-Ray shows the recorded PostgreSQL run and says what it is and is not", () => {
  const { container } = renderWithQuery(<Page />);
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
  const { container } = renderWithQuery(<Page />);
  const text = (container.querySelector(".xr") as HTMLElement).textContent ?? "";
  expect(text).toContain(`${MEASURED.before.examined.toLocaleString("en-US")} examined`);
  expect(text).toContain(`${MEASURED.before.discarded.toLocaleString("en-US")} rows read`);
  expect(text).toContain(`range ${formatMs(MEASURED.before.minMs)} – ${formatMs(MEASURED.before.maxMs)} ms`);
  expect(text).toContain(`median of ${MEASURED.runs} runs per plan`);
});

test("Before/After is a pressed-state toggle", () => {
  renderWithQuery(<Page />);
  const group = screen.getByRole("group", { name: "Execution plan" });
  const before = within(group).getByRole("button", { name: "Before" });
  const after = within(group).getByRole("button", { name: "After" });
  expect(before.getAttribute("aria-pressed")).toBe("true");
  fireEvent.click(after);
  expect(after.getAttribute("aria-pressed")).toBe("true");
  expect(before.getAttribute("aria-pressed")).toBe("false");
});
