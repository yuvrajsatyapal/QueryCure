import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { applyTheme } from "./theme";

/** The landing page reads the existing session (`/me`, `/auth/options`) and adapts its calls to action.
 * Sessions are mocked at our own API so the run is deterministic and needs no provider credentials; a real
 * provider sign-in is OAUTH_VERIFICATION_CHECKLIST's job, on a deployed origin. */

const FEATURES = { live_inspection: true, sandbox: true, google_login: true, github_login: true };
const OPEN = { google_login: true, github_login: true, restricted_access: false };
const RESTRICTED = { google_login: true, github_login: false, restricted_access: true };
const ADA = { user: { id: "00000000-0000-4000-8000-0000000000a1", kind: "oauth", display_name: "Ada Lovelace" }, profile: "demo", features: FEATURES };
const UNAUTHENTICATED = { error: { code: "UNAUTHENTICATED", message: "Sign in required.", status: 401 } };
const SIZES = [
  { width: 375, height: 812 },
  { width: 768, height: 1024 },
  { width: 1440, height: 900 },
];

interface Session {
  signedIn: boolean;
}

/** `/me` answers from `session`, so a test can sign the visitor in or out between requests. */
async function mockSession(page: Page, session: Session, options = OPEN) {
  await page.route("**/api/v1/me", (route) => (session.signedIn ? route.fulfill({ json: ADA }) : route.fulfill({ status: 401, json: UNAUTHENTICATED })));
  await page.route("**/api/v1/auth/options", (route) => route.fulfill({ json: options }));
}

/** Requests that would start a session: the landing page must never make one. */
function watchSessionStarts(page: Page): string[] {
  const started: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && new URL(r.url()).pathname === "/api/v1/session") started.push(r.url());
  });
  return started;
}

const noSideways = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
const header = (page: Page) => page.locator("header.nav");
const hero = (page: Page) => page.locator("section.hero");
const closing = (page: Page) => page.locator("section.cta");

