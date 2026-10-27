import { expect, test, type Page } from "@playwright/test";
import { advanceTo } from "./wizard";

/** Layout regression (UI_UX §3.6, 2026-10-27): a step that is not "done" carries a screen-reader
 * status word (`sr-only`, absolutely positioned) inside the trace tree's scrolling list. With the
 * list unpositioned, that word escaped the list's clip and made the document taller than the app
 * shell, so the sticky sidebar scrolled away and left a blank band. Real stack, real sandbox run
 * (sf=1.0, so `run_experiment` stays running long enough to measure). Assertions compare the
 * document with the shell and the sidebar with the viewport, at more than one size. */

const SIZES = [
  { width: 1440, height: 900 },
  { width: 1280, height: 720 },
  { width: 1024, height: 1366 },
];

/** Document height beyond the app shell, sidebar placement once scrolled to the end, sideways
 * overflow, and whether the tree list can still scroll. */
async function layout(page: Page) {
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  return page.evaluate(() => {
    const de = document.documentElement;
    const aside = document.querySelector<HTMLElement>("aside.sticky");
    const shell = aside?.parentElement?.getBoundingClientRect();
    const side = aside?.getBoundingClientRect();
    const tree = document.querySelector<HTMLElement>('ol[role="tree"]');
    return {
      extra: shell ? de.scrollHeight - Math.round(shell.bottom + window.scrollY) : NaN,
      sidebarShown: aside ? getComputedStyle(aside).display !== "none" : false,
      sidebarTop: side ? Math.round(side.top) : NaN,
      sidebarBottom: side ? Math.round(side.bottom) : NaN,
      innerHeight: window.innerHeight,
      sideways: de.scrollWidth - de.clientWidth,
      treeScrolls: tree ? tree.scrollHeight > tree.clientHeight : false,
    };
  });
}

async function expectContained(page: Page, when: string) {
  for (const size of SIZES) {
    await page.setViewportSize(size);
    const m = await layout(page);
    const at = `${when} at ${size.width}x${size.height}`;
    expect(m.extra, `${at}: document taller than the app shell`).toBeLessThanOrEqual(0);
    expect(m.sideways, `${at}: sideways overflow`).toBeLessThanOrEqual(0);
    if (m.sidebarShown) {
      expect(m.sidebarTop, `${at}: sidebar scrolled away`).toBe(0);
      expect(m.sidebarBottom, `${at}: blank band under the sidebar`).toBeGreaterThanOrEqual(m.innerHeight);
    }
  }
}

test("trace layout - a live step's status word stays inside the trace list; the sidebar stays put", async ({ page }) => {
  test.setTimeout(240_000);
  await page.setViewportSize(SIZES[0]!);
  await page.goto("/app/investigations/new");
  await advanceTo(page, "Plan source", "Check and continue");
  await page.getByRole("radio", { name: /Demo workload/ }).check();
  await page.getByLabel("Workload", { exact: true }).selectOption("orders_ecommerce");
  await page.getByLabel("Scale factor").selectOption("1");
  await advanceTo(page, "Investigation mode");
  await advanceTo(page, "Review & start");
  await page.getByLabel("Title").fill(`E2E trace layout ${Date.now()}`);
  await page.getByRole("button", { name: "Start investigation" }).click();
  await expect(page).toHaveURL(/\/app\/investigations\/[0-9a-f-]{36}$/, { timeout: 30_000 });

  const card = page.getByRole("region", { name: "Approval required" });
  await card.getByRole("button", { name: "Review details" }).click({ timeout: 120_000 });
  await page.getByRole("dialog", { name: "Benchmark this change in a sandbox?" }).getByRole("button", { name: "Approve selected" }).click();
  const recorded = page.getByRole("dialog", { name: "Decision recorded" });
  await recorded.getByRole("button", { name: "Close", exact: true }).click({ timeout: 15_000 });

  // The live row: its accessible name carries the screen-reader status word.
  const tree = page.getByRole("tree", { name: "Run steps" });
  const live = tree.getByRole("treeitem", { name: /run_experiment \(running\)/ });
  await expect(live).toBeVisible({ timeout: 60_000 });
  await expectContained(page, "live");
  await expect(live, "measured while the step was still running").toBeVisible();

  // The list itself still scrolls (inside, not the page) and the live row is reachable.
  await page.setViewportSize({ width: 1280, height: 720 });
  expect((await layout(page)).treeScrolls).toBe(true);
  const before = await tree.evaluate((el) => el.scrollTop);
  await tree.hover();
  await page.mouse.wheel(0, 400);
  await expect.poll(() => tree.evaluate((el) => el.scrollTop)).toBeGreaterThan(before);

  // After the run: same containment.
  await expect(page.getByRole("region", { name: "Agent timeline" }).getByText(/Run completed/).first()).toBeVisible({ timeout: 120_000 });
  await expectContained(page, "completed");
});
