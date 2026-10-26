import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { waitForShortcuts } from "./shortcuts";
import { applyTheme } from "./theme";

/** UI Pass 3 (UI_UX §3.14–3.15): the guided New investigation flow and the command palette,
 * driven by keyboard only, against the real stack with the offline stub LLM. */
test("keyboard - start an investigation by keyboard, title suggested from the SQL, then switch tabs", async ({ page }) => {
  await page.goto("/app/investigations/new");
  const editor = page.getByRole("textbox", { name: "SQL query" });
  await editor.focus();
  // Tab leaves CodeMirror (no indent-with-tab), then Enter on the focused button checks the SQL.
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Check and continue" })).toBeFocused();
  await page.keyboard.press("Enter");

  // Focus moves to the newly opened step; arrow keys pick a plan source.
  await expect(page.getByRole("heading", { name: /Plan source/ })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("radio", { name: /Upload plan/ })).toBeFocused();
  for (let i = 0; i < 3; i += 1) await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("radio", { name: /No plan/ })).toBeChecked();
  await page.keyboard.press("ControlOrMeta+Enter");

  await expect(page.getByRole("heading", { name: /Investigation mode/ })).toBeFocused();
  await expect(page.getByRole("radio", { name: /Live inspection/ })).toBeDisabled();
  await page.keyboard.press("ControlOrMeta+Enter");

  const suggestion = "orders · where customer_id · order by created_at · limit 20";
  await expect(page.getByLabel("Title")).toHaveAttribute("placeholder", suggestion);
  await page.keyboard.press("ControlOrMeta+Enter");

  await expect(page).toHaveURL(/\/app\/investigations\/[0-9a-f-]{36}$/, { timeout: 30_000 });
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(suggestion, { timeout: 30_000 });

  const tab = (name: string) => page.getByRole("tab", { name, exact: true });
  await expect(tab("Findings")).toHaveAttribute("aria-selected", "true");
  await page.locator("body").focus();
  await page.keyboard.press("g");
  await page.keyboard.press("p");
  await expect(tab("Plan")).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("]");
  await expect(tab("Report")).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("[");
  await expect(tab("Plan")).toHaveAttribute("aria-selected", "true");

  // Workstream 3 (UI_UX §3.15): from a run, ⌘K searches that run first; Backspace widens the scope.
  await page.keyboard.press("ControlOrMeta+k");
  const palette = page.getByRole("dialog", { name: "Command palette" });
  const scoped = palette.getByRole("combobox", { name: "Search Run #1 and commands" });
  await expect(scoped).toBeFocused();
  await expect(palette.getByRole("button", { name: "Leave Run #1 scope and search everywhere" })).toBeVisible();
  await page.keyboard.type("stub finding");
  const finding = palette.getByRole("group", { name: "Findings" }).getByRole("option", { name: /Stub finding/ }).first();
  // The run may still be finishing: results join the open palette as they are recorded.
  await expect(finding).toBeVisible({ timeout: 30_000 });
  for (const scheme of ["light", "dark"] as const) {
    await applyTheme(page, scheme);
    const result = await new AxeBuilder({ page }).include('[role="dialog"]').withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    expect(result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`), `scoped palette, ${scheme}`).toEqual([]);
  }
  await page.keyboard.press("Enter");
  await expect(palette).toBeHidden();
  await expect(tab("Findings")).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("[data-claim]:focus")).toContainText("Stub finding");

  // Nothing in the run matches: the first option searches every investigation with the same query.
  await page.keyboard.press("ControlOrMeta+k");
  await expect(scoped).toBeFocused();
  await page.keyboard.type("zz no such thing");
  await expect(palette.getByText("Nothing in Run #1 matches.")).toBeVisible();
  const widen = palette.getByRole("option", { name: "Search all investigations for “zz no such thing”" });
  await expect(widen).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Enter");
  const everywhere = palette.getByRole("combobox", { name: "Search commands and investigations" });
  await expect(everywhere).toBeFocused();
  await expect(everywhere).toHaveValue("zz no such thing");
  await expect(palette.getByText("No matching investigations.")).toBeVisible({ timeout: 10_000 });
  await page.keyboard.press("Escape");
  await expect(palette).toBeHidden();

  await page.keyboard.press("ControlOrMeta+k");
  await expect(scoped).toBeFocused();
  await page.keyboard.press("Backspace");
  await expect(palette.getByRole("combobox", { name: "Search commands and investigations" })).toBeFocused();
  await expect(palette.getByRole("group", { name: "Recent investigations" })).toBeVisible({ timeout: 10_000 });
  await page.keyboard.press("Escape");
  await expect(palette).toBeHidden();
});

test("keyboard - palette navigates and searches; shortcuts dialog; g sequences; axe with the palette open", async ({ page }) => {
  // A short window makes the palette's results overflow, so axe always checks the scroll region.
  await page.setViewportSize({ width: 1280, height: 420 });
  await page.goto("/app");
  await waitForShortcuts(page);

  await page.keyboard.press("ControlOrMeta+k");
  const palette = page.getByRole("dialog", { name: "Command palette" });
  await expect(palette).toBeVisible();
  await expect(palette.getByRole("combobox")).toBeFocused();
  await page.waitForLoadState("networkidle");
  for (const scheme of ["light", "dark"] as const) {
    await applyTheme(page, scheme);
    const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    expect(result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`), scheme).toEqual([]);
  }
  await page.keyboard.type("history");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/app\/history$/);
  await expect(palette).toBeHidden();

  // Title search goes through the API: an investigation from the previous test is findable.
  await page.keyboard.press("ControlOrMeta+k");
  await page.keyboard.type("customer_id");
  const hit = palette.getByRole("option", { name: /orders · where customer_id/ }).first();
  await expect(hit).toBeVisible({ timeout: 10_000 });
  await page.keyboard.press("Escape");
  await expect(palette).toBeHidden();

  await page.keyboard.press("?");
  const help = page.getByRole("dialog", { name: "Keyboard shortcuts" });
  await expect(help).toContainText("Go to Connections");
  await expect(help.getByRole("button", { name: "Close keyboard shortcuts" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(help).toBeHidden();

  await page.keyboard.press("g");
  await page.keyboard.press("c");
  await expect(page).toHaveURL(/\/app\/connections$/);

  // Single keys are ignored while typing in a field.
  await page.goto("/app/history");
  await page.getByLabel("Search titles").focus();
  await page.keyboard.press("c");
  await expect(page).toHaveURL(/\/app\/history$/);
  await expect(page.getByLabel("Search titles")).toHaveValue("c");
});

test("keyboard - ⌘K under 6x CPU throttling once shortcuts are ready; Esc restores focus; one listener across pages; both themes", async ({ page }) => {
  const cdp = await page.context().newCDPSession(page);
  // Slow enough that hydration trails the server-rendered shell (the CI race), on a cold cache.
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 6 });
  const keydownListeners = async () => {
    const { result } = await cdp.send("Runtime.evaluate", { expression: "window" });
    const { listeners } = await cdp.send("DOMDebugger.getEventListeners", { objectId: result.objectId ?? "" });
    return listeners.filter((l) => l.type === "keydown").length;
  };
  const palette = page.getByRole("dialog", { name: "Command palette" });
  const nav = page.getByRole("navigation", { name: "Main" });

  await page.goto("/app");
  await waitForShortcuts(page);
  const baseline = await keydownListeners();
  await expect(page.getByRole("heading", { level: 1, name: "Dashboard" })).toBeVisible({ timeout: 30_000 });
  const history = nav.getByRole("link", { name: "History" });
  await history.focus();
  await page.keyboard.press("ControlOrMeta+k");
  await expect(palette).toBeVisible();
  await expect(palette.getByRole("combobox")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(palette).toBeHidden();
  await expect(history).toBeFocused();

  // Client-side navigation keeps the one provider: still ready, one press still opens the palette
  // (it toggles, so a duplicate listener would close it again), and no listener piles up.
  for (const [key, url] of [["h", /\/app\/history$/], ["c", /\/app\/connections$/], ["d", /\/app$/]] as const) {
    await page.locator("body").focus();
    await page.keyboard.press("g");
    await page.keyboard.press(key);
    await expect(page).toHaveURL(url);
    await waitForShortcuts(page);
    await page.keyboard.press("ControlOrMeta+k");
    await expect(palette).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(palette).toBeHidden();
  }
  await expect(page.getByRole("heading", { level: 1, name: "Dashboard" })).toBeVisible();
  expect(await keydownListeners()).toBe(baseline);

  for (const scheme of ["light", "dark"] as const) {
    await applyTheme(page, scheme);
    await page.keyboard.press("ControlOrMeta+k");
    await expect(palette, scheme).toBeVisible();
    await expect(palette.getByRole("combobox"), scheme).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(palette, scheme).toBeHidden();
  }
});

test("keyboard - mobile width: the drawer opens the palette and the guided flow has no sideways scroll", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/app/investigations/new");
  await expect(page.getByRole("button", { name: "Check and continue" })).toBeVisible({ timeout: 30_000 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);

  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("button", { name: /Search or jump to/ }).click();
  const palette = page.getByRole("dialog", { name: "Command palette" });
  await expect(palette).toBeVisible();
  const box = await palette.boundingBox();
  expect(box && box.x >= 0 && box.x + box.width <= 390).toBe(true);
});
