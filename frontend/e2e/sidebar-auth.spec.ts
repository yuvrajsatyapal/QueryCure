import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { applyTheme } from "./theme";

/** Sidebar authentication UX (UI_UX §3.6, 2026-10-31): one Sign in button for a local session, a
 * provider dialog, and an account menu with Sign out for a signed-in account. Session states are
 * mocked on `/me` (and `/auth/logout`) so the run is deterministic and needs no provider
 * credentials. The provider login route is intercepted at our own API: this proves the dialog
 * starts the existing OAuth flow with the right `return_to`, not that a real provider sign-in
 * works (that is OAUTH_VERIFICATION_CHECKLIST's job, on a deployed origin). */

const FEATURES = { live_inspection: true, sandbox: true, google_login: true, github_login: true };
const OAUTH_ME = { user: { id: "00000000-0000-4000-8000-0000000000a1", kind: "oauth", display_name: "Ada Lovelace" }, profile: "local", features: FEATURES };

/** Keeps the real local session but advertises both providers (CI has no OAuth client IDs). */
async function mockLocalWithProviders(page: Page) {
  await page.route("**/api/v1/me", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({ response, json: { ...body, features: FEATURES } });
  });
}

async function mockSignedIn(page: Page) {
  await page.route("**/api/v1/me", (route) => route.fulfill({ json: OAUTH_ME }));
}

async function sidebar(page: Page): Promise<Locator> {
  const width = page.viewportSize()?.width ?? 1280;
  if (width < 768) {
    await page.getByRole("button", { name: "Open navigation" }).click();
    return page.getByRole("dialog", { name: "Navigation" });
  }
  return page.locator("aside.sticky");
}

/** The element painted at the centre of `locator` is it or inside it (nothing covers it). */
async function onTop(locator: Locator) {
  return locator.evaluate((el) => {
    const r = el.getBoundingClientRect();
    const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
    return !!hit && (hit === el || el.contains(hit));
  });
}

async function insideViewport(page: Page, locator: Locator) {
  const box = await locator.boundingBox();
  const vp = page.viewportSize();
  expect(box && vp).toBeTruthy();
  if (!box || !vp) return;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(vp.width);
  expect(box.y + box.height).toBeLessThanOrEqual(vp.height);
}

const noSideways = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

function collectHydrationErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error" && /hydrat/i.test(m.text())) errors.push(m.text());
  });
  page.on("pageerror", (e) => {
    if (/hydrat/i.test(e.message)) errors.push(e.message);
  });
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
    for (const size of [{ width: 1024, height: 360 }, { width: 1440, height: 900 }, { width: 1280, height: 1400 }]) {
      await page.setViewportSize(size);
      await page.goto(path);
      await expect(page.locator("aside.sticky").getByText("Local session")).toBeVisible();
      await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
      const m = await page.evaluate(() => {
        const aside = document.querySelector<HTMLElement>("aside.sticky");
        const footer = aside?.querySelector<HTMLElement>("[data-sidebar-footer]");
        const a = aside?.getBoundingClientRect();
        // The footer's place at the end of the scrolled sidebar content.
        const footerEnd = footer && aside ? footer.offsetTop + footer.offsetHeight : 0;
        return { top: a?.top, bottom: a?.bottom, vh: window.innerHeight, footerEnd, scrollHeight: aside?.scrollHeight ?? 0, padding: aside ? parseFloat(getComputedStyle(aside).paddingBottom) : 0 };
      });
      const at = `${path} ${size.width}x${size.height}`;
      expect(Math.round(m.top ?? -1), `${at}: sidebar top`).toBe(0);
      expect(Math.round(m.bottom ?? 0), `${at}: sidebar bottom`).toBe(m.vh);
      expect(Math.abs(m.scrollHeight - m.padding - m.footerEnd), `${at}: footer is not the last thing in the sidebar`).toBeLessThanOrEqual(1);
    }
  }
});

