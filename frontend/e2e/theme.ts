import type { Page } from "@playwright/test";

/** Applies a theme the way next-themes does (class + color-scheme on <html>). Dark is the fixed
 * default (ADR-0030), so emulating prefers-color-scheme alone would never show the light theme. */
export async function applyTheme(page: Page, scheme: "light" | "dark"): Promise<void> {
  await page.emulateMedia({ colorScheme: scheme });
  await page.evaluate((s) => {
    const root = document.documentElement;
    // Like next-themes' disableTransitionOnChange: no colour transition runs during the switch, so axe
    // never samples a control halfway between the two themes.
    const pause = document.createElement("style");
    pause.textContent = "*,*::before,*::after{transition:none!important}";
    document.head.appendChild(pause);
    root.classList.remove("light", "dark");
    root.classList.add(s);
    root.style.colorScheme = s;
    void getComputedStyle(document.body).opacity;
    pause.remove();
  }, scheme);
  await page.waitForFunction((s) => document.documentElement.classList.contains(s), scheme);
}
