import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { applyTheme } from "./theme";

/** Authentication UX (UI_UX §3.6, 2026-10-31, revised): a dedicated `/sign-in` page and inline
 * account controls in the sidebar. No sign-in dialog, popover or floating account menu. Session
 * states are mocked on `/me`, `/auth/options` and `/auth/logout` so the run is deterministic and
 * needs no provider credentials. Provider login routes are intercepted at our own API: this proves
 * the page starts the existing OAuth flow with the right `return_to`, not that a real provider
 * sign-in works (that is OAUTH_VERIFICATION_CHECKLIST's job, on a deployed origin). */

const FEATURES = { live_inspection: true, sandbox: true, google_login: true, github_login: true };
const OPTIONS = { google_login: true, github_login: true, restricted_access: false };
const OAUTH_ME = { user: { id: "00000000-0000-4000-8000-0000000000a1", kind: "oauth", display_name: "Ada Lovelace" }, profile: "local", features: FEATURES };

/** Keeps the real local session but advertises both providers (CI has no OAuth client IDs). */
async function mockLocalWithProviders(page: Page) {
  await page.route("**/api/v1/me", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({ response, json: { ...body, features: FEATURES } });
  });
  await page.route("**/api/v1/auth/options", (route) => route.fulfill({ json: OPTIONS }));
}

async function mockSignedIn(page: Page, displayName = "Ada Lovelace") {
  await page.route("**/api/v1/me", (route) =>
    route.fulfill({
      json: {
        ...OAUTH_ME,
        user: { ...OAUTH_ME.user, display_name: displayName },
      },
    }),
  );
  await page.route("**/api/v1/auth/options", (route) => route.fulfill({ json: OPTIONS }));
}

async function sidebar(page: Page): Promise<Locator> {
  const width = page.viewportSize()?.width ?? 1280;
  if (width < 768) {
    await page.getByRole("button", { name: "Open navigation" }).click();
    return page.getByRole("dialog", { name: "Navigation" }).locator("aside");
  }
  return page.locator("aside.sticky");
}

/** The element painted at the centre of `locator` is it or inside it (nothing covers it). */
async function onTop(locator: Locator) {
  return locator.evaluate((el) => {
    el.scrollIntoView({ block: "nearest" });
    const r = el.getBoundingClientRect();
    const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
    return !!hit && (hit === el || el.contains(hit));
  });
}

const noSideways = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

/** No fixed, absolute or portalled layer anywhere between the element and the sidebar. */
async function inFlow(locator: Locator) {
  return locator.evaluate((el) => {
    const aside = el.closest("aside");
    if (!aside) return false;
    for (let node: Element | null = el; node && node !== aside; node = node.parentElement) {
      if (["fixed", "absolute"].includes(getComputedStyle(node).position)) return false;
    }
    return true;
  });
}

