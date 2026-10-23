import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { applyTheme } from "./theme";

/** Mode C through the real stack (API, worker, metadata DB, sandbox PostgreSQL) with the
 * offline stub LLM: the run must stop for approval with the exact SQL on screen, and only
 * after approval benchmark in the sandbox and show a tournament verdict. */
test("sandbox - approve the candidate SQL, then see the benchmarked tournament", async ({ page }) => {
  await page.goto("/app/investigations/new");
  await page.getByRole("button", { name: "Check and continue" }).click();
  await page.getByRole("radio", { name: /Demo workload/ }).check();
  await page.getByLabel("Workload", { exact: true }).selectOption("orders_ecommerce");
  await page.getByLabel("Scale factor").selectOption("0.01");

  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("radio", { name: /Sandbox benchmark/ })).toBeChecked();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Title").fill(`E2E sandbox ${Date.now()}`);
  await expect(page.getByText(/Demo workload · orders_ecommerce@v\d+:sf=0\.01:seed=\d+/).first()).toBeVisible();
  await page.getByRole("button", { name: "Start investigation" }).click();
  await expect(page).toHaveURL(/\/app\/investigations\/[0-9a-f-]{36}$/, { timeout: 30_000 });

  const card = page.getByRole("region", { name: "Approval required" });
  await expect(card).toBeVisible({ timeout: 60_000 });
  await expect(card.getByText("CREATE INDEX ON orders (customer_id, created_at)")).toBeVisible();
  await expect(card.getByText(/Nothing has run yet/)).toBeVisible();
  await expect(page.locator("header").getByText("Approval required", { exact: true })).toBeVisible();

  await card.getByRole("button", { name: "Approve and run" }).click();
  await expect(card).toBeHidden({ timeout: 15_000 });
  const timeline = page.getByRole("region", { name: "Agent timeline" });
  await expect(timeline.getByText("Approval approved")).toBeVisible({ timeout: 15_000 });
  await expect(timeline.getByText(/Run completed/).first()).toBeVisible({ timeout: 90_000 });

  await page.getByRole("tab", { name: "Tournament" }).click();
  const table = page.getByRole("table", { name: "Optimization tournament" });
  await expect(table).toBeVisible({ timeout: 15_000 });
  // Any deterministic verdict is legitimate on shared CI hardware, including the noise-warning
  // verification (ADR-0019) and an auditor downgrade to inconclusive (ADR-0009).
  await expect(
    table.getByText(/Verified · tested scope|Verified · noise warning|Inconclusive|Rejected/).first(),
  ).toBeVisible();
  await expect(page.getByRole("table", { name: /Baseline versus candidate/ })).toBeVisible();
  await expect(page.getByText(/Measured in the sandbox/)).toBeVisible();

  // Pass 4 (UI_UX §3.17): recorded samples, speedup with the 1× reference, warnings, verdicts.
  await expect(page.getByRole("region", { name: "Recommendation verdicts" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Measurement warnings" }).getByText(/Host contention is not recorded/)).toBeVisible();
  await expect(page.getByRole("img", { name: /^Latency distribution · experiment [0-9a-f]{8} · round 1 · param set / })).toBeVisible();
  // A speedup is drawn only when the engine recorded a valid one; otherwise the row says why.
  await expect(page.getByRole("figure", { name: /Speedup with 95% CI/ }).getByText("1× no improvement")).toBeVisible();
  for (const scheme of ["light", "dark"] as const) {
    await applyTheme(page, scheme);
    const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    const summary = result.violations.map((v) => `${v.id} (${v.impact}): ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(" | ")}`);
    expect(summary, `tournament tab in ${scheme} mode`).toEqual([]);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});
