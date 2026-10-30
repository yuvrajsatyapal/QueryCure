import { expect, test, type Page } from "@playwright/test";
import { applyTheme } from "./theme";

/** Layout regression (UI_UX §3.6, 2026-10-31). On short viewports the sidebar's nav shrank below
 * its content (`min-h-0`, no overflow), so Connections, Demo gallery and Settings painted over the
 * account footer and Settings could not be reached. Separately, the Next dev indicator (fixed,
 * bottom-left in dev only) sat on the footer's sign-in controls. Every footer control must be the topmost
 * element at its own centre once scrolled into view, and no nav link may intersect the footer. */

const SIZES = [
  { width: 320, height: 360 },
  { width: 320, height: 568 },
  { width: 375, height: 667 },
  { width: 768, height: 400 },
  { width: 768, height: 1024 },
  { width: 1024, height: 360 },
  { width: 1440, height: 560 },
  { width: 1440, height: 900 },
];

async function openSidebar(page: Page, width: number) {
  if (width < 768) {
    await page.getByRole("button", { name: "Open navigation" }).click();
    return page.getByRole("dialog", { name: "Navigation" });
  }
  return page.locator("aside.sticky");
}

/** Whether the control is the element painted at its own centre (nothing layered over it). */
async function topmost(page: Page, selector: string, index: number) {
  return page.evaluate(
    ([sel, i]) => {
      const aside = [...document.querySelectorAll("aside")].find((a) => a.getClientRects().length);
      const el = aside?.querySelectorAll<HTMLElement>(sel as string)[i as number];
      if (!el) return { found: false, top: false, inView: false };
      el.scrollIntoView({ block: "nearest" });
      const r = el.getBoundingClientRect();
      const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
      return { found: true, top: !!hit && (hit === el || el.contains(hit)), inView: r.top >= 0 && r.bottom <= window.innerHeight };
    },
    [selector, index] as const,
  );
}

// The Sign in button exists only where a provider is configured (not in CI); sidebar-auth.spec
// covers it with a mocked session.
const FOOTER_CONTROLS = ['a[href="/app/settings"]', 'button[aria-label*="theme" i]', "[data-sidebar-footer] button"];

for (const scheme of ["dark", "light"] as const) {
  test(`sidebar footer - controls stay reachable and uncovered (${scheme})`, async ({ page }) => {
    for (const size of SIZES) {
      await page.setViewportSize(size);
      await page.goto("/app");
      await applyTheme(page, scheme);
      const sidebar = await openSidebar(page, size.width);
      await expect(sidebar.getByText("Local session")).toBeVisible();
      const at = `${size.width}x${size.height} ${scheme}`;

      for (const selector of FOOTER_CONTROLS) {
        const count = await sidebar.locator(selector).count();
        if (selector.startsWith("a[href")) expect(count, `${at}: Settings link missing`).toBe(1);
        for (let i = 0; i < count; i++) {
          const m = await topmost(page, selector, i);
          expect(m.inView, `${at}: ${selector}[${i}] cannot be scrolled into view`).toBe(true);
          expect(m.top, `${at}: ${selector}[${i}] is covered`).toBe(true);
        }
      }

      const clash = await page.evaluate(() => {
        const aside = [...document.querySelectorAll("aside")].find((a) => a.getClientRects().length);
        const footer = aside?.querySelector<HTMLElement>(":scope > div.border-t");
        const f = footer?.getBoundingClientRect();
        if (!f) return ["footer missing"];
        return [...(aside?.querySelectorAll<HTMLElement>("nav a") ?? [])]
          .filter((a) => {
            const r = a.getBoundingClientRect();
            return r.height > 0 && r.bottom > f.top + 1 && r.top < f.bottom - 1;
          })
          .map((a) => a.textContent ?? "");
      });
      expect(clash, `${at}: nav links overlap the account footer`).toEqual([]);
      const sideways = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(sideways, `${at}: sideways overflow`).toBeLessThanOrEqual(0);
    }
  });
}

test("sidebar footer - keyboard reaches the footer with a visible focus ring", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 360 });
  await page.goto("/app");
  await expect(page.locator("aside.sticky").getByText("Local session")).toBeVisible();
  const settings = page.locator('aside.sticky a[href="/app/settings"]');
  await page.locator("aside.sticky").getByRole("link", { name: "Demo gallery" }).focus();
  await page.keyboard.press("Tab");
  await expect(settings).toBeFocused();
  await expect(settings).toBeInViewport({ ratio: 1 });
  const outline = await settings.evaluate((el) => getComputedStyle(el).outlineStyle);
  expect(outline).toBe("solid");
});