function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => {
    // A 401 on /me is the expected "no session yet" answer, not a page error.
    if (m.type() === "error" && !/401|Failed to load resource/.test(m.text())) errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

const SIZES = [
  { width: 320, height: 360 },
  { width: 375, height: 667 },
  { width: 768, height: 1024 },
  { width: 1024, height: 360 },
  { width: 1440, height: 900 },
];

test("sidebar auth - the desktop sidebar fills the viewport with the account footer at the bottom", async ({ page }) => {
  // A short page (Connections) and a long one (History), scrolled to the end.
  for (const path of ["/app/connections", "/app/history"]) {
    for (const size of [
      { width: 1024, height: 360 },
      { width: 1440, height: 900 },
      { width: 1280, height: 1400 },
    ]) {
      await page.setViewportSize(size);
      await page.goto(path);
      await expect(page.locator("aside.sticky").getByText("Local session")).toBeVisible();
      await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
      const m = await page.evaluate(() => {
        const aside = document.querySelector<HTMLElement>("aside.sticky");
        const footer = aside?.querySelector<HTMLElement>("[data-sidebar-footer]");
        const a = aside?.getBoundingClientRect();
        const footerEnd = footer && aside ? footer.offsetTop + footer.offsetHeight : 0;
        return {
          top: a?.top,
          bottom: a?.bottom,
          vh: window.innerHeight,
          footerEnd,
          scrollHeight: aside?.scrollHeight ?? 0,
          padding: aside ? parseFloat(getComputedStyle(aside).paddingBottom) : 0,
        };
      });
      const at = `${path} ${size.width}x${size.height}`;
      expect(Math.round(m.top ?? -1), `${at}: sidebar top`).toBe(0);
      expect(Math.round(m.bottom ?? 0), `${at}: sidebar bottom`).toBe(m.vh);
      expect(Math.abs(m.scrollHeight - m.padding - m.footerEnd), `${at}: footer is not the last thing in the sidebar`).toBeLessThanOrEqual(1);
    }
  }
});

for (const scheme of ["dark", "light"] as const) {
  test(`sidebar auth - signed out: one Sign in link navigates to /sign-in, never a popup (${scheme})`, async ({ page }) => {
    const errors = collectErrors(page);
    await mockLocalWithProviders(page);
    for (const size of SIZES) {
      await page.setViewportSize(size);
      await page.goto("/app/history");
      await applyTheme(page, scheme);
      const at = `${size.width}x${size.height} ${scheme}`;
      const nav = await sidebar(page);
      await expect(nav.getByText("Local session")).toBeVisible();
      await expect(nav.getByRole("link", { name: /Google|GitHub/ }), at).toHaveCount(0);
      await expect(nav.getByRole("button", { name: /sign in/i }), at).toHaveCount(0);
      const signIn = nav.getByRole("link", { name: "Sign in" });
      await expect(signIn).toHaveCount(1);
      expect(await onTop(signIn), `${at}: Sign in is covered`).toBe(true);
      expect(await onTop(nav.getByRole("link", { name: "Settings" })), `${at}: Settings is covered`).toBe(true);
      expect(await onTop(nav.getByRole("button", { name: /theme/i })), `${at}: theme toggle is covered`).toBe(true);
      await signIn.click();

      await expect(page).toHaveURL(/\/sign-in\?next=%2Fapp%2Fhistory$/);
      await expect(page.getByRole("heading", { level: 1, name: "Welcome to QueryCure" })).toBeVisible();
      await expect(page.getByRole("dialog")).toHaveCount(0);
      await expect(page.getByRole("menu")).toHaveCount(0);
      for (const name of ["Continue with Google", "Continue with GitHub", "Back to QueryCure"]) {
        expect(await onTop(page.getByRole("link", { name })), `${at}: ${name} covered`).toBe(true);
      }
      expect(await noSideways(page), `${at}: sideways overflow on /sign-in`).toBeLessThanOrEqual(0);
    }
    expect(errors).toEqual([]);
  });
}

test("sign-in page - starts the existing OAuth route with a safe return path, once", async ({ page }) => {
  await mockLocalWithProviders(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  const started: string[] = [];
  await page.route("**/api/v1/auth/github/login**", async (route) => {
    started.push(route.request().url());
    await route.fulfill({ contentType: "text/html", body: "<title>login intercepted</title>" });
  });
  await page.goto("/sign-in?next=%2Fapp%2Fhistory");
  await page.getByRole("link", { name: "Continue with GitHub" }).click();
  await expect(page).toHaveTitle("login intercepted");
  expect(started).toHaveLength(1);
  expect(new URL(started[0] ?? "").searchParams.get("return_to")).toBe("/app/history");

  // An off-site `next` is never passed on.
  await page.goto("/sign-in?next=https%3A%2F%2Fevil.example%2F");
  const href = await page.getByRole("link", { name: "Continue with GitHub" }).getAttribute("href");
  expect(new URL(href ?? "").searchParams.get("return_to")).toBe("/app");
  await expect(page.getByRole("link", { name: "Back to QueryCure" })).toHaveAttribute("href", "/app");
});

test("sign-in page - a cancelled sign-in comes back to the page with the reason", async ({ page }) => {
  await mockLocalWithProviders(page);
  await page.setViewportSize({ width: 375, height: 667 });
  // Where the API sends a failed or cancelled sign-in.
  await page.goto("/app?auth_error=access_denied");
  await expect(page).toHaveURL(/\/sign-in\?auth_error=access_denied$/);
  await expect(page.locator("main").getByRole("alert")).toHaveText("Sign-in was cancelled.");
  await expect(page.getByRole("link", { name: "Continue with Google" })).toBeVisible();
});

test("sign-in page - a failed sign-in keeps the page it started from, so a retry returns there", async ({ page }) => {
  await mockLocalWithProviders(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  // The API sends a refused attempt to `/app?auth_error=`, without the destination.
  await page.route("**/api/v1/auth/google/login**", (route) =>
    route.fulfill({ status: 302, headers: { location: new URL("/app?auth_error=access_denied", page.url()).toString() } }),
  );
  await page.goto("/app/connections");
  await (await sidebar(page)).getByRole("link", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/sign-in\?next=%2Fapp%2Fconnections$/);
  await page.getByRole("link", { name: "Continue with Google" }).click();
  await expect(page).toHaveURL(/\/sign-in\?next=%2Fapp%2Fconnections&auth_error=access_denied$/);
  await expect(page.locator("main").getByRole("alert")).toHaveText("Sign-in was cancelled.");
  const retry = await page.getByRole("link", { name: "Continue with GitHub" }).getAttribute("href");
  expect(new URL(retry ?? "").searchParams.get("return_to")).toBe("/app/connections");
});

test("sign-in page - a restricted trial sends gated pages to the same sign-in page", async ({ page }) => {
  await page.route("**/api/v1/me", (route) => route.fulfill({ status: 401, json: { error: { code: "UNAUTHENTICATED", message: "Sign in to continue.", status: 401, details: [] } } }));
  await page.route("**/api/v1/session", (route) => route.fulfill({ status: 403, json: { error: { code: "ACCESS_DENIED", message: "Sign-in required.", status: 403, details: [] } } }));
  await page.route("**/api/v1/auth/options", (route) => route.fulfill({ json: { ...OPTIONS, restricted_access: true } }));
  await page.setViewportSize({ width: 375, height: 667 });
  await page.goto("/app/history");
  await expect(page).toHaveURL(/\/sign-in\?next=%2Fapp%2Fhistory$/);
  await expect(page.getByRole("heading", { level: 1, name: "Welcome to QueryCure" })).toBeVisible();
  await expect(page.getByText("This trial is limited to approved accounts.")).toBeVisible();
  const href = await page.getByRole("link", { name: "Continue with Google" }).getAttribute("href");
  expect(new URL(href ?? "").searchParams.get("return_to")).toBe("/app/history");
  await expect(page.getByRole("link", { name: "Back to QueryCure" })).toHaveAttribute("href", "/");
});

test("sign-in page - a signed-in account does not stay on it", async ({ page }) => {
  await mockSignedIn(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/sign-in?next=%2Fapp%2Fconnections");
  await expect(page).toHaveURL(/\/app\/connections$/);
  await expect(page.locator("aside.sticky").getByRole("button", { name: /Ada Lovelace/ })).toBeVisible();
});

test("sign-in page - public pages need no sign-in", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  for (const path of ["/", "/demo", "/app"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    expect(new URL(page.url()).pathname, path).toBe(path);
  }
});

for (const scheme of ["dark", "light"] as const) {
  test(`sidebar auth - signed in: the profile expands Sign out inline, in the sidebar's flow (${scheme})`, async ({ page }) => {
    const errors = collectErrors(page);
    await mockSignedIn(page);
    for (const size of SIZES) {
      await page.setViewportSize(size);
      await page.goto("/app");
      await applyTheme(page, scheme);
      const at = `${size.width}x${size.height} ${scheme}`;
      const nav = await sidebar(page);
      const profile = nav.getByRole("button", { name: /Ada Lovelace/ });
      await expect(profile).toHaveAttribute("aria-expanded", "false");
      await expect(nav.getByRole("link", { name: "Sign in" })).toHaveCount(0);
      await expect(nav.getByRole("button", { name: "Sign out" })).toHaveCount(0);
      expect(await onTop(profile), `${at}: profile covered`).toBe(true);

      const footer = nav.locator("[data-sidebar-footer]");
      const before = await footer.evaluate((f) => f.getBoundingClientRect().height);
      await profile.focus();
      await page.keyboard.press("Enter");
      await expect(profile).toHaveAttribute("aria-expanded", "true");
      const signOut = nav.getByRole("button", { name: "Sign out" });
      await expect(signOut).toBeVisible();
      await expect(page.getByRole("menu")).toHaveCount(0);
      expect(await inFlow(signOut), `${at}: Sign out is layered, not in flow`).toBe(true);
      // It takes room in the sidebar's footer (the layout grows) and sits directly below the profile.
      expect(await footer.evaluate((f) => f.getBoundingClientRect().height), `${at}: expanding added no height`).toBeGreaterThan(before);
      const [p, s] = [await profile.boundingBox(), await signOut.boundingBox()];
      expect((s?.y ?? 0) + 1, `${at}: Sign out should be below the profile`).toBeGreaterThanOrEqual((p?.y ?? 0) + (p?.height ?? 0));
      for (const target of [signOut, nav.getByRole("link", { name: "Settings" }), nav.getByRole("button", { name: /theme/i }), profile]) {
        expect(await onTop(target), `${at}: control covered`).toBe(true);
      }
      expect(await noSideways(page), `${at}: sideways overflow`).toBeLessThanOrEqual(0);

      await profile.focus();
      await page.keyboard.press("Space");
      await expect(profile).toHaveAttribute("aria-expanded", "false");
      await expect(signOut).toHaveCount(0);
    }
    expect(errors).toEqual([]);
  });
}

test("sidebar auth - long names truncate without sideways overflow on a 320px phone", async ({ page }) => {
  await mockSignedIn(page, "Augusta Ada King, Countess of Lovelace and Analytical Engine Enthusiast");
  await page.setViewportSize({ width: 320, height: 568 });
  await page.goto("/app");
  const nav = await sidebar(page);
  const profile = nav.getByRole("button", { name: /Augusta Ada King/ });
  await profile.click();
  await expect(nav.getByRole("button", { name: "Sign out" })).toBeVisible();
  const overflow = await profile.evaluate((b) => b.scrollWidth - b.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  expect(await noSideways(page)).toBeLessThanOrEqual(0);
});

test("sidebar auth - the collapsed rail expands an icon Sign out inline", async ({ page }) => {
  await mockSignedIn(page);
  await page.setViewportSize({ width: 1024, height: 360 });
  await page.goto("/app");
  await page.getByRole("button", { name: "Collapse sidebar" }).click();
  try {
    const aside = page.locator("aside.sticky");
    await aside.getByRole("button", { name: "Account: Ada Lovelace" }).click();
    const signOut = aside.getByRole("button", { name: "Sign out" });
    await expect(signOut).toBeVisible();
    expect(await inFlow(signOut)).toBe(true);
    expect(await onTop(signOut)).toBe(true);
    expect(await noSideways(page)).toBeLessThanOrEqual(0);
  } finally {
    await page.getByRole("button", { name: "Expand sidebar" }).click();
  }
});

for (const width of [1440, 375]) {
  test(`sidebar auth - sign-out failure is reported; success returns to the local session (${width}px)`, async ({ page }) => {
    await mockSignedIn(page);
    await page.setViewportSize({ width, height: 800 });
    await page.goto("/app");
    const nav = await sidebar(page);
    await page.route("**/api/v1/auth/logout", (route) => route.fulfill({ status: 500, json: { error: { code: "INTERNAL", message: "boom" } } }));
    await nav.getByRole("button", { name: /Ada Lovelace/ }).click();
    await nav.getByRole("button", { name: "Sign out" }).click();
    await expect(nav.getByRole("alert")).toContainText("Sign-out failed");
    await expect(nav.getByRole("button", { name: /Ada Lovelace/ })).toBeVisible();

    // The mocked account's session is the real local one underneath: dropping the /me mock is what
    // a revoked OAuth session followed by SessionGate's fresh local session looks like here.
    await page.unroute("**/api/v1/auth/logout");
    await page.route("**/api/v1/auth/logout", async (route) => {
      await page.unroute("**/api/v1/me");
      await route.fulfill({ status: 204 });
    });
    await nav.getByRole("button", { name: "Sign out" }).click();
    await expect(nav.getByText("Local session")).toBeVisible();
    await expect(nav.getByText("Ada Lovelace")).toHaveCount(0);
  });
}

test("sidebar auth - axe finds no violations on the sign-in page or the expanded account", async ({ page }) => {
  const scan = async (label: string) => {
    for (const scheme of ["light", "dark"] as const) {
      await applyTheme(page, scheme);
      const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      expect(
        result.violations.map(
          (v) =>
            `${v.id}: ${v.nodes
              .map((n) => n.target.join(" "))
              .slice(0, 3)
              .join(" | ")}`,
        ),
        `${label} ${scheme}`,
      ).toEqual([]);
    }
  };
  await mockLocalWithProviders(page);
  for (const size of [
    { width: 1440, height: 900 },
    { width: 320, height: 568 },
  ]) {
    await page.setViewportSize(size);
    await page.goto("/sign-in?auth_error=access_denied");
    await expect(page.getByRole("link", { name: "Continue with Google" })).toBeVisible();
    await scan(`sign-in ${size.width}`);
  }

  await page.unroute("**/api/v1/me");
  await page.unroute("**/api/v1/auth/options");
  await mockSignedIn(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/app/connections");
  await page
    .locator("aside.sticky")
    .getByRole("button", { name: /Ada Lovelace/ })
    .click();
  await expect(page.locator("aside.sticky").getByRole("button", { name: "Sign out" })).toBeVisible();
  await scan("expanded account");
  await page.setViewportSize({ width: 375, height: 667 });
  await page.goto("/app/connections");
  const nav = await sidebar(page);
  await nav.getByRole("button", { name: /Ada Lovelace/ }).click();
  await expect(nav.getByRole("button", { name: "Sign out" })).toBeVisible();
  await scan("expanded account in drawer");
});
