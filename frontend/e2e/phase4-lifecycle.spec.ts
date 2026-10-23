import { expect, test } from "@playwright/test";

/** Phase 4 lifecycle through the real stack (API, worker, metadata DB, sandbox PostgreSQL) with
 * the offline stub LLM: workspace → investigation → agents → candidate → approval → sandbox
 * experiment → Benchmark Auditor → sealed final report → report replay → experiment replay
 * (new measurements, no model calls) → comparison. */
test("lifecycle - approve, audit, report, verify, replay the experiment", async ({ page }) => {
  test.setTimeout(240_000);
  await page.goto("/app/investigations/new");
  await page.getByRole("button", { name: "Check and continue" }).click();
  await page.getByRole("radio", { name: /Demo workload/ }).check();
  await page.getByLabel("Workload", { exact: true }).selectOption("orders_ecommerce");
  await page.getByLabel("Scale factor").selectOption("0.01");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("radio", { name: /Sandbox benchmark/ })).toBeChecked();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Title").fill(`E2E lifecycle ${Date.now()}`);
  await page.getByRole("button", { name: "Start investigation" }).click();
  await expect(page).toHaveURL(/\/app\/investigations\/[0-9a-f-]{36}$/, { timeout: 30_000 });
  const investigationUrl = page.url();

  const card = page.getByRole("region", { name: "Approval required" });
  await expect(card).toBeVisible({ timeout: 60_000 });
  await card.getByRole("button", { name: "Approve and run" }).click();
  const timeline = page.getByRole("region", { name: "Agent timeline" });
  await expect(timeline.getByText(/Run completed/).first()).toBeVisible({ timeout: 120_000 });
  await expect(timeline.getByText(/Audit:/).first()).toBeVisible();

  // Benchmark Auditor and plan diff in the tournament.
  await page.getByRole("tab", { name: "Tournament" }).click();
  const auditor = page.getByRole("region", { name: "Benchmark Auditor" });
  await expect(auditor).toBeVisible({ timeout: 15_000 });
  await expect(auditor.getByText("rescore")).toBeVisible();
  await expect(page.getByRole("region", { name: "Plan diff" })).toBeVisible();

  // Sealed final report, verified against its stored digests (no model call, no SQL).
  await page.getByRole("tab", { name: "Report" }).click();
  const report = page.getByRole("article", { name: "Final report" });
  await expect(report).toBeVisible({ timeout: 15_000 });
  await expect(report.getByText(/Nothing was applied to your database/)).toBeVisible();
  await expect(report.getByRole("note").filter({ hasText: /offline stub model/ })).toBeVisible();
  await page.getByRole("button", { name: "Verify report" }).click();
  await expect(page.getByText("Integrity check passed against stored digests")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("link", { name: "Export Markdown" })).toHaveAttribute("href", /report\.md$/);

  // Experiment replay: confirm the exact SQL, then a new measurement and a comparison.
  await page.getByRole("link", { name: "Reproducibility & replay" }).click();
  await expect(page).toHaveURL(/\/app\/replay\/[0-9a-f-]{36}$/, { timeout: 60_000 });
  await page.getByRole("button", { name: "Re-run experiment…" }).first().click();
  const dialog = page.getByRole("dialog", { name: "Confirm experiment replay" });
  await expect(dialog.getByText(/CREATE INDEX ON orders \(customer_id, created_at\)/)).toBeVisible({ timeout: 15_000 });
  await dialog.getByRole("button", { name: "Confirm and re-run" }).click();
  const history = page.getByRole("region", { name: "Replay history" });
  await expect(history.getByText(/^experiment$/)).toBeVisible({ timeout: 15_000 });
  await expect(
    history.getByText(/^(Reproduced|Reproduced, effect size drifted|Not reproduced|Inconclusive|Consistent across environments)$/).first(),
  ).toBeVisible({ timeout: 150_000 });
  await history.getByRole("button", { name: "Show comparison" }).first().click();
  await expect(page.getByRole("region", { name: "Replay comparison" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Environment differences" })).toBeVisible();

  // The replay run is sealed too and has its own report.
  await page.getByRole("link", { name: "Open the replay run's report" }).click();
  await expect(page.getByRole("article", { name: "Final report" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/experiment replay · run 2/)).toBeVisible();

  // Run history (Phase 5): the investigation lists both runs; the replay links to its source.
  await page.goto(investigationUrl);
  // The run list lives in the header's run selector (UI_UX §3.6): open it first.
  const picker = page.getByRole("navigation", { name: "Runs of this investigation" });
  const runSelector = (name: RegExp) => page.getByRole("button", { name });
  // Without ?run= the page shows the investigation's latest run, the original.
  await runSelector(/^run 1 · Original run/).click({ timeout: 15_000 });
  await expect(picker.getByText("Runs (2)")).toBeVisible();
  await picker.getByRole("button", { name: /^#2 Experiment replay of run #1/ }).click();
  await expect(page).toHaveURL(/\?run=[0-9a-f-]{36}$/);
  await expect(page.getByText(/run 2 · Experiment replay of run #1/)).toBeVisible();
  await runSelector(/^run 2 · Experiment replay of run #1/).click();
  await expect(picker.getByRole("link", { name: "Open this run's report" })).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Go to run #1 (original run)" }).click();
  await expect(page.getByText(/run 1 · Original run/)).toBeVisible({ timeout: 15_000 });

  // Phone width: the picker and run view wrap instead of scrolling the page sideways.
  await page.setViewportSize({ width: 375, height: 812 });
  await runSelector(/^run 1 · Original run/).click();
  await expect(picker).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});
