import { execFileSync } from "node:child_process";
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { applyTheme } from "./theme";
import { advanceTo } from "./wizard";

/** Workstream 5 real-stack rehearsal (playwright.rehearsal.config.ts only). API → rehearsal worker
 * (real replay handler, comparison, classifier, report-builder@2 / report-md@2, sealing) → real
 * report endpoint → this page. Nothing is intercepted: the spec never calls `page.route`, and every
 * report read is checked to come from the real API. The worker's virtual clock makes replay 1
 * reproduce the original and replay 2 drift; production `_close` and defaults are unchanged. */

const API = "http://localhost:8100";
const SHOTS = "../test-results/ws5-rehearsal";
const WIDTHS = [[320, 700], [375, 812], [768, 1024], [1440, 900]] as const;
const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];
const UUID = /[0-9a-f-]{36}/;

/** The fields of the real API's report response (snake_case JSON) that this spec checks. */
interface SealedReport {
  builder_version: string;
  report_schema_version: number;
  outcome: string;
  report: {
    recommendation: { status: string; origin?: string; source_run_id?: string };
    replay_result: {
      result: string;
      claims_reproduction: boolean;
      correctness_reproduced: boolean | null;
      material_drift: boolean | null;
      basis: { code: string; comparison_status: string };
    };
  };
}

/** The sealed report as the real API returned it to the page. */
async function openReport(page: Page, runId: string) {
  const response = page.waitForResponse((r) => r.url() === `${API}/api/v1/runs/${runId}/report` && r.request().method() === "GET");
  await page.goto(`/app/reports/${runId}`);
  const res = await response;
  expect(res.status()).toBe(200);
  expect(res.fromServiceWorker()).toBe(false);
  await expect(page.getByRole("article", { name: "Final report" })).toBeVisible({ timeout: 15_000 });
  return (await res.json()) as SealedReport;
}

async function replayOnce(page: Page, replayUrl: string, verdict: RegExp): Promise<string> {
  await page.goto(replayUrl);
  await page.getByRole("button", { name: "Re-run experiment…" }).first().click();
  const dialog = page.getByRole("dialog", { name: "Confirm experiment replay" });
  await dialog.getByRole("button", { name: "Confirm and re-run" }).click();
  const history = page.getByRole("region", { name: "Replay history" });
  const before = await history.getByText(verdict).count();
  await expect(history.getByText(verdict)).toHaveCount(before + 1, { timeout: 150_000 });
  // newest attempt first; its comparison panel links to the replay run's report
  await history.getByRole("button", { name: "Show comparison" }).first().click();
  await page.getByRole("link", { name: "Open the replay run's report" }).first().click();
  await expect(page).toHaveURL(/\/app\/reports\/[0-9a-f-]{36}$/, { timeout: 15_000 });
  return page.url().match(UUID)![0];
}

async function shots(page: Page, runId: string, name: string) {
  for (const [w, h] of WIDTHS) {
    await page.setViewportSize({ width: w, height: h });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await openReport(page, runId);
    await page.waitForLoadState("networkidle");
    for (const scheme of ["dark", "light"] as const) {
      await applyTheme(page, scheme);
      await page.waitForTimeout(300);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, `${name} ${w}px ${scheme}`).toBeLessThanOrEqual(0);
      await page.screenshot({ path: `${SHOTS}/${name}-${w}-${scheme}.png`, fullPage: true });
      if (w === 1440 || w === 320) {
        const axe = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
        expect(axe.violations.map((v) => v.id), `${name} ${w}px ${scheme}`).toEqual([]);
      }
    }
  }
  await page.setViewportSize({ width: 1440, height: 900 });
}

