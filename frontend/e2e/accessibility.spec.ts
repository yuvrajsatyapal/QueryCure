import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

/** T5.10: axe (WCAG 2.1 A/AA rules) on the core pages, keyboard focus, reduced motion. */
const PAGES: [string, string][] = [
  ["/", "QueryCure"],
  ["/demo", "Prerecorded investigations"],
  ["/demo/orders-sandbox-composite-index", "Inconclusive"],
  ["/app", ""],
  ["/app/investigations/new", ""],
  ["/app/history", ""],
  ["/app/settings", "Model key"],
];

for (const [path, heading] of PAGES) {
  test(`a11y - axe finds no WCAG A/AA violations on ${path}`, async ({ page }) => {
    await page.goto(path);
    if (heading) await expect(page.getByRole("heading", { name: heading }).first()).toBeVisible({ timeout: 30_000 });
    else await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible({ timeout: 30_000 });
    await page.waitForLoadState("networkidle");
    for (const scheme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme: scheme });
      const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      const summary = result.violations.map((v) => `${v.id} (${v.impact}): ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(" | ")}`);
      expect(summary, `${path} in ${scheme} mode`).toEqual([]);
    }
  });
}

test("a11y - keyboard reaches the main actions with a visible focus ring", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Tab");
  const focused = page.locator(":focus");
  await expect(focused).toHaveText("Explore prerecorded investigations");
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
