import { afterEach, expect, test, vi } from "vitest";
import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ExperimentDetail, OptimizationCandidate, Verification } from "@/lib/api/types";
import recorded from "@/lib/benchmark/__tests__/recorded-result.json";
import { BenchmarkAnalytics } from "../BenchmarkAnalytics";

afterEach(cleanup);

// Recorded locally (Docker, stub model) on 2026-10-23; see lib/benchmark/__tests__.
const ARM = "oc_70a238eea02a";
const detail = {
  id: "2601e225-50b0-5970-8c24-3063b7a929a3",
  runId: "run-1",
  round: 0,
  replicate: 0,
  kind: "single",
  status: "completed",
  engineVersion: "bench@2",
  rowProfile: "qc-row-v1",
  environmentDigest: "abc",
  provenance: "measured",
  config: { minEffect: 1.1, maxRegression: 0.95, maxCv: 0.25, paramSets: [{ name: "hot_customer" }, { name: "regular_customer" }] },
  environment: null,
  blocks: [],
  replication: null,
  result: recorded,
} as unknown as ExperimentDetail;
const candidates = [
  { key: ARM, kind: "create_index", ddl: ["CREATE INDEX ON orders (customer_id, created_at)"], querySql: null, status: "verified" },
  { key: "oc_declined000", kind: "analyze_statistics", ddl: ["ANALYZE orders"], querySql: null, status: "declined" },
] as unknown as OptimizationCandidate[];

test("every chart names its experiment, round and param set", () => {
  render(<BenchmarkAnalytics detail={detail} candidates={candidates} audits={[]} />);

  const dist = screen.getByRole("img", { name: /Latency distribution · experiment 2601e225 · round 1 · param set hot_customer/ });
  expect(dist.getAttribute("aria-label")).toContain("baseline median 0.70 ms, n 30");
  expect(dist.getAttribute("aria-label")).toContain(`${ARM} median 0.44 ms, n 30`);
});

test("param sets are shown one at a time, never pooled", async () => {
  const user = userEvent.setup();
  render(<BenchmarkAnalytics detail={detail} candidates={candidates} audits={[]} />);

  await user.click(screen.getByRole("tab", { name: "regular_customer" }));
  expect(screen.getByRole("img", { name: /param set regular_customer/ })).toBeDefined();
  expect(screen.queryByRole("img", { name: /param set hot_customer/ })).toBeNull();
});

test("the speedup chart marks 1× and draws only recorded intervals", () => {
  render(<BenchmarkAnalytics detail={detail} candidates={candidates} audits={[]} />);

  const forest = screen.getByRole("figure", { name: /Speedup with 95% CI/ });
  // In the legend and as the in-chart label above the 1× line.
  expect(within(forest).getAllByText("1× no change").length).toBeGreaterThanOrEqual(1);
  expect(within(forest).getByText("min effect 1.10×")).toBeDefined();
  const rows = within(forest).getAllByRole("listitem");
  expect(rows).toHaveLength(2); // one candidate × two param sets
  expect(rows[0]!.textContent).toContain("hot_customer");
  expect(rows[0]!.textContent).toContain("1.59× (1.47×–1.69×)");
});

test("a non-comparable arm says why instead of drawing a speedup", () => {
  const mismatch = {
    ...detail,
    result: { ...(recorded as object), verdicts: [{ arm: ARM, verdict: "rejected", gate: 3, reasons: [{ code: "result_mismatch", detail: "rows differ" }] }] },
  } as unknown as ExperimentDetail;
  render(<BenchmarkAnalytics detail={mismatch} candidates={candidates} audits={[]} />);

  const forest = screen.getByRole("figure", { name: /Speedup with 95% CI/ });
  expect(within(forest).getAllByText("Not comparable: results differ from the baseline (result_mismatch).")).toHaveLength(2);
});

test("verdict classes come from the backend, including a disputed and an unverified candidate", () => {
  const audits = [{ candidateKey: ARM, experimentId: detail.id, engineVerdict: "verified", verdict: "inconclusive", auditorDowngraded: true }] as unknown as Verification[];
  render(<BenchmarkAnalytics detail={detail} candidates={candidates} audits={audits} />);

  const summary = screen.getByRole("region", { name: "Recommendation verdicts" });
  expect(within(summary).getByText("Disputed · auditor downgrade")).toBeDefined();
  expect(within(summary).getByText("Engine verdict verified; Benchmark Auditor downgraded it to inconclusive.")).toBeDefined();
  expect(within(summary).getByText("Unverified · not measured")).toBeDefined();
});