test("landing auth - signed out: the calls to action lead into the existing sign-in page, and no session is started", async ({ page }) => {
  const started = watchSessionStarts(page);
  await mockSession(page, { signedIn: false });
  for (const size of SIZES) {
    await page.setViewportSize(size);
    await page.goto("/");
    const at = `${size.width}x${size.height}`;
    await expect(hero(page).getByRole("link", { name: "Get started" }), at).toHaveAttribute("href", "/sign-in");
    await expect(closing(page).getByRole("link", { name: "Get started" }), at).toHaveAttribute("href", "/sign-in");
    await expect(closing(page).getByRole("link", { name: "Open QueryCure" }), at).toHaveAttribute("href", "/app");
    await expect(page.locator("footer").getByRole("link", { name: "Sign in" }), at).toHaveAttribute("href", "/sign-in");
    await expect(page.getByRole("link", { name: /Open dashboard/ }), at).toHaveCount(0);
    expect(await noSideways(page), `${at}: sideways overflow`).toBeLessThanOrEqual(0);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await header(page).getByRole("link", { name: "Sign in" }).click();
  // The bare page: the API's own default destination (the dashboard) applies after sign-in.
  await expect(page).toHaveURL(/\/sign-in$/);
  await expect(page.getByRole("heading", { level: 1, name: "Welcome to QueryCure" })).toBeVisible();
  expect(started).toEqual([]);
});

test("landing auth - the sign-in options start the OAuth flow with the dashboard as the destination", async ({ page }) => {
  await mockSession(page, { signedIn: false });
  const logins: string[] = [];
  await page.route("**/api/v1/auth/github/login**", (route) => {
    logins.push(route.request().url());
    return route.fulfill({ status: 200, contentType: "text/html", body: "provider" });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await hero(page).getByRole("link", { name: "Get started" }).click();
  await page.getByRole("link", { name: "Continue with GitHub" }).click();
  await expect.poll(() => logins.length).toBe(1);
  expect(new URL(logins[0] ?? "").searchParams.get("return_to")).toBe("/app");
});

for (const scheme of ["dark", "light"] as const) {
  test(`landing auth - signed in: dashboard entry points and the account replace Get started (${scheme})`, async ({ page }) => {
    const started = watchSessionStarts(page);
    await mockSession(page, { signedIn: true });
    for (const size of SIZES) {
      await page.setViewportSize(size);
      await page.goto("/");
      await applyTheme(page, scheme);
      const at = `${size.width}x${size.height} ${scheme}`;
      await expect(hero(page).getByRole("link", { name: "Open dashboard" }), at).toHaveAttribute("href", "/app");
      await expect(closing(page).getByRole("link", { name: "Open dashboard" }), at).toHaveAttribute("href", "/app");
      await expect(page.locator("footer").getByRole("link", { name: "Dashboard" }), at).toHaveAttribute("href", "/app");
      await expect(header(page).getByRole("img", { name: "Signed in as Ada Lovelace" }), at).toHaveText("AL");
      await expect(header(page).getByRole("button", { name: "Sign out" }), at).toBeVisible();
      await expect(page.getByRole("link", { name: /Get started|Sign in|Open QueryCure/ }), at).toHaveCount(0);
      expect(await noSideways(page), `${at}: sideways overflow`).toBeLessThanOrEqual(0);
    }
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    await page.getByRole("heading", { level: 1 }).waitFor();
    await expect(header(page).getByRole("button", { name: "Sign out" })).toBeVisible();
    await applyTheme(page, scheme);
    await page.waitForLoadState("networkidle");
    // Contrast is only meaningful at rest, as in accessibility.spec.ts: the page keeps starting one-shot entrances
    // and button colour transitions, so wait (polling) until none is running; looping ones never end, so skip them.
    await page.waitForFunction(() => document.getAnimations().every((a) => a.playState !== "running" || a.effect?.getComputedTiming().iterations === Infinity), null, { timeout: 15_000 });
    const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    expect(result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
    expect(started).toEqual([]);
  });
}

test("landing auth - sign out sends the CSRF token, then the page returns to its signed-out state without starting a session", async ({ page, context }) => {
  const started = watchSessionStarts(page);
  const session = { signedIn: true };
  await mockSession(page, session);
  await context.addCookies([{ name: "qc_csrf", value: "csrf-token-1", url: "http://localhost:3200" }]);
  let csrf: string | undefined;
  await page.route("**/api/v1/auth/logout", (route) => {
    csrf = route.request().headers()["x-csrf-token"];
    session.signedIn = false;
    return route.fulfill({ status: 204 });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await header(page).getByRole("button", { name: "Sign out" }).click();
  await expect(hero(page).getByRole("link", { name: "Get started" })).toBeVisible();
  await expect(header(page).getByRole("link", { name: "Sign in" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Open dashboard/ })).toHaveCount(0);
  expect(csrf).toBe("csrf-token-1");
  // Still on the landing page, with no anonymous session created behind it.
  await expect(page).toHaveURL(/\/$/);
  expect(started).toEqual([]);
});

test("landing auth - a failed sign-out keeps the account and says so", async ({ page }) => {
  await mockSession(page, { signedIn: true });
  await page.route("**/api/v1/auth/logout", (route) => route.abort("failed"));
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  await header(page).getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Sign-out failed" })).toBeVisible();
  await expect(header(page).getByRole("img", { name: "Signed in as Ada Lovelace" })).toBeVisible();
  expect(await noSideways(page)).toBeLessThanOrEqual(0);
});

test("landing auth - window focus picks up a sign-out that happened elsewhere", async ({ page }) => {
  const session = { signedIn: true };
  await mockSession(page, session);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(hero(page).getByRole("link", { name: "Open dashboard" })).toBeVisible();
  session.signedIn = false;
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(hero(page).getByRole("link", { name: "Get started" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Open dashboard/ })).toHaveCount(0);
});

test("landing auth - restricted trial: Sign in is the only way in", async ({ page }) => {
  const started = watchSessionStarts(page);
  await mockSession(page, { signedIn: false }, RESTRICTED);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(hero(page).getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/sign-in");
  await expect(closing(page).getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/sign-in");
  await expect(page.getByRole("link", { name: /Open QueryCure|Get started/ })).toHaveCount(0);
  expect(started).toEqual([]);
});

test("landing auth - nothing about the account is claimed until the session is known", async ({ page }) => {
  // Held until the test lets it go, so the pending state is checked however slowly the page hydrates.
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => (release = resolve));
  await page.route("**/api/v1/me", async (route) => {
    await held;
    await route.fulfill({ status: 401, json: UNAUTHENTICATED });
  });
  await page.route("**/api/v1/auth/options", (route) => route.fulfill({ json: OPEN }));
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.locator("[data-auth-slot='pending']").first()).toBeAttached();
  await expect(page.getByRole("link", { name: /Open QueryCure|Get started|Sign in|Open dashboard/ })).toHaveCount(0);
  release();
  await expect(hero(page).getByRole("link", { name: "Get started" })).toBeVisible();
  await expect(page.locator("[data-auth-slot='pending']")).toHaveCount(0);
});

test("landing auth - an unreachable API leaves a usable page with a neutral way in", async ({ page }) => {
  await page.route("**/api/v1/me", (route) => route.abort("failed"));
  await page.route("**/api/v1/auth/options", (route) => route.abort("failed"));
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(hero(page).getByRole("link", { name: "Get started" })).toHaveAttribute("href", "/sign-in");
  await expect(page.getByRole("link", { name: /Open QueryCure|Open dashboard/ })).toHaveCount(0);
  // (Next's own route announcer is an empty alert, so look for one with content.)
  await expect(page.getByRole("alert").filter({ hasText: /\S/ })).toHaveCount(0);
});

test("landing auth - a landing visit does not stop the app from starting its session", async ({ page }) => {
  // Real API, local profile: the landing page reads /me, then Open QueryCure reaches a working app.
  const started = watchSessionStarts(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  expect(started).toEqual([]);
  await page.goto("/app");
  await expect(page.getByRole("link", { name: "History" }).first()).toBeVisible({ timeout: 30_000 });
});