test("rehearsal - activated replay outcome through the real stack, no interception", async ({ page }) => {
  test.setTimeout(600_000);
  // 1. A real Mode C investigation (stub LLM, real sandbox), sealed by the rehearsal worker.
  await page.goto("/app/investigations/new");
  await advanceTo(page, "Plan source", "Check and continue");
  await page.getByRole("radio", { name: /Demo workload/ }).check();
  await page.getByLabel("Workload", { exact: true }).selectOption("orders_ecommerce");
  await page.getByLabel("Scale factor").selectOption("0.01");
  await advanceTo(page, "Investigation mode");
  await advanceTo(page, "Review & start");
  await page.getByLabel("Title").fill(`WS5 rehearsal ${Date.now()}`);
  await page.getByRole("button", { name: "Start investigation" }).click();
  await expect(page).toHaveURL(/\/app\/investigations\/[0-9a-f-]{36}$/, { timeout: 30_000 });
  const investigationUrl = page.url();
  await page.getByRole("region", { name: "Approval required" }).getByRole("button", { name: "Approve and run" }).click({ timeout: 60_000 });
  await expect(page.getByRole("region", { name: "Agent timeline" }).getByText(/Run completed/).first()).toBeVisible({ timeout: 150_000 });
  await page.getByRole("tab", { name: "Report" }).click();
  await expect(page.getByRole("article", { name: "Final report" }).getByRole("heading", { level: 1 })).toHaveText("Verified recommendation", { timeout: 15_000 });
  await page.getByRole("link", { name: "Reproducibility & replay" }).click();
  await expect(page).toHaveURL(/\/app\/replay\/[0-9a-f-]{36}$/, { timeout: 60_000 });
  const replayUrl = page.url();
  const sourceRun = replayUrl.match(UUID)![0];

  // 2. Replay 1 (virtual clock: same timing): the original recommendation is reproduced.
  const reproduced = await replayOnce(page, replayUrl, /^Reproduced$/);
  let sealed = await openReport(page, reproduced);
  expect([sealed.builder_version, sealed.report_schema_version, sealed.outcome]).toEqual(["report-builder@2", 2, "verified_recommendation"]);
  const rr = sealed.report.replay_result;
  expect([rr.result, rr.basis.code, rr.basis.comparison_status, rr.claims_reproduction]).toEqual(["original_reproduced", "reproduced_source_recommendation", "reproduced", true]);
  expect(sealed.report.recommendation.origin).toBe("source_run");
  expect(sealed.report.recommendation.source_run_id).toBe(sourceRun);
  const article = page.getByRole("article", { name: "Final report" });
  await expect(article.getByRole("heading", { level: 1 })).toHaveText("Original recommendation reproduced");
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  await expect(article.getByText("Verified recommendation", { exact: true })).toHaveCount(0);
  const original = article.getByRole("region", { name: "Original recommendation" });
  await expect(original.getByText(/reproduced by this replay/)).toBeVisible();
  await expect(original.getByRole("list", { name: "Source details" })).toContainText(sourceRun);
  await expect(article.getByRole("region", { name: "Experiment replay result" }).getByText(/replay measurement, not a verification/)).toBeVisible();
  await expect(article.getByRole("region", { name: "Comparison with the original" })).toBeVisible();
  await expect(page.getByRole("note", { name: "Historical replay report" })).toHaveCount(0);
  // report replay rebuilds the same sealed bytes
  await page.getByRole("button", { name: "Verify report" }).click();
  await expect(page.getByText("Integrity check passed against stored digests")).toBeVisible({ timeout: 15_000 });
  // exported Markdown is the sealed Markdown and agrees with the page
  const md = await (await page.request.get(`${API}/api/v1/runs/${reproduced}/report.md`)).text();
  expect(md).toContain("> **Original recommendation reproduced.**");
  expect(md).toContain("## Original recommendation");
  expect(md).not.toContain("Verified recommendation");
  const exported = await (await page.request.get(`${API}/api/v1/runs/${reproduced}/report.json`)).json();
  expect(exported.report).toEqual(sealed.report);

  // 3. Replay 2 (virtual clock: half the speed-up): correctness held, performance drifted.
  const drifted = await replayOnce(page, replayUrl, /^Reproduced, effect size drifted$/);
  sealed = await openReport(page, drifted);
  expect([sealed.builder_version, sealed.outcome, sealed.report.replay_result.result, sealed.report.replay_result.basis.code]).toEqual([
    "report-builder@2",
    "inconclusive",
    "performance_drift",
    "comparison_reproduced_with_drift",
  ]);
  expect([sealed.report.replay_result.correctness_reproduced, sealed.report.replay_result.material_drift]).toEqual([true, true]);
  expect(sealed.report.recommendation.status).toBe("none");
  await expect(article.getByRole("heading", { level: 1 })).toHaveText("Performance drift detected");
  await expect(article.getByRole("region", { name: "Original recommendation" })).toHaveCount(0);
  await expect(article.getByRole("region", { name: "Recommendation" }).getByText("This replay makes no recommendation of its own.")).toBeVisible();
  await expect(article.getByText("Verified recommendation", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Verify report" }).click();
  await expect(page.getByText("Integrity check passed against stored digests")).toBeVisible({ timeout: 15_000 });

  // 4. Run selector: replay-specific labels; the original keeps its own.
  await page.goto(investigationUrl);
  await page.getByRole("button", { name: /^run 1 · Original run/ }).click({ timeout: 15_000 });
  const picker = page.getByRole("menu", { name: "Runs of this investigation" });
  const replays = picker.getByRole("group", { name: "Experiment replays" });
  await expect(replays.getByRole("menuitemradio", { name: /^#2 Experiment replay of run #1/ })).toContainText("· Original recommendation reproduced", { timeout: 15_000 });
  await expect(replays.getByRole("menuitemradio", { name: /^#3 Experiment replay of run #1/ })).toContainText("· Performance drift detected");
  await expect(replays).not.toContainText(/verified recommendation/i);
  await expect(replays.getByText("legacy replay")).toHaveCount(0);
  await expect(picker.getByRole("group", { name: "Investigation runs" }).getByRole("menuitemradio", { name: /^#1 Original run/ })).toContainText("verified recommendation");
  for (const scheme of ["dark", "light"] as const) {
    await applyTheme(page, scheme);
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${SHOTS}/run-selector-1440-${scheme}.png` });
    const axe = await new AxeBuilder({ page }).include("[role=menu]").withTags(AXE_TAGS).analyze();
    expect(axe.violations.map((v) => v.id), scheme).toEqual([]);
  }
  await page.keyboard.press("Escape");

  // 5. Visual QA on the real sealed reports.
  await shots(page, reproduced, "reproduced");
  await shots(page, drifted, "drifted");

  // 6. A historical report-builder@1 replay sealed earlier on this stack: stored outcome kept,
  // legacy notice outside the sealed body, and still verifiable.
  const legacy = execFileSync("docker", [
    "exec", "querycure-metadata-db-1", "psql", "-U", "qc_owner", "-d", "querycure", "-Atc",
    "SELECT r.run_id FROM investigation_reports r JOIN investigation_runs u ON u.id = r.run_id " +
      "WHERE u.kind = 'experiment_replay' AND r.builder_version = 'report-builder@1' " +
      "AND r.outcome = 'verified_recommendation' AND r.deleted_at IS NULL ORDER BY r.created_at DESC LIMIT 1",
  ]).toString().trim();
  expect(legacy).toMatch(UUID);
  sealed = await openReport(page, legacy);
  expect([sealed.builder_version, sealed.report_schema_version, sealed.outcome]).toEqual(["report-builder@1", 1, "verified_recommendation"]);
  await expect(page.getByRole("note", { name: "Historical replay report" })).toBeVisible();
  await expect(page.getByRole("article", { name: "Final report" }).getByRole("heading", { level: 1 })).toHaveText("Verified recommendation");
  await page.getByRole("button", { name: "Verify report" }).click();
  await expect(page.getByText("Integrity check passed against stored digests")).toBeVisible({ timeout: 15_000 });
  await shots(page, legacy, "legacy");
});