test("recorded measurement warnings are listed, and unrecorded host contention is stated", () => {
  render(<BenchmarkAnalytics detail={detail} candidates={candidates} audits={[]} />);

  const warnings = screen.getByRole("region", { name: "Measurement warnings" });
  expect(within(warnings).getByText(/Transport floor 0\.23 ms is 61% of the fastest arm's median/)).toBeDefined();
  expect(within(warnings).getByText(/Host contention is not recorded/)).toBeDefined();
});

test("every recorded sample is available as a table", async () => {
  const user = userEvent.setup();
  render(<BenchmarkAnalytics detail={detail} candidates={candidates} audits={[]} />);

  await user.click(screen.getByText(/Recorded samples · hot_customer/));
  const table = screen.getByRole("table", { name: /Recorded samples, hot_customer/ });
  expect(within(table).getAllByRole("row")).toHaveLength(31); // header + 30 samples
});

test("an experiment without measurements says the data is unavailable", () => {
  const empty = { ...detail, result: { ...(recorded as object), measurements: [], stats: [] } } as unknown as ExperimentDetail;
  render(<BenchmarkAnalytics detail={empty} candidates={candidates} audits={[]} />);

  expect(screen.getByText("No recorded samples for this experiment.")).toBeDefined();
});

test("correctness panel reads the recorded fingerprints and never claims equivalence", async () => {
  const { CorrectnessPanel } = await import("../CorrectnessPanel");
  render(<CorrectnessPanel result={recorded as unknown as NonNullable<ExperimentDetail["result"]>} arm={ARM} />);
  const panel = screen.getByRole("region", { name: `Result correctness · ${ARM}` });
  expect(within(panel).getByText("Same rows as the baseline on every param set")).toBeTruthy();
  expect(within(panel).getByText(/compared as a multiset/)).toBeTruthy();
  expect(within(panel).getAllByText("20 / 20")).toHaveLength(1);
  expect(within(panel).getByLabelText(/^baseline row hash 9183cfaa8528/)).toBeTruthy();
  expect(within(panel).getByText(/not a proof that the two queries are equivalent/)).toBeTruthy();
});

test("stats glossary explains the terms and that faster is not verified", async () => {
  const { StatsGlossary } = await import("../StatsGlossary");
  render(<StatsGlossary />);
  await userEvent.click(screen.getByText("How to read these numbers"));
  for (const term of ["Speedup", "IQR", "Robust CV", "Transport floor"]) expect(screen.getByText(term)).toBeTruthy();
  expect(screen.getByText(/Faster is not the same as verified/)).toBeTruthy();
});

test("the studio rail selects an arm; its verdict card keeps measured and predicted apart", async () => {
  const user = userEvent.setup();
  const withPrediction = [
    { ...candidates[0], expectedBenefit: "Removes the sort", estimatedCost: { indexSizeEstimateBytes: 2048, writeOverhead: "low" } },
    candidates[1],
  ] as unknown as OptimizationCandidate[];
  render(<BenchmarkAnalytics detail={detail} candidates={withPrediction} audits={[]} />);
  const rail = screen.getByRole("region", { name: "Recommendation verdicts" });
  expect(within(rail).getByText("Baseline")).toBeDefined();
  const first = within(rail).getByRole("button", { name: new RegExp(`${ARM}: Verified · tested scope, 1\\.59× on hot_customer`) });
  expect(first.getAttribute("aria-pressed")).toBe("true");
  const card = screen.getByRole("region", { name: `Verdict · ${ARM}` });
  // Measured: the recorded interval and the recorded index build.
  expect(within(card).getByText(/95% CI 1\.47×–1\.69× · hot_customer · n 30\/30/)).toBeDefined();
  expect(within(card).getByText(/Index build 328 kB/)).toBeDefined();
  // Predicted: the agent's expectation, labelled as not measured.
  expect(within(card).getByText("Predicted · not measured")).toBeDefined();
  expect(within(card).getByText("Removes the sort")).toBeDefined();
  expect(within(card).getByText(/est\. index size 2 kB/)).toBeDefined();

  await user.click(within(rail).getByRole("button", { name: /oc_declined000/ }));
  const declined = screen.getByRole("region", { name: "Verdict · oc_declined000" });
  expect(within(declined).getByText(/unverified · not measured/)).toBeDefined();
  // One line per param set, each saying why nothing is drawn.
  expect(within(declined).getAllByText(/No speedup statistic recorded/)).toHaveLength(2);
});

test("gates show the correctness outcome, the rule verdict and the auditor's recorded checks", () => {
  const audits = [
    {
      candidateKey: ARM,
      candidateId: "c1",
      experimentId: detail.id,
      round: 0,
      engineVerdict: "verified",
      verdict: "verified",
      auditorDowngraded: false,
      auditorStatus: "completed",
      auditorNotes: null,
      auditorPromptVersion: "auditor@1",
      reasons: [],
      checks: [
        { name: "rescore", status: "pass", detail: "re-scored with bench@2", evidenceIds: [] },
        { name: "transport_floor", status: "warn", detail: "relay path", evidenceIds: [] },
      ],
      auditorConcerns: [],
    },
  ] as unknown as Verification[];
  render(<BenchmarkAnalytics detail={detail} candidates={candidates} audits={audits} />);
  const gates = screen.getByRole("region", { name: `Correctness and audit gates · ${ARM}` });
  expect(within(gates).getByText("Same rows as the baseline on every param set")).toBeDefined();
  expect(within(gates).getByText("Rule verdict: verified")).toBeDefined();
  expect(within(gates).getByText("Transport floor dominates the fastest arm")).toBeDefined();
  const checks = within(gates).getByRole("list", { name: "Auditor checks" });
  expect(within(checks).getByText("rescore")).toBeDefined();
  expect(within(checks).getByText("warning:")).toBeDefined();
  expect(within(gates).getByText(/It can only downgrade/)).toBeDefined();
});

test("each speedup row keeps the candidate, its param set, the measured ratio and n together in one header", () => {
  render(<BenchmarkAnalytics detail={detail} candidates={candidates} audits={[]} />);
  const forest = screen.getByRole("figure", { name: /Speedup with 95% CI/ });
  const [row] = within(forest).getAllByRole("listitem");
  const head = row!.querySelector<HTMLElement>("[data-row-head]");
  expect(head).not.toBeNull();
  const text = head!.textContent ?? "";
  for (const part of [ARM, "param set hot_customer", "1.59× (1.47×–1.69×)", "n 30 / 30"]) expect(text).toContain(part);
  // The interval strip follows its header inside the same row.
  expect(within(row!).getByRole("img", { name: /on hot_customer: ratio 1\.59×/ })).toBeDefined();
});

test("timing distributions keep a compact key visible and the full explanation in a disclosure", async () => {
  const user = userEvent.setup();
  render(<BenchmarkAnalytics detail={detail} candidates={candidates} audits={[]} />);
  const dist = screen.getByRole("region", { name: "Timing distributions" });
  const key = within(dist).getByRole("list", { name: "Chart key" });
  expect(key.textContent).toContain("median");
  expect(key.textContent).toContain("outliers");
  expect(key.textContent).toContain("transport floor 0.23 ms");

  const howTo = within(dist).getByText("How to read this chart");
  expect(howTo.tagName).toBe("SUMMARY");
  const details = howTo.closest("details")!;
  expect(details.open).toBe(false);
  await user.click(howTo);
  expect(details.open).toBe(true);
  for (const term of ["Q1–Q3", "whisker", "1.5×IQR", "log scale", "spread vertically", "arrow keys"]) expect(details.textContent).toContain(term);
  // The recorded-samples disclosure is still there.
  expect(within(dist).getByText(/^Recorded samples · hot_customer/).tagName).toBe("SUMMARY");
  expect(within(dist).getByText(/^Recorded samples · hot_customer/).textContent).toBe("Recorded samples · hot_customer · n 30 / 30");
});

test("each sample can be read from the keyboard; outliers are marked, never removed", async () => {
  const user = userEvent.setup();
  render(<BenchmarkAnalytics detail={detail} candidates={candidates} audits={[]} />);
  const samples = screen.getByRole("slider", { name: "baseline samples, hot_customer" });
  expect(samples.getAttribute("aria-valuemax")).toBe("30");
  act(() => samples.focus());
  // Focus starts at the fastest recorded sample; End jumps to the slowest.
  const fastest = Math.min(...recorded.measurements.find((m) => m.arm === "baseline" && m.paramSet === "hot_customer")!.latenciesNs);
  expect(samples.getAttribute("aria-valuetext")).toContain(`${(fastest / 1e6).toFixed(2)} ms`);
  await user.keyboard("{End}");
  expect(samples.getAttribute("aria-valuenow")).toBe("30");
  expect(samples.getAttribute("aria-valuetext")).toContain("1.06 ms · outlier (beyond 1.5×IQR)");
  await user.keyboard("{ArrowLeft}");
  expect(samples.getAttribute("aria-valuenow")).toBe("29");
  // The chart's name counts the outliers; the table still lists all 30 samples.
  const dist = screen.getByRole("img", { name: /Latency distribution/ });
  expect(dist.getAttribute("aria-label")).toMatch(/baseline median 0\.70 ms, n 30, \d+ outliers?/);
});

test("a speedup interval states its exact values and sample counts on focus", async () => {
  render(<BenchmarkAnalytics detail={detail} candidates={candidates} audits={[]} />);
  const strip = screen.getByRole("img", { name: `${ARM} on hot_customer: ratio 1.59× (95% CI 1.47×–1.69×), interval above 1×; n 30 baseline / 30 candidate samples` });
  act(() => strip.focus());
  expect(strip.textContent).toContain("1.59× · 95% CI 1.47×–1.69×");
  expect(strip.textContent).toContain("n 30/30");
});

test("intervals clustered near 1× are drawn on a widened axis that says so", () => {
  const stats = (recorded as { stats: object[] }).stats.map((s) => ({ ...s, speedup: 1.03, ciLow: 1.01, ciHigh: 1.05 }));
  const near = { ...detail, config: { paramSets: detail.config && [{ name: "hot_customer" }, { name: "regular_customer" }] }, result: { ...(recorded as object), stats } } as unknown as ExperimentDetail;
  render(<BenchmarkAnalytics detail={near} candidates={candidates} audits={[]} />);
  const forest = screen.getByRole("figure", { name: /Speedup with 95% CI/ });
  expect(within(forest).getByText(/widened to at least a 1\.32× range so small differences are not exaggerated/)).toBeDefined();
  // The recorded values are printed unchanged.
  expect(within(forest).getAllByText("1.03× (1.01×–1.05×)")).toHaveLength(2);
  expect(within(forest).getAllByRole("img", { name: /interval above 1×/ })).toHaveLength(2);
});

test("on a phone, secondary sections collapse with summaries; the verdict, interval, correctness and warnings stay open", async () => {
  const user = userEvent.setup();
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: query === "(max-width: 767px)", addEventListener: () => {}, removeEventListener: () => {} }));
  render(<BenchmarkAnalytics detail={detail} candidates={candidates} audits={[]} />);
  // Always visible: the verdict card with interval, sample counts, scope and correctness; warnings.
  const card = screen.getByRole("region", { name: `Verdict · ${ARM}` });
  expect(within(card).getByText(/95% CI 1\.47×–1\.69× · hot_customer · n 30\/30/)).toBeDefined();
  expect(within(card).getByText(/Correctness: Same rows as the baseline on every param set/)).toBeDefined();
  expect(within(card).getByText(/Tested scope: 2 param sets \(hot_customer, regular_customer\), never pooled/)).toBeDefined();
  expect(screen.getByRole("region", { name: "Measurement warnings" })).toBeDefined();
  expect(screen.getByRole("figure", { name: /Speedup with 95% CI/ })).toBeDefined();
  // Collapsed by default, each with a summary; several can be open at once.
  const dist = screen.getByText("Timing distributions").closest("details")!;
  const gates = screen.getByText("Correctness and auditor checks").closest("details")!;
  expect(dist.open).toBe(false);
  expect(gates.open).toBe(false);
  expect(within(gates).getByText(/correctness passed · rule verdict verified · not audited yet/)).toBeDefined();
  await user.click(within(dist).getByText("Timing distributions"));
  await user.click(within(gates).getByText("Correctness and auditor checks"));
  expect(dist.open && gates.open).toBe(true);
  vi.unstubAllGlobals();
});

test("on a phone, auditor warnings keep the checks section open and flagged", () => {
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: query === "(max-width: 767px)", addEventListener: () => {}, removeEventListener: () => {} }));
  const audits = [
    { candidateKey: ARM, experimentId: detail.id, engineVerdict: "verified", verdict: "verified", auditorDowngraded: false, auditorStatus: "completed", checks: [{ name: "dispersion", status: "warn", detail: "noisy", evidenceIds: [] }], auditorConcerns: [] },
  ] as unknown as Verification[];
  render(<BenchmarkAnalytics detail={detail} candidates={candidates} audits={audits} />);
  const gates = screen.getByText("Correctness and auditor checks").closest("details")!;
  expect(gates.open).toBe(true);
  expect(within(gates).getByText(/Needs attention/)).toBeDefined();
  expect(within(gates).getByText(/auditor 0 pass, 1 warning/)).toBeDefined();
  vi.unstubAllGlobals();
});
