import { expect, test } from "@playwright/test";

/** Public demo (T5.5): prerecorded investigations are browsable without a database connection,
 * every page carries the prerecorded label, and the shipped digests check out. */
test("demo gallery - browse, label, verify, phone width", async ({ page }) => {
  await page.goto("/demo");
  await expect(page.getByRole("heading", { name: "Prerecorded investigations" })).toBeVisible({ timeout: 30_000 });
  const cards = page.getByRole("region", { name: "Investigations" }).getByRole("listitem");
  await expect(cards.first()).toBeVisible();
  expect(await cards.count()).toBeGreaterThanOrEqual(5);
  await expect(page.getByRole("region", { name: "Benchmark verdicts" }).getByText(/verified/i).first()).toBeVisible();

  await page.getByRole("link", { name: "Orders sandbox composite index" }).click();
  const banner = page.getByRole("note", { name: "Prerecorded demonstration" });
  await expect(banner).toContainText("not a live run, not your database");
  await expect(page.getByText("Contains prerecorded demo measurements")).toBeVisible();
  await page.getByRole("button", { name: "Check stored digests" }).click();
  await expect(page.getByRole("status")).toContainText(/All \d+ shipped artifacts match the manifest/);
  await expect(page.getByRole("region", { name: "Plan explorer" })).toBeVisible();

  await page.setViewportSize({ width: 375, height: 812 });
  for (const path of ["/demo", "/demo/orders-sandbox-composite-index"]) {
    await page.goto(path);
    await expect(page.getByRole("note", { name: "Prerecorded demonstration" }).first()).toBeVisible({ timeout: 15_000 });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, path).toBeLessThanOrEqual(0);
  }
});