for (const scheme of ["dark", "light"] as const) {
  test(`sidebar auth - local session: one Sign in button opens an accessible provider dialog (${scheme})`, async ({ page }) => {
    const hydration = collectHydrationErrors(page);
    await mockLocalWithProviders(page);
    for (const size of SIZES) {
      await page.setViewportSize(size);
      await page.goto("/app");
      await applyTheme(page, scheme);
      const at = `${size.width}x${size.height} ${scheme}`;
      const nav = await sidebar(page);
      await expect(nav.getByText("Local session")).toBeVisible();
      await expect(nav.getByRole("link", { name: /Google|GitHub/ }), at).toHaveCount(0);
      const signIn = nav.getByRole("button", { name: "Sign in" });
      await expect(signIn).toHaveCount(1);
      await signIn.scrollIntoViewIfNeeded();
      expect(await onTop(signIn), `${at}: Sign in is covered`).toBe(true);
      await signIn.click();

      const dialog = page.getByRole("dialog", { name: "Sign in to QueryCure" });
      await expect(dialog).toBeVisible();
      // On phones the drawer closes so it cannot sit over (or trap focus away from) the dialog.
      if (size.width < 768) await expect(page.getByRole("dialog", { name: "Navigation" })).toHaveCount(0);
      await insideViewport(page, dialog);
      for (const name of ["Continue with Google", "Continue with GitHub", "Close sign-in"]) {
        expect(await onTop(dialog.getByRole(name.startsWith("Close") ? "button" : "link", { name })), `${at}: ${name} covered`).toBe(true);
      }
      expect(await noSideways(page), `${at}: sideways overflow`).toBeLessThanOrEqual(0);
      await page.keyboard.press("Escape");
      await expect(dialog).toHaveCount(0);
    }
    expect(hydration).toEqual([]);
  });
}

