import { expect, type Page } from "@playwright/test";

export type WizardStepTitle = "SQL query" | "Plan source" | "Investigation mode" | "Review & start";

/** The New investigation step that is open now (`aria-current="step"`). */
export function currentStep(page: Page) {
  return page.locator('ol[aria-label="New investigation steps"] > li[aria-current="step"]');
}

export async function expectStep(page: Page, title: WizardStepTitle): Promise<void> {
  await expect(currentStep(page).getByRole("heading", { level: 2 })).toContainText(title);
}

/** Clicks the open step's primary button once it is enabled, then waits for the next step to open.
 * Each transition is asserted, so a click that a pending request rejected cannot go unnoticed. */
export async function advanceTo(page: Page, next: WizardStepTitle, button = "Continue"): Promise<void> {
  const action = currentStep(page).getByRole("button", { name: button, exact: true });
  await expect(action).toBeEnabled();
  await action.click();
  await expectStep(page, next);
}

/** Pastes plan JSON in Plan source and waits until the analysis succeeded and Continue is enabled. */
export async function analyzeUploadedPlan(page: Page, plan: string): Promise<void> {
  await expectStep(page, "Plan source");
  await page.getByLabel("Plan JSON").fill(plan);
  await page.getByRole("button", { name: "Analyze plan" }).click();
  await expect(page.getByRole("treegrid")).toBeVisible();
  await expect(currentStep(page).getByRole("button", { name: "Continue", exact: true })).toBeEnabled();
}
