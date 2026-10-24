import { readFileSync } from "node:fs";
import { join } from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { applyTheme } from "./theme";

const PLAN = readFileSync(join(__dirname, "orders-plan.json"), "utf8");
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

async function finishedOfflineRun(page: Page): Promise<string> {
  await page.goto("/app/investigations/new");
  await page.getByRole("button", { name: "Check and continue" }).click();
  await page.getByLabel("Plan JSON").fill(PLAN);
  await page.getByRole("button", { name: "Analyze plan" }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Title").fill(`E2E workspace ${Date.now()}`);
  await page.getByRole("button", { name: "Start investigation" }).click();
  await expect(page).toHaveURL(/\/app\/investigations\/[0-9a-f-]{36}$/, { timeout: 30_000 });
  await expect(page.getByRole("region", { name: "Agent timeline" }).getByText(/Run completed/).first()).toBeVisible({ timeout: 60_000 });
  return page.url();
}

async function axe(page: Page, label: string, include?: string) {
  for (const scheme of ["light", "dark"] as const) {
    await applyTheme(page, scheme);
    const builder = new AxeBuilder({ page }).withTags(TAGS);
    const result = await (include ? builder.include(include) : builder).analyze();
    const summary = result.violations.map((v) => `${v.id} (${v.impact}): ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(" | ")}`);
    expect(summary, `${label} in ${scheme} mode`).toEqual([]);
  }
}

test("workspace - graph follows the recorded run, rows have a context menu, the inspector resizes", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await finishedOfflineRun(page);

  // Activity line from the run's status, and the figures strip.
  await expect(page.getByText("The report is sealed from recorded results.")).toBeVisible();
  await expect(page.getByRole("region", { name: "Budget" }).getByText("Evidence")).toBeVisible();

  // Graph: an offline run exits to write_report after synthesis; the optimisation loop is not reached.
  await page.getByRole("group", { name: "Workspace view" }).getByRole("button", { name: "Graph" }).click();
  const graph = page.getByRole("region", { name: "Agent graph" });
  await expect(graph.getByRole("button", { name: /^synthesize_hypotheses, done/ })).toBeVisible();
  await expect(graph.getByRole("button", { name: "optimization_engineer, not reached" })).toBeVisible();
  await graph.getByRole("button", { name: /^collect_context, done/ }).click();
  const details = page.getByRole("region", { name: "Selection details" });
  await expect(details.getByRole("heading", { name: "collect_context" })).toBeVisible();
  await page.keyboard.press("ArrowRight");
  await expect(details.getByRole("heading", { name: "supervisor_plan" })).toBeVisible();
  await axe(page, "graph view");

  // Waterfall row actions: right-click, then keyboard.
  await page.getByRole("group", { name: "Workspace view" }).getByRole("button", { name: "Waterfall" }).click();
  const row = page.getByRole("tree", { name: "Run steps" }).getByRole("treeitem", { name: /^intake/ });
  await row.click({ button: "right" });
  const menu = page.getByRole("menu", { name: "Step actions" });
  await expect(menu.getByRole("menuitem", { name: "Inspect" })).toBeFocused();
  await axe(page, "context menu", '[role="menu"]');
  await page.keyboard.press("Escape");
  await expect(menu).toBeHidden();
  await expect(row).toBeFocused();
  await page.keyboard.press("Shift+F10");
  await expect(menu).toBeVisible();
  await menu.getByRole("menuitem", { name: "Show in graph" }).click();
  // Focus follows to the node, not the page.
  const intakeNode = page.getByRole("region", { name: "Agent graph" }).getByRole("button", { name: /^intake/ });
  await expect(intakeNode).toHaveAttribute("aria-pressed", "true");
  await expect(intakeNode).toBeFocused();
  // Fit keeps the 12px labels at 85% or more.
  const fit = Number((await page.getByRole("group", { name: "Graph zoom" }).getByRole("button", { name: /^Fit/ }).textContent())?.match(/(\d+)%/)?.[1]);
  expect(fit).toBeGreaterThanOrEqual(85);
  await page.getByRole("group", { name: "Workspace view" }).getByRole("button", { name: "Waterfall" }).click();

  // The splitter is a keyboard-operable separator.
  const splitter = page.getByRole("separator", { name: "Resize the details panel" });
  const before = Number(await splitter.getAttribute("aria-valuenow"));
  await splitter.focus();
  await page.keyboard.press("ArrowLeft");
  await expect(splitter).toHaveAttribute("aria-valuenow", String(before + 24));
  await axe(page, "waterfall workspace");
});

test("workspace - phone width: trace rows open the inspector as a bottom sheet", async ({ page }) => {
  await finishedOfflineRun(page);
  await page.setViewportSize({ width: 390, height: 844 });
  const row = page.getByRole("tree", { name: "Run steps" }).getByRole("treeitem", { name: /^collect_context/ });
  await row.click();
  const sheet = page.getByRole("dialog", { name: "Step details: collect_context" });
  await expect(sheet.getByRole("tab", { name: "Input" })).toBeVisible();
  // One header row: the step, its actions and a single close button (focused).
  await expect(sheet.getByRole("button", { name: "Close details" })).toHaveCount(1);
  await expect(sheet.getByRole("button", { name: "Close details" })).toBeFocused();
  await expect(sheet.getByRole("button", { name: /Back to run results/ })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBe(0);
  await axe(page, "inspector sheet", '[role="dialog"]');
  await page.keyboard.press("Escape");
  await expect(sheet).toBeHidden();
  await expect(row).toBeFocused();
});
