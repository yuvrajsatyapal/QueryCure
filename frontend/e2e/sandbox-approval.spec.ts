import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { advanceTo } from "./wizard";
import { applyTheme } from "./theme";

/** Mode C through the real stack (API, worker, metadata DB, sandbox PostgreSQL) with the
 * offline stub LLM: the run must stop for approval with the exact SQL on screen, and only
 * after approval benchmark in the sandbox and show a tournament verdict. */
test("sandbox - approve the candidate SQL, then see the benchmarked tournament", async ({ page }) => {
  await page.goto("/app/investigations/new");
  await advanceTo(page, "Plan source", "Check and continue");
  await page.getByRole("radio", { name: /Demo workload/ }).check();
  await page.getByLabel("Workload", { exact: true }).selectOption("orders_ecommerce");
  await page.getByLabel("Scale factor").selectOption("0.01");

  await advanceTo(page, "Investigation mode");
  await expect(page.getByRole("radio", { name: /Sandbox benchmark/ })).toBeChecked();
  await advanceTo(page, "Review & start");
  await page.getByLabel("Title").fill(`E2E sandbox ${Date.now()}`);
  await expect(page.getByText(/Demo workload · orders_ecommerce@v\d+:sf=0\.01:seed=\d+/).first()).toBeVisible();
  await page.getByRole("button", { name: "Start investigation" }).click();
  await expect(page).toHaveURL(/\/app\/investigations\/[0-9a-f-]{36}$/, { timeout: 30_000 });

  const card = page.getByRole("region", { name: "Approval required" });
  await expect(card).toBeVisible({ timeout: 60_000 });
  await expect(card.getByText("CREATE INDEX ON orders (customer_id, created_at)")).toBeVisible();
  await expect(card.getByText(/Nothing has run yet/)).toBeVisible();
  // Deterministic description derived from the DDL (FINAL_UI_POLISH §2.2), key kept beside it.
  await expect(card.getByText("Composite index on orders (customer_id, created_at)")).toBeVisible();
  await expect(page.locator("header").getByText("Approval required", { exact: true })).toBeVisible();

  // Workstream 2: the review drawer shows the same request in detail; approve from it.
  const opener = card.getByRole("button", { name: "Review details" });
  await opener.click();
  const drawer = page.getByRole("dialog", { name: "Benchmark this change in a sandbox?" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole("region", { name: /^statement · oc_/ })).toHaveText("CREATE INDEX ON orders (customer_id, created_at)");
  await expect(drawer.getByText(/^[0-9a-f]{64}$/)).toBeVisible();
  await expect(drawer.getByText(/Nothing measured yet/)).toBeVisible();
  for (const scheme of ["light", "dark"] as const) {
    await applyTheme(page, scheme);
    const result = await new AxeBuilder({ page }).include('[role="dialog"]').withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    expect(result.violations, `${scheme}: ${result.violations.map((v) => v.id).join(", ")}`).toEqual([]);
  }
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(opener).toBeFocused();

  // Phone footer: the count on its own line, both actions on one row, unwrapped and inside the
  // sheet, never covering the last candidate once scrolled to the end; no sideways scrolling.
  const desktop = page.viewportSize();
  for (const width of [320, 375, 390]) {
    await page.setViewportSize({ width, height: 700 });
    await opener.click();
    await expect(drawer).toBeVisible();
    const decline = drawer.getByRole("button", { name: "Decline all" });
    const approve = drawer.getByRole("button", { name: "Approve selected" });
    const count = drawer.getByText(/^\d+ of \d+ selected$/);
    const [d, a, c, sheet] = await Promise.all([decline.boundingBox(), approve.boundingBox(), count.boundingBox(), drawer.boundingBox()]);
    if (!d || !a || !c || !sheet) throw new Error(`footer not laid out at ${width}px`);
    expect(Math.abs(d.y + d.height / 2 - (a.y + a.height / 2)), `${width}px: actions share a row`).toBeLessThan(1);
    expect(c.y + c.height, `${width}px: count above the actions`).toBeLessThanOrEqual(d.y);
    expect(a.x + a.width, `${width}px: approve inside the sheet`).toBeLessThanOrEqual(sheet.x + sheet.width);
    for (const b of [decline, approve]) {
      expect(await b.evaluate((el) => el.scrollWidth <= el.clientWidth && el.getBoundingClientRect().height < 48), `${width}px: unwrapped`).toBe(true);
    }
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, `${width}px: page overflow`).toBe(0);
    expect(await drawer.evaluate((el) => el.scrollWidth - el.clientWidth), `${width}px: sheet overflow`).toBe(0);
    const last = drawer.getByRole("article").last();
    await drawer.getByText("If you approve").scrollIntoViewIfNeeded();
    const [lastBox, footerTop] = await Promise.all([last.boundingBox(), decline.evaluate((el) => el.closest("footer")?.getBoundingClientRect().top ?? 0)]);
    if (!lastBox) throw new Error("last candidate not laid out");
    expect(lastBox.y + lastBox.height, `${width}px: footer clears the last candidate`).toBeLessThanOrEqual(footerTop);
    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();
  }
  if (desktop) await page.setViewportSize(desktop);

  // A server refusal (409, as the API answers an expired request) closes the request at once even
  // though the list still says pending: the server's message stays, and no decision is offered.
  // Browser-side only; the real request stays pending and is approved below after a reload.
  let refusals = 0;
  await page.route("**/api/v1/approvals/*/decision", (route) => {
    refusals += 1;
    return route.fulfill({ status: 409, json: { error: { code: "INVALID_STATE", message: "This approval request has expired.", details: [], request_id: "e2e-refusal" } } });
  });
  await page.route("**/api/v1/runs/*/approvals", (route) => route.fulfill({ status: 503, json: { error: { code: "UNAVAILABLE", message: "held back by the test", details: [], request_id: null } } }));
  await opener.click();
  await drawer.getByRole("button", { name: "Approve selected" }).click();
  const refused = page.getByRole("dialog", { name: "Decision not recorded" });
  await expect(refused.getByRole("alert").filter({ hasText: "This approval request has expired." })).toBeVisible();
  await expect(refused.getByText(/No decision was recorded and nothing ran in the sandbox/)).toBeVisible();
  await expect(refused.getByRole("button", { name: /Approve|Decline/ })).toHaveCount(0);
  await expect(refused.getByRole("button", { name: "Close", exact: true })).toBeVisible();
  await page.keyboard.press("Enter");
  expect(refusals).toBe(1);
  await page.unroute("**/api/v1/approvals/*/decision");
  await page.unroute("**/api/v1/runs/*/approvals");
  await page.reload();
  await expect(card).toBeVisible({ timeout: 15_000 });
  await opener.click();
  await drawer.getByRole("button", { name: "Approve selected" }).click();
  await expect(page.getByRole("dialog", { name: "Decision recorded" }).getByText(/Approved: 1 of 1 candidate will be benchmarked/)).toBeVisible({ timeout: 15_000 });
  await expect(card).toBeHidden({ timeout: 15_000 });
  await page.getByRole("dialog", { name: "Decision recorded" }).getByRole("button", { name: "Close", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1 })).toBeFocused();
  const timeline = page.getByRole("region", { name: "Agent timeline" });
  await expect(timeline.getByText("Approval approved")).toBeVisible({ timeout: 15_000 });
  await expect(timeline.getByText(/Run completed/).first()).toBeVisible({ timeout: 90_000 });

  // Final polish (FINAL_UI_POLISH §2.1): the sealed conclusion is above the trace, no tab switch.
  const summary = page.getByRole("region", { name: "Result summary" });
  await expect(summary).toBeVisible({ timeout: 30_000 });
  await expect(summary.getByRole("heading", { level: 2 })).toHaveText(/Verified recommendation|Unverified recommendations|Inconclusive|No action needed/);
  await expect(summary.getByText(/Nothing was applied to your database/)).toBeVisible();
  await summary.getByRole("button", { name: "Full report" }).click();
  await expect(page.getByRole("article", { name: "Final report" })).toBeVisible({ timeout: 15_000 });
  await summary.getByRole("button", { name: "Benchmark details" }).click();
  // Phase 3 studio: the verdict card and gates first; the full tables behind a toggle.
  await expect(page.getByRole("heading", { name: "Candidate comparison" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("region", { name: /^Verdict · oc_/ }).getByText("Predicted · not measured")).toBeVisible();
  await expect(page.getByRole("region", { name: /^Correctness and audit gates · oc_/ })).toBeVisible();
  await page.getByRole("button", { name: "Show data tables" }).click();
  const table = page.getByRole("table", { name: "Optimization tournament" });
  await expect(table).toBeVisible({ timeout: 15_000 });
  // Any deterministic verdict is legitimate on shared CI hardware, including the noise-warning
  // verification (ADR-0019) and an auditor downgrade to inconclusive (ADR-0009).
  await expect(
    table.getByText(/Verified · tested scope|Verified · noise warning|Inconclusive|Rejected/).first(),
  ).toBeVisible();
  await expect(page.getByRole("table", { name: /Baseline versus candidate/ })).toBeVisible();
  await expect(page.getByText(/Measured in the sandbox/)).toBeVisible();

  // Pass 4 (UI_UX §3.17): recorded samples, speedup with the 1× reference, warnings, verdicts.
  await expect(page.getByRole("region", { name: "Recommendation verdicts" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Measurement warnings" }).getByText(/Host contention is not recorded/)).toBeVisible();
  await expect(page.getByRole("img", { name: /^Latency distribution · experiment [0-9a-f]{8} · round 1 · param set / })).toBeVisible();
  // A speedup is drawn only when the engine recorded a valid one; otherwise the row says why.
  await expect(page.getByRole("figure", { name: /Speedup with 95% CI/ }).getByText("1× no change").first()).toBeVisible();
  await expect(table.getByText("Composite index on orders (customer_id, created_at)")).toBeVisible();
  // Result correctness from recorded fingerprints (UI_UX §3.8), and the statistics glossary.
  const correctness = page.getByRole("region", { name: /^Result correctness · oc_/ });
  await expect(correctness).toBeVisible();
  await expect(correctness.getByRole("table", { name: /Result fingerprints/ })).toBeVisible();
  await expect(correctness.getByText(/not a proof that the two queries are equivalent/)).toBeVisible();
  await page.getByText("How to read these numbers").click();
  await expect(page.getByText(/Faster is not the same as verified/)).toBeVisible();
  // Plan diff (UI rebuild Phase 4): both layouts, plan-capture figures labelled apart from the
  // benchmark, and the node-metrics panel by keyboard with focus returned on close.
  const planDiff = page.getByRole("region", { name: "Plan diff" });
  await expect(planDiff.getByRole("combobox", { name: "Candidate" })).toBeVisible();
  await expect(planDiff.getByRole("table", { name: /side by side/ })).toBeVisible({ timeout: 15_000 });
  await expect(planDiff.getByText("One EXPLAIN ANALYZE capture after timing")).toBeVisible();
  const marker = planDiff.getByRole("button", { name: /: show recorded metrics$/ }).first();
  await marker.focus();
  await page.keyboard.press("Enter");
  const nodeMetrics = planDiff.getByRole("region", { name: /^Recorded metrics · / });
  await expect(nodeMetrics).toBeVisible();
  await nodeMetrics.getByRole("button", { name: "Close node metrics" }).click();
  await expect(marker).toBeFocused();
  await planDiff.getByRole("button", { name: "Unified" }).click();
  await expect(planDiff.getByRole("table", { name: /one list/ })).toBeVisible();
  await marker.click();
  for (const scheme of ["light", "dark"] as const) {
    await applyTheme(page, scheme);
    const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    const summary = result.violations.map((v) => `${v.id} (${v.impact}): ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(" | ")}`);
    expect(summary, `tournament tab in ${scheme} mode`).toEqual([]);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  // Polled: read straight after the resize, scrollWidth can still be the 1440px layout's.
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);

  // Evidence tab (UI_UX §3.18): recorded links from the run, the auditor's citations included.
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("button", { name: "Results", exact: true }).click();
  await page.getByRole("tab", { name: "Evidence" }).click();
  const evidence = page.getByRole("region", { name: "Evidence relationships" });
  await expect(evidence.getByRole("button", { name: /^Verdict oc_/ }).first()).toBeVisible({ timeout: 15_000 });
  await expect(evidence.getByRole("list", { name: "Link legend" }).getByText(/Inferred by QueryCure/)).toBeVisible();
  await evidence.getByRole("button", { name: /^Evidence ev_[0-9a-f]{12} · benchmark_metric/ }).first().click();
  const record = evidence.getByRole("complementary", { name: "Selected record" });
  await expect(record.getByText(/measured by this run/)).toBeVisible();
  await expect(record.getByText("from audit check", { exact: false }).first()).toBeVisible();
  for (const scheme of ["light", "dark"] as const) {
    await applyTheme(page, scheme);
    const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    const summary = result.violations.map((v) => `${v.id} (${v.impact}): ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(" | ")}`);
    expect(summary, `evidence tab in ${scheme} mode`).toEqual([]);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  // Polled: read straight after the resize, scrollWidth can still be the 1440px layout's.
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);

  // Workstream 3 (UI_UX §3.15): the run-scoped palette lists the candidate with its recorded status
  // (no speed-up figure) and jumps to its plan diff, opening the folded phone section.
  await page.keyboard.press("ControlOrMeta+k");
  const palette = page.getByRole("dialog", { name: "Command palette" });
  await expect(palette.getByRole("combobox", { name: "Search Run #1 and commands" })).toBeFocused();
  const candidate = palette.getByRole("group", { name: "Candidates" }).getByRole("option", { name: /Composite index on orders/ });
  await expect(candidate).toContainText(/Verified · tested scope|Verified · noise warning|Inconclusive|Rejected|Benchmarking/);
  await expect(candidate).not.toContainText("×");
  const box = await palette.boundingBox();
  expect(box && box.x >= 0 && box.x + box.width <= 390).toBe(true);
  for (const scheme of ["light", "dark"] as const) {
    await applyTheme(page, scheme);
    const result = await new AxeBuilder({ page }).include('[role="dialog"]').withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    expect(result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`), `sandbox palette, ${scheme}`).toEqual([]);
  }
  await page.keyboard.type("plan diff");
  await expect(palette.getByRole("group", { name: "Plan diffs" }).getByRole("option", { name: /baseline → oc_/ })).toBeVisible({ timeout: 10_000 });
  await page.keyboard.press("Enter");
  await expect(palette).toBeHidden();
  await expect(page.getByRole("tab", { name: "Tournament" })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("details[data-bench-section][open]").filter({ hasText: "Execution-plan differences" })).toBeVisible();
  const heading = page.getByRole("heading", { name: /^Plan diff · baseline → oc_/ });
  await expect(heading).toBeFocused();
  // Chosen by keyboard: a visible ring, flush to the heading so it stays off the description below.
  const ring = await heading.evaluate((h) => {
    const s = getComputedStyle(h);
    const next = h.nextElementSibling?.getBoundingClientRect().top ?? Infinity;
    return { style: s.outlineStyle, width: parseFloat(s.outlineWidth), offset: parseFloat(s.outlineOffset), gap: next - h.getBoundingClientRect().bottom };
  });
  expect(ring.style).toBe("solid");
  expect(ring.offset).toBe(0);
  expect(ring.gap).toBeGreaterThanOrEqual(ring.width);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});
