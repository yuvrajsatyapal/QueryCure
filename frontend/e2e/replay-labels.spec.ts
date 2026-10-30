import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Response } from "@playwright/test";
import { applyTheme } from "./theme";

/** History and Dashboard outcome labels on real local data (REPLAY_OUTCOME_AUDIT §18.1–§18.2): no
 * interception. The list's `latest_run` is never an experiment replay today (only creation and
 * re-investigation set it; backend test_replay_cutover pins that), so these rows are ordinary
 * runs with their stored outcome. Should a replay ever appear, it must not read as verified.
 * Lists never fetch a report per row. Replay labels themselves are covered by unit tests. */

const SHOTS = "../test-results/ws5-preact";
const WIDTHS = [320, 375, 768, 1440] as const;

interface Item {
  title: string;
  latest_run: { kind: string; status: string; outcome: string | null } | null;
}

const isList = (path: RegExp) => (r: Response) => r.ok() && r.request().method() === "GET" && path.test(new URL(r.url()).pathname + new URL(r.url()).search);

async function overflow(page: Page): Promise<number> {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
}

async function checkPage(page: Page, name: string) {
  for (const scheme of ["dark", "light"] as const) {
    await applyTheme(page, scheme);
    const axe = await new AxeBuilder({ page }).analyze();
    expect(axe.violations.map((v) => v.id), `${name} axe ${scheme}`).toEqual([]);
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: 900 });
      expect(await overflow(page), `${name} overflow at ${width}`).toBeLessThanOrEqual(0);
      await page.screenshot({ path: `${SHOTS}/${name}-${width}-${scheme}.png`, fullPage: true });
    }
  }
  await page.setViewportSize({ width: 1440, height: 900 });
}

test("history rows label replays by what they are, never as verified", async ({ page }) => {
  const reports: string[] = [];
  page.on("request", (r) => {
    if (/\/api\/v1\/runs\/[^/]+\/report$/.test(new URL(r.url()).pathname)) reports.push(r.url());
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  const listed = page.waitForResponse(isList(/\/api\/v1\/investigations\?.*limit=20/));
  await page.goto("/app/history");
  const items = ((await (await listed).json()) as { items: Item[] }).items;
  const rows = page.locator("main ul.qc-panel > li");
  await expect(rows).toHaveCount(items.length, { timeout: 15_000 });

  let replays = 0;
  for (const [i, item] of items.entries()) {
    const text = (await rows.nth(i).textContent()) ?? "";
    expect(text).toContain(item.title);
    const run = item.latest_run;
    if (run?.kind === "experiment_replay") {
      replays += 1;
      expect(text, item.title).not.toMatch(/verified recommendation/i);
      if (run.status === "completed") expect(text).toContain("Replay completed");
    } else if (run?.status === "completed" && run.outcome === "verified_recommendation") {
      expect(text).toContain("Verified recommendation");
    }
  }
  test.info().annotations.push({ type: "replay rows (expected 0, §18.2)", description: String(replays) });
  expect(reports, "lists never fetch a report per row").toEqual([]);
  await checkPage(page, "history");
});

test("dashboard recent runs and outcome counts never count a replay as verified", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const listed = page.waitForResponse(isList(/\/api\/v1\/investigations\?limit=25$/));
  await page.goto("/app");
  const items = ((await (await listed).json()) as { items: Item[] }).items;
  const recent = page.getByRole("region", { name: "Recent investigations" });
  const rows = recent.locator("tbody tr");
  await expect(rows.first()).toBeVisible({ timeout: 15_000 });

  for (const [i, item] of items.slice(0, await rows.count()).entries()) {
    const text = (await rows.nth(i).textContent()) ?? "";
    if (item.latest_run?.kind === "experiment_replay") expect(text, item.title).not.toMatch(/verified recommendation/i);
  }
  const concluded = items.filter((i) => i.latest_run && ["completed", "failed", "cancelled"].includes(i.latest_run.status));
  const verified = concluded.filter((i) => i.latest_run?.kind !== "experiment_replay" && i.latest_run?.outcome === "verified_recommendation").length;
  const replayed = concluded.filter((i) => i.latest_run?.kind === "experiment_replay" && i.latest_run.status === "completed").length;
  const bar = page.getByRole("region", { name: "Run outcomes" }).getByRole("img");
  const label = (await bar.getAttribute("aria-label")) ?? "";
  if (verified) expect(label).toContain(`${verified} Verified recommendation`);
  else expect(label).not.toContain("Verified recommendation");
  if (replayed) expect(label).toContain(`${replayed} Experiment replays`);
  await checkPage(page, "dashboard");
});
