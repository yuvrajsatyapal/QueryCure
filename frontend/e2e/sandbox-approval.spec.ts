import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { advanceTo } from "./wizard";
import { applyTheme } from "./theme";

/** Mode C through the real stack (API, worker, metadata DB, sandbox PostgreSQL) with the
 * offline stub LLM: the run must stop for approval with the exact SQL on screen, and only
 * after approval benchmark in the sandbox and show a tournament verdict. */
test("sandbox - approve the candidate SQL, then see the benchmarked tournament", async ({ page }) => {
  await page.goto("/app/investigations/new");
  await advanceTo(page, "Plan source", "Check and continue");
  await page.getByRole("radio", { name: /Demo workload/ }).check();
  await page.getByLabel("Workload", { exact: true }).selectOption("orders_ecommerce");
  await page.getByLabel("Scale factor").selectOption("0.01");

  await advanceTo(page, "Investigation mode");
  await expect(page.getByRole("radio", { name: /Sandbox benchmark/ })).toBeChecked();
  await advanceTo(page, "Review & start");
  await page.getByLabel("Title").fill(`E2E sandbox ${Date.now()}`);
  await expect(page.getByText(/Demo workload · orders_ecommerce@v\d+:sf=0\.01:seed=\d+/).first()).toBeVisible();
  await page.getByRole("button", { name: "Start investigation" }).click();
  await expect(page).toHaveURL(/\/app\/investigations\/[0-9a-f-]{36}$/, { timeout: 30_000 });

  const card = page.getByRole("region", { name: "Approval required" });
  await expect(card).toBeVisible({ timeout: 60_000 });
  await expect(card.getByText("CREATE INDEX ON orders (customer_id, created_at)")).toBeVisible();
  await expect(card.getByText(/Nothing has run yet/)).toBeVisible();
  // Deterministic description derived from the DDL (FINAL_UI_POLISH §2.2), key kept beside it.
  await expect(card.getByText("Composite index on orders (customer_id, created_at)")).toBeVisible();
  await expect(page.locator("header").getByText("Approval required", { exact: true })).toBeVisible();

  await card.getByRole("button", { name: "Approve and run" }).click();
  await expect(card).toBeHidden({ timeout: 15_000 });
  const timeline = page.getByRole("region", { name: "Agent timeline" });
  await expect(timeline.getByText("Approval approved")).toBeVisible({ timeout: 15_000 });
  await expect(timeline.getByText(/Run completed/).first()).toBeVisible({ timeout: 90_000 });

  // Final polish (FINAL_UI_POLISH §2.1): the sealed conclusion is above the trace, no tab switch.
  const summary = page.getByRole("region", { name: "Result summary" });
  await expect(summary).toBeVisible({ timeout: 30_000 });
  await expect(summary.getByRole("heading", { level: 2 })).toHaveText(/Verified recommendation|Unverified recommendations|Inconclusive|No action needed/);
  await expect(summary.getByText(/Nothing was applied to your database/)).toBeVisible();
  await summary.getByRole("button", { name: "Full report" }).click();
  await expect(page.getByRole("article", { name: "Final report" })).toBeVisible({ timeout: 15_000 });
  await summary.getByRole("button", { name: "Benchmark details" }).click();
  // Phase 3 studio: the verdict card and gates first; the full tables behind a toggle.
  await expect(page.getByRole("heading", { name: "Candidate comparison" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("region", { name: /^Verdict · oc_/ }).getByText("Predicted · not measured")).toBeVisible();
  await expect(page.getByRole("region", { name: /^Correctness and audit gates · oc_/ })).toBeVisible();
  await page.getByRole("button", { name: "Show data tables" }).click();
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
  await expect(table.getByText("Composite index on orders (customer_id, created_at)")).toBeVisible();
  // Result correctness from recorded fingerprints (UI_UX §3.8), and the statistics glossary.
  const correctness = page.getByRole("region", { name: /^Result correctness · oc_/ });
  await expect(correctness).toBeVisible();
  await expect(correctness.getByRole("table", { name: /Result fingerprints/ })).toBeVisible();
  await expect(correctness.getByText(/not a proof that the two queries are equivalent/)).toBeVisible();
  await page.getByText("How to read these numbers").click();
  await expect(page.getByText(/Faster is not the same as verified/)).toBeVisible();
  for (const scheme of ["light", "dark"] as const) {
    await applyTheme(page, scheme);
    const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    const summary = result.violations.map((v) => `${v.id} (${v.impact}): ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(" | ")}`);
    expect(summary, `tournament tab in ${scheme} mode`).toEqual([]);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);

  // Evidence tab (UI_UX §3.18): recorded links from the run, the auditor's citations included.
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("button", { name: "Results", exact: true }).click();
  await page.getByRole("tab", { name: "Evidence" }).click();
  const evidence = page.getByRole("region", { name: "Evidence relationships" });
  await expect(evidence.getByRole("button", { name: /^Verdict oc_/ }).first()).toBeVisible({ timeout: 15_000 });
  await expect(evidence.getByRole("list", { name: "Link legend" }).getByText(/Inferred by QueryCure/)).toBeVisible();
  await evidence.getByRole("button", { name: /^Evidence ev_[0-9a-f]{12} · benchmark_metric/ }).first().click();
  const record = evidence.getByRole("complementary", { name: "Selected record" });
  await expect(record.getByText(/measured by this run/)).toBeVisible();
  await expect(record.getByText("from audit check", { exact: false }).first()).toBeVisible();
  for (const scheme of ["light", "dark"] as const) {
    await applyTheme(page, scheme);
    const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    const summary = result.violations.map((v) => `${v.id} (${v.impact}): ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(" | ")}`);
    expect(summary, `evidence tab in ${scheme} mode`).toEqual([]);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});
