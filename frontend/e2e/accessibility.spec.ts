import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { applyTheme } from "./theme";

/** T5.10: axe (WCAG 2.1 A/AA rules) on the core pages, keyboard focus, reduced motion. */
const PAGES: [string, string][] = [
  ["/", "Find out why your PostgreSQL queries are slow"],
  ["/demo", "Prerecorded investigations"],
  ["/demo/orders-sandbox-composite-index", "Inconclusive"],
  ["/app", ""],
  ["/app/investigations/new", ""],
  ["/app/history", ""],
  ["/app/connections", "Connections"],
  ["/app/settings", "Model key"],
];

for (const [path, heading] of PAGES) {
  test(`a11y - axe finds no WCAG A/AA violations on ${path}`, async ({ page }) => {
    await page.goto(path);
    if (heading) await expect(page.getByRole("heading", { name: heading }).first()).toBeVisible({ timeout: 30_000 });
    else await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible({ timeout: 30_000 });
    await page.waitForLoadState("networkidle");
    for (const scheme of ["light", "dark"] as const) {
      await applyTheme(page, scheme);
      // Contrast is only meaningful at rest: let one-shot entrances finish (loops never do, so skip them).
      await page.waitForFunction(() => document.getAnimations().every((a) => a.playState !== "running" || a.effect?.getComputedTiming().iterations === Infinity), null, {
        timeout: 15_000,
      });
      const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      const summary = result.violations.map((v) => `${v.id} (${v.impact}): ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(" | ")}`);
      expect(summary, `${path} in ${scheme} mode`).toEqual([]);
    }
  });
}

test("a11y - empty states are axe-clean too (the history page with no matches)", async ({ page }) => {
  await page.goto("/app/history");
  await page.getByLabel("Search titles").fill(`no-such-investigation-${Date.now()}`);
  await expect(page.getByText(/No investigations match these filters/)).toBeVisible({ timeout: 30_000 });
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  expect(result.violations.map((v) => v.id)).toEqual([]);
});

test("a11y - keyboard reaches the main actions with a visible focus ring", async ({ page }) => {
  // The header and hero calls to action depend on the visitor's session, so fix it: signed out, both providers on.
  await page.route("**/api/v1/me", (route) => route.fulfill({ status: 401, json: { error: { code: "UNAUTHENTICATED", message: "Sign in required.", status: 401 } } }));
  await page.route("**/api/v1/auth/options", (route) => route.fulfill({ json: { google_login: true, github_login: true, restricted_access: false } }));
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 30_000 });
  // The calls to action appear once the session is known; tabbing earlier would skip their reserved space.
  await expect(page.locator("section.hero").getByRole("link", { name: "Get started" })).toBeVisible();
  // Header (logo, section links, theme, then Open QueryCure and Sign in) comes first; the hero's primary action follows.
  const focused = page.locator(":focus");
  for (const name of ["QueryCure", "Product", "How it works", "Safety", "Verification", "Reports", "Real data", "", "Open QueryCure", "Sign in", "Get started"]) {
    await page.keyboard.press("Tab");
    if (name) await expect(focused).toHaveText(name);
  }
  const outline = await focused.evaluate((el) => getComputedStyle(el).outlineStyle);
  expect(outline).not.toBe("none");
});

test("a11y - reduced motion turns transitions off", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/demo");
  await expect(page.getByRole("heading", { name: "Prerecorded investigations" })).toBeVisible({ timeout: 30_000 });
  const duration = await page.evaluate(() => getComputedStyle(document.body).transitionDuration);
  expect(["0s", "1e-05s"]).toContain(duration.split(",")[0]?.trim());
});
