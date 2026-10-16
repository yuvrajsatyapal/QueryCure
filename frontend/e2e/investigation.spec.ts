import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test } from "@playwright/test";

const PLAN = readFileSync(join(__dirname, "orders-plan.json"), "utf8");

test("investigation - start from an uploaded plan, follow the timeline, open cited evidence", async ({ page }) => {
  await page.goto("/app/investigations/new");
  await page.getByLabel("Plan JSON").fill(PLAN);
  await page.getByRole("button", { name: "Analyze plan" }).click();
  await expect(page.getByRole("treegrid")).toBeVisible();

  await page.getByRole("button", { name: "New investigation" }).click();
  await page.getByLabel("Title").fill(`E2E orders ${Date.now()}`);
  await expect(page.getByText("with the uploaded plan")).toBeVisible();
  await page.getByRole("button", { name: "Start investigation" }).click();

  await expect(page).toHaveURL(/\/app\/investigations\/[0-9a-f-]{36}$/, { timeout: 30_000 });
  const timeline = page.getByRole("region", { name: "Agent timeline" });
  await expect(timeline.getByText("intake started")).toBeVisible({ timeout: 30_000 });
  await expect(timeline.getByText(/Run completed/).first()).toBeVisible({ timeout: 60_000 });

  // The stub's hypothesis cites the Seq Scan plan node it found in the evidence block.
  await expect(page.getByText(/Stub hypothesis/)).toBeVisible();
  await expect(page.getByText(/Hypothesis · low · unverified/)).toBeVisible();
  await page.getByRole("button", { name: /^Evidence ev_/ }).first().click();

  await expect(page.getByRole("tab", { name: "Plan" })).toHaveAttribute("aria-selected", "true");
  const selected = page.getByRole("treegrid").locator('tr[aria-selected="true"]');
  await expect(selected).toHaveCount(1);
  await expect(selected).toContainText("Seq Scan");
  await expect(page.getByLabel("Selected evidence")).toContainText("Seq Scan on orders");
});
