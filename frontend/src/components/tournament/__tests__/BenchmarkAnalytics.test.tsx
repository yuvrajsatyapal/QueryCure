import { afterEach, expect, test } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
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
  expect(within(forest).getByText("1× no improvement")).toBeDefined();
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