test("sidebar auth - the dialog traps focus, restores it, and starts the existing OAuth route", async ({ page }) => {
  await mockLocalWithProviders(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/app/history");
  const signIn = page.locator("aside.sticky").getByRole("button", { name: "Sign in" });
  await signIn.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Sign in to QueryCure" });
  await expect(dialog).toBeVisible();
  // Tab cycles inside the dialog only.
  for (let i = 0; i < 5; i++) {
    await page.keyboard.press("Tab");
    expect(await dialog.evaluate((d) => d.contains(document.activeElement))).toBe(true);
  }
  await dialog.getByRole("button", { name: "Close sign-in" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(signIn).toBeFocused();

  // The backdrop closes it too.
  await signIn.click();
  await page.mouse.click(5, 5);
  await expect(dialog).toHaveCount(0);

  let started = "";
  await page.route("**/api/v1/auth/github/login**", async (route) => {
    started = route.request().url();
    await route.fulfill({ contentType: "text/html", body: "<title>login intercepted</title>" });
  });
  await signIn.click();
  await dialog.getByRole("link", { name: "Continue with GitHub" }).click();
  await expect(page).toHaveTitle("login intercepted");
  expect(new URL(started).searchParams.get("return_to")).toBe("/app/history");
});

for (const scheme of ["dark", "light"] as const) {
  test(`sidebar auth - signed in: account menu opens upward, stays in view, and is keyboard operable (${scheme})`, async ({ page }) => {
    const hydration = collectHydrationErrors(page);
    await mockSignedIn(page);
    for (const size of SIZES) {
      await page.setViewportSize(size);
      await page.goto("/app");
      await applyTheme(page, scheme);
      const at = `${size.width}x${size.height} ${scheme}`;
      const nav = await sidebar(page);
      const account = nav.getByRole("button", { name: "Account: Ada Lovelace" });
      await expect(account).toBeVisible();
      await expect(nav.getByRole("button", { name: "Sign in" })).toHaveCount(0);
      await account.scrollIntoViewIfNeeded();
      expect(await onTop(account), `${at}: account control covered`).toBe(true);

      await account.focus();
      await page.keyboard.press("Enter");
      const menu = page.getByRole("menu", { name: "Account" });
      await expect(menu).toBeVisible();
      await expect(menu.getByRole("menuitem", { name: "Sign out" })).toBeFocused();
      await insideViewport(page, menu);
      const signOut = menu.getByRole("menuitem", { name: "Sign out" });
      expect(await onTop(signOut), `${at}: menu item covered or clipped`).toBe(true);
      const [menuBox, accountBox] = [await menu.boundingBox(), await account.boundingBox()];
      expect((menuBox?.y ?? 0) + (menuBox?.height ?? 0), `${at}: menu should open upward`).toBeLessThanOrEqual((accountBox?.y ?? 0) + 1);
      expect(await noSideways(page), `${at}: sideways overflow`).toBeLessThanOrEqual(0);

      await page.keyboard.press("Escape");
      await expect(menu).toHaveCount(0);
      await expect(account).toBeFocused();
      // Outside click closes it too.
      await account.click();
      await expect(menu).toBeVisible();
      await page.mouse.click((page.viewportSize()?.width ?? 400) - 5, 5);
      await expect(menu).toHaveCount(0);
    }
    expect(hydration).toEqual([]);
  });
}

test("sidebar auth - the account menu is not clipped by the collapsed rail", async ({ page }) => {
  await mockSignedIn(page);
  await page.setViewportSize({ width: 1024, height: 360 });
  await page.goto("/app");
  await page.getByRole("button", { name: "Collapse sidebar" }).click();
  try {
    const account = page.locator("aside.sticky").getByRole("button", { name: "Account: Ada Lovelace" });
    await account.click();
    const signOut = page.getByRole("menu", { name: "Account" }).getByRole("menuitem", { name: "Sign out" });
    await expect(signOut).toBeVisible();
    expect(await onTop(signOut)).toBe(true);
    await insideViewport(page, page.getByRole("menu", { name: "Account" }));
  } finally {
    await page.getByRole("button", { name: "Expand sidebar" }).click();
  }
});

test("sidebar auth - sign-out failure is reported; success returns the sidebar to the local session", async ({ page }) => {
  await mockSignedIn(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/app");
  const aside = page.locator("aside.sticky");
  await page.route("**/api/v1/auth/logout", (route) => route.fulfill({ status: 500, json: { error: { code: "INTERNAL", message: "boom" } } }));
  await aside.getByRole("button", { name: "Account: Ada Lovelace" }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(aside.getByRole("alert")).toContainText("Sign-out failed");
  await expect(aside.getByRole("button", { name: "Account: Ada Lovelace" })).toBeVisible();

  // The mocked account's session is the real local one underneath: dropping the /me mock is what
  // a revoked OAuth session followed by SessionGate's fresh local session looks like here.
  await page.unroute("**/api/v1/auth/logout");
  await page.route("**/api/v1/auth/logout", async (route) => {
    await page.unroute("**/api/v1/me");
    await route.fulfill({ status: 204 });
  });
  await aside.getByRole("button", { name: "Account: Ada Lovelace" }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(aside.getByText("Local session")).toBeVisible();
  await expect(aside.getByText("Ada Lovelace")).toHaveCount(0);
});

test("sidebar auth - axe finds no violations with the dialog or the menu open", async ({ page }) => {
  const scan = async (label: string) => {
    for (const scheme of ["light", "dark"] as const) {
      await applyTheme(page, scheme);
      const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      expect(result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(" | ")}`), `${label} ${scheme}`).toEqual([]);
    }
  };
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockLocalWithProviders(page);
  await page.goto("/app/connections");
  await page.locator("aside.sticky").getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("dialog", { name: "Sign in to QueryCure" })).toBeVisible();
  await scan("sign-in dialog");

  await page.unroute("**/api/v1/me");
  await mockSignedIn(page);
  await page.goto("/app/connections");
  await page.locator("aside.sticky").getByRole("button", { name: "Account: Ada Lovelace" }).click();
  await expect(page.getByRole("menu", { name: "Account" })).toBeVisible();
  await scan("account menu");
});
