import { readFileSync } from "node:fs";
import { join } from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { applyTheme } from "./theme";

const PLAN = readFileSync(join(__dirname, "orders-plan.json"), "utf8");

test("investigation - start from an uploaded plan, follow the timeline, open cited evidence", async ({ page }) => {
  await page.goto("/app/investigations/new");
  await page.getByRole("button", { name: "Check and continue" }).click();
  await expect(page.getByText(/SELECT · orders · 0 parameters/)).toBeVisible();
  await page.getByLabel("Plan JSON").fill(PLAN);
  await page.getByRole("button", { name: "Analyze plan" }).click();
  await expect(page.getByRole("treegrid")).toBeVisible();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("radio", { name: /Offline/ })).toBeChecked();
  await page.getByRole("button", { name: "Continue" }).click();

  await page.getByLabel("Title").fill(`E2E orders ${Date.now()}`);
  await expect(page.getByText(/Uploaded plan · uploaded plan · artifact/)).toBeVisible();
  await page.getByRole("button", { name: "Start investigation" }).click();

  await expect(page).toHaveURL(/\/app\/investigations\/[0-9a-f-]{36}$/, { timeout: 30_000 });
  const timeline = page.getByRole("region", { name: "Agent timeline" });
  await expect(timeline.getByText("intake", { exact: true })).toBeVisible({ timeout: 30_000 });
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
  // Pass 1 (UI_UX §3.6): the cited node names the claims that cite it.
  await expect(page.getByRole("region", { name: "Cited by" }).getByRole("button", { name: /Stub hypothesis/ })).toBeVisible({ timeout: 15_000 });

  // A finding's "Show step" selects the trace row that recorded it; the details pane follows.
  await page.getByRole("tab", { name: "Findings" }).click();
  await page.getByRole("button", { name: /^Show step/ }).first().click();
  const tree = page.getByRole("tree", { name: "Run steps" });
  const selectedRow = tree.locator('[role="treeitem"][aria-selected="true"]');
  await expect(selectedRow).toHaveCount(1);
  await expect(page.getByRole("region", { name: "Selection details" }).getByRole("button", { name: "Back to run results" })).toBeVisible();

  // Keyboard: Home selects the run row, ArrowDown the next one, and the run row shows results again.
  await selectedRow.focus();
  await page.keyboard.press("Home");
  await expect(tree.getByRole("treeitem", { name: /^Run #1/ })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tab", { name: "Findings" })).toBeVisible();
  await page.keyboard.press("ArrowDown");
  await expect(tree.getByRole("treeitem", { name: /^Run #1/ })).toHaveAttribute("aria-selected", "false");

  for (const scheme of ["light", "dark"] as const) {
    await applyTheme(page, scheme);
    const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    const summary = result.violations.map((v) => `${v.id} (${v.impact}): ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(" | ")}`);
    expect(summary, `investigation page in ${scheme} mode`).toEqual([]);
  }
});
