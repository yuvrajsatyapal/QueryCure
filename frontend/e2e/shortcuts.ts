import { expect, type Page } from "@playwright/test";

/** Waits until the app's keyboard shortcuts are live. The server-rendered shell is visible before
 * hydration attaches the listener, and keys pressed in that gap are lost (CI run 40201784103). */
export async function waitForShortcuts(page: Page): Promise<void> {
  await expect(page.locator("html")).toHaveAttribute("data-shortcuts", "ready", { timeout: 30_000 });
}
