import { expect, test } from "@playwright/test";

/** Mode C through the real stack (API, worker, metadata DB, sandbox PostgreSQL) with the
 * offline stub LLM: the run must stop for approval with the exact SQL on screen, and only
 * after approval benchmark in the sandbox and show a tournament verdict. */
test("sandbox - approve the candidate SQL, then see the benchmarked tournament", async ({ page }) => {
  await page.goto("/app/investigations/new");
  await page.getByRole("tab", { name: "Demo workload" }).click();
  await page.getByLabel("Workload").selectOption("orders_ecommerce");
  await page.getByLabel("Scale factor").selectOption("0.01");

  await page.getByRole("button", { name: "New investigation" }).click();
  await page.getByLabel("Title").fill(`E2E sandbox ${Date.now()}`);
  await expect(page.getByText(/Mode: sandbox benchmark on/)).toBeVisible();
  await page.getByRole("button", { name: "Start investigation" }).click();
  await expect(page).toHaveURL(/\/app\/investigations\/[0-9a-f-]{36}$/, { timeout: 30_000 });

  const card = page.getByRole("region", { name: "Approval required" });
  await expect(card).toBeVisible({ timeout: 60_000 });
  await expect(card.getByText("CREATE INDEX ON orders (customer_id, created_at)")).toBeVisible();
  await expect(card.getByText(/Nothing has run yet/)).toBeVisible();
  await expect(page.getByText(/Status:\s*awaiting_approval/)).toBeVisible();

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
});
