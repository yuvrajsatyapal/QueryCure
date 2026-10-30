import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import fixtures from "../src/test/fixtures/report-v2.json";
import { applyTheme } from "./theme";

/** Report schema 2 and historical replay notices (Workstream 5), every scenario of the fixture
 * set at fixed widths. The report endpoint is intercepted with real report-builder@2 / @1 output
 * for synthetic inputs (backend test_frontend_report_fixture.py), so scenarios a host cannot
 * reach on demand are covered too. Real sealed v2 replays (no interception) are covered by
 * phase4-lifecycle.spec.ts and the rehearsal. Everything else (session, page, layout) is the
 * real app. */

type Name = Exclude<keyof typeof fixtures, "_note">;
const RUN = "00000000-0000-4000-8000-0000000000aa";
const SHOTS = "../test-results/ws5";
const snake = (v: unknown): unknown =>
  Array.isArray(v)
    ? v.map(snake)
    : v && typeof v === "object"
      ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k.replace(/[A-Z]/g, (c) => `_${c.toLowerCase()}`), snake(x)]))
      : v;

async function serve(page: Page, name: Name) {
  const report = fixtures[name] as { schemaVersion: number; builderVersion: string; outcome: string | null; finalStatus: string };
  await page.route(`**/api/v1/runs/${RUN}/report`, (route) =>
    route.fulfill({
      json: {
        run_id: RUN,
        final_status: report.finalStatus,
        outcome: report.outcome,
        report_schema_version: report.schemaVersion,
        builder_version: report.builderVersion,
        md_renderer_version: report.schemaVersion === 2 ? "report-md@2" : "report-md@1",
        report_json_sha256: "a".repeat(64),
        report_md_sha256: "b".repeat(64),
        manifest_sha256: "c".repeat(64),
        report: snake(fixtures[name]),
      },
    }),
  );
}

const CASES: [Name, string][] = [
  ["1_reproduced_original", "Original recommendation reproduced"],
  ["2_performance_drift", "Performance drift detected"],
  ["3_not_reproduced_rows", "Original result not reproduced"],
  ["5_cross_environment", "Results not directly comparable"],
  ["14_not_replayable", "No comparison with the original was possible"],
  ["15_execution_failed", "Replay failed"],
];

for (const [name, title] of CASES) {
  test(`replay report v2 - ${name}`, async ({ page }) => {
    await serve(page, name);
    await page.goto(`/app/reports/${RUN}`);
    const article = page.getByRole("article", { name: "Final report" });
    await expect(article.getByRole("heading", { level: 1 })).toHaveText(title, { timeout: 15_000 });
    await expect(article.getByText("Verified recommendation", { exact: true })).toHaveCount(0);
    await expect(article.getByRole("region", { name: "Experiment replay result" })).toBeVisible();
    await expect(page.getByRole("note", { name: "Historical replay report" })).toHaveCount(0);
    for (const scheme of ["dark", "light"] as const) {
      await applyTheme(page, scheme);
      const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      expect(axe.violations, `${scheme}: ${axe.violations.map((v) => v.id).join(", ")}`).toEqual([]);
    }
  });
}

test("replay report v2 and legacy notice - widths, themes, reduced motion", async ({ page }) => {
  test.setTimeout(120_000);
  for (const name of ["1_reproduced_original", "2_performance_drift", "legacy_v1_replay"] as Name[]) {
    await page.unrouteAll();
    await serve(page, name);
    for (const [w, h] of [[320, 700], [375, 812], [768, 1024], [1440, 900]] as const) {
      await page.setViewportSize({ width: w, height: h });
      await page.emulateMedia({ reducedMotion: "reduce" });
      await page.goto(`/app/reports/${RUN}`);
      await expect(page.getByRole("article", { name: "Final report" })).toBeVisible({ timeout: 15_000 });
      await page.waitForLoadState("networkidle");
      for (const scheme of ["dark", "light"] as const) {
        await applyTheme(page, scheme);
        await page.waitForTimeout(300); // let the theme transition finish before the screenshot
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
        expect(overflow, `${name} ${w}px ${scheme}`).toBeLessThanOrEqual(0);
        await page.screenshot({ path: `${SHOTS}/${name}-${w}-${scheme}.png`, fullPage: true });
      }
    }
  }
  // Legacy notice: present and outside the sealed report.
  await expect(page.getByRole("note", { name: "Historical replay report" })).toBeVisible();
  await expect(page.getByRole("article", { name: "Final report" }).getByRole("heading", { level: 1 })).toHaveText("Verified recommendation");
  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  expect(axe.violations.map((v) => v.id)).toEqual([]);
});
