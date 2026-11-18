import { expect, test as base, type Page } from "@playwright/test";

export { expect };

// AppBoot (the "Getting QueryCure ready" screen) covers the app, with its own <h1> and a paced
// minimum time per stage, until the account and first list are loaded. A test that asserts straight
// after a page load would measure that overlay, not the page, so loads wait for it to leave.
// Bounded and non-throwing: a spec that deliberately keeps the boot stalled asserts on it itself.
const BOOT_TITLE = "Getting QueryCure ready";
const BOOT_WAIT_MS = 15_000;

async function bootFinished(page: Page): Promise<void> {
  await page
    .getByRole("heading", { name: BOOT_TITLE })
    .waitFor({ state: "detached", timeout: BOOT_WAIT_MS })
    .catch(() => undefined);
}

function waitForBootAfterLoads(page: Page): void {
  for (const method of ["goto", "reload"] as const) {
    const original = page[method].bind(page) as (...args: unknown[]) => Promise<unknown>;
    (page as unknown as Record<string, unknown>)[method] = async (...args: unknown[]) => {
      const response = await original(...args);
      await bootFinished(page);
      return response;
    };
  }
}

export const test = base.extend({
  context: async ({ context }, provide) => {
    context.on("page", waitForBootAfterLoads);
    await provide(context);
  },
});
