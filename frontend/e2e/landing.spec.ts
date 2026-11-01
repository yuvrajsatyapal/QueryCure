import { expect, test, type Page } from "@playwright/test";

/** Landing page (docs/design/prototypes/landing): renders cleanly at phone and desktop widths, the X-Ray
 * toggle works and keeps its illustrative labels, reduced motion shows final states, styles stay scoped. */

const errorsOf = (page: Page) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  return errors;
};

for (const width of [375, 1440]) {
  test(`landing - ${width}px: no console errors and no horizontal overflow, top to bottom`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const errors = errorsOf(page);
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1, name: /Find out why your PostgreSQL queries are slow/ })).toBeVisible({ timeout: 30_000 });
    for (const id of ["product", "how", "verify", "bench", "report", "features"]) {
      await page.locator(`#${id}`).scrollIntoViewIfNeeded();
      await page.waitForTimeout(400);
    }
    await page.getByRole("contentinfo").scrollIntoViewIfNeeded();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBe(0);
    expect(errors).toEqual([]);
  });
}

test("landing - X-Ray switches plans and keeps its benchmark labelled as a separate illustration", async ({ page }) => {
  await page.goto("/");
  const xray = page.locator(".xr");
  const group = page.getByRole("group", { name: "Execution plan" });
  await expect(group).toBeVisible({ timeout: 30_000 });
  await group.getByRole("button", { name: "Before" }).click();
  await expect(group.getByRole("button", { name: "Before" })).toHaveAttribute("aria-pressed", "true");
  await expect(xray.getByText("Seq Scan on orders").first()).toBeVisible();
  await expect(xray.getByText("Before optimization")).toBeVisible();
  await expect(xray.getByText(/not a measurement of this plan/)).toBeVisible();
  await expect(xray.getByText("Illustrative verified outcome")).toBeHidden();

  await group.getByRole("button", { name: "After" }).click();
  await expect(group.getByRole("button", { name: "After" })).toHaveAttribute("aria-pressed", "true");
  await expect(xray.getByText(/Index Scan using/)).toBeVisible();
  await expect(xray.getByText("Illustrative verified outcome")).toBeVisible();
  await expect(xray.getByText(/Separate illustrative benchmark, not this plan/)).toBeVisible();
  await expect(xray.locator('.xr-slot[data-n="seq"]')).toBeHidden();

  // Keyboard: arrow keys move between the two plans.
  await group.getByRole("button", { name: "After" }).focus();
  await page.keyboard.press("ArrowLeft");
  await expect(group.getByRole("button", { name: "Before" })).toHaveAttribute("aria-pressed", "true");
  await expect(group.getByRole("button", { name: "Before" })).toBeFocused();
});

test("landing - reduced motion: no autoplay, final states shown, the X-Ray still switches", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  const group = page.getByRole("group", { name: "Execution plan" });
  await expect(group).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(3000);
  await expect(group.getByRole("button", { name: "Before" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".xr")).not.toHaveClass(/ghost/);
  await expect(page.getByRole("button", { name: "Replay the X-ray" })).toBeHidden();
  await group.getByRole("button", { name: "After" }).click();
  await expect(page.locator(".xr").getByText("Illustrative verified outcome")).toBeVisible();
});

test("landing - styles stay scoped: the app shell is unaffected after client navigation", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 30_000 });
  await page.getByRole("banner").getByRole("link", { name: "Open QueryCure" }).click();
  await expect(page).toHaveURL(/\/app$/);
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible({ timeout: 30_000 });
  // Landing rules all live under .lp; none may match outside it.
  const leaked = await page.evaluate(() => {
    let n = 0;
    for (const sheet of [...document.styleSheets]) {
      let rules: CSSRuleList;
      try {
        rules = sheet.cssRules;
      } catch {
        continue;
      }
      for (const r of [...rules]) {
        if (r instanceof CSSStyleRule && r.selectorText.includes(".lp ") && document.querySelector(r.selectorText) && !document.querySelector(".lp")) n++;
      }
    }
    return n;
  });
  expect(leaked).toBe(0);
});
