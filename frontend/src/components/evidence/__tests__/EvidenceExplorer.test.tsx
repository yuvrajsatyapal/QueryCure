import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { EvidenceDetail, Finding, Hypothesis, OptimizationCandidate, Verification } from "@/lib/api/types";
import type { ReactNode } from "react";
import type { GraphNode } from "@/lib/evidence/graph";
import { EvidenceExplorer } from "../EvidenceExplorer";

afterEach(cleanup);

const E1 = "ev_000000000001";
const E2 = "ev_000000000002";
const E3 = "ev_000000000003";
const findings = [{ key: "fd_1", agent: "query_analyzer", title: "Seq Scan on orders", detail: "d", severity: "high", evidenceIds: [E1] }] as Finding[];
const hypotheses = [
  { key: "hy_1", rank: 1, category: "missing_index", confidence: "high", statement: "A composite index removes the scan", supportingEvidence: [E1], contradictingEvidence: [], proposedBy: ["index_strategist"], uncertaintyNotes: "", verificationMethod: "benchmark" },
  { key: "hy_2", rank: 2, category: "stale_statistics", confidence: "low", statement: "Statistics are stale", supportingEvidence: [E2], contradictingEvidence: [], proposedBy: ["workload_investigator"], uncertaintyNotes: "", verificationMethod: "stats_refresh" },
] as Hypothesis[];
const candidates = [
  { key: "oc_1", id: "c1", kind: "create_index", ddl: ["CREATE INDEX ON orders (customer_id, created_at)"], querySql: null, addressesHypotheses: ["hy_1"], expectedBenefit: "Removes the sort", estimatedCost: { indexSizeEstimateBytes: 4096, writeOverhead: "low" }, risks: [], round: 0, sqlSha256: "s", status: "verified", proposedBy: "optimization_engineer", rollbackSql: null },
] as unknown as OptimizationCandidate[];
const verifications = [
  { candidateKey: "oc_1", candidateId: "c1", experimentId: "x", round: 0, engineVerdict: "verified", verdict: "verified", auditorDowngraded: false, auditorStatus: "completed", auditorNotes: null, auditorPromptVersion: null, reasons: [], checks: [{ name: "rescore", status: "pass", detail: "ok", evidenceIds: [E3] }], auditorConcerns: [] },
] as unknown as Verification[];
const record = (id: string, kind: string, provenance: string): EvidenceDetail =>
  ({ evidence: { id, kind, provenance, summary: `${kind} summary`, locator: "/nodes/4", data: { node_id: 4 }, artifactSha256: "abcdef0123456789" }, artifact: { kind: "context.plan", sha256: "abcdef0123456789" }, citedByFindings: ["fd_1"], citedByHypotheses: ["hy_1"] }) as EvidenceDetail;
const evidence = new Map<string, EvidenceDetail | "error">([
  [E1, record(E1, "plan_node", "measured")],
  [E2, "error"],
  [E3, record(E3, "benchmark_metric", "measured")],
]);

function renderExplorer(actionsFor: (node: GraphNode) => ReactNode = () => null) {
  render(<EvidenceExplorer findings={findings} hypotheses={hypotheses} candidates={candidates} verifications={verifications} evidence={evidence} actionsFor={actionsFor} />);
  return screen.getByRole("region", { name: "Evidence relationships" });
}

test("the verdict is selected first; records off its chain stay listed, marked and selectable", async () => {
  const user = userEvent.setup();
  const panel = renderExplorer();
  expect(within(panel).getByRole("button", { name: /^Verdict oc_1 · round 1/ }).getAttribute("aria-pressed")).toBe("true");
  expect(within(panel).getByRole("button", { name: /^Candidate oc_1/ })).toBeDefined();
  expect(within(panel).getByRole("button", { name: /^Hypothesis hy_1/ })).toBeDefined();
  expect(within(panel).getByRole("button", { name: /^Finding fd_1/ })).toBeDefined();
  expect(within(panel).getByRole("button", { name: new RegExp(`^Evidence ${E3}`) })).toBeDefined();
  // Selected path (the default): off-path records are quieter, never hidden.
  expect(within(panel).getByRole("button", { name: "Selected path" }).getAttribute("aria-pressed")).toBe("true");
  expect(within(panel).getByRole("button", { name: /^Hypothesis hy_2 .*\(not on the selected path\)$/ })).toBeDefined();
  await user.click(within(panel).getByRole("button", { name: "Everything" }));
  expect(within(panel).getByRole("button", { name: /^Hypothesis hy_2/ }).getAttribute("aria-label")).not.toMatch(/not on the selected path/);
  // An evidence record that failed to load stays listed and says so.
  expect(within(panel).getByRole("button", { name: new RegExp(`^Evidence ${E2} · not loaded`) })).toBeDefined();
});

test("recorded and inferred links are told apart in the legend and in the record", async () => {
  const user = userEvent.setup();
  const panel = renderExplorer();
  const legend = within(panel).getByRole("list", { name: "Link legend" });
  expect(within(legend).getByText("Recorded reference")).toBeDefined();
  expect(within(legend).getByText(/Inferred by QueryCure/)).toBeDefined();
  expect(within(panel).getByText(/recorded links, 1 inferred/)).toBeDefined();
  await user.click(within(panel).getByRole("button", { name: /^Finding fd_1/ }));
  const rec = within(panel).getByRole("complementary", { name: "Selected record" });
  expect(within(rec).getByText("inferred")).toBeDefined();
  expect(within(rec).getByText(`via ${E1}`)).toBeDefined();
  expect(within(rec).getByText("from finding.evidence_ids")).toBeDefined();
});

test("an evidence record shows its provenance, artifact and recorded backlinks, and asks for its actions", async () => {
  const user = userEvent.setup();
  const actionsFor = vi.fn<(node: GraphNode) => ReactNode>(() => <button type="button">Show in plan</button>);
  const panel = renderExplorer(actionsFor);
  await user.click(within(panel).getByRole("button", { name: /^Finding fd_1/ }));
  await user.click(within(panel).getByRole("button", { name: new RegExp(`^Evidence ${E1}`) }));
  const rec = within(panel).getByRole("complementary", { name: "Selected record" });
  expect(within(rec).getByText(/measured by this run/)).toBeDefined();
  expect(within(rec).getByText(/context\.plan · abcdef012345/)).toBeDefined();
  expect(within(rec).getByText(/Cited by \(recorded\): fd_1 · hy_1/)).toBeDefined();
  expect(within(rec).getByRole("button", { name: "Show in plan" })).toBeDefined();
  expect(actionsFor).toHaveBeenLastCalledWith(expect.objectContaining({ id: E1, column: "evidence" }));
});

test("a candidate's record labels its prediction as not measured", async () => {
  const user = userEvent.setup();
  const panel = renderExplorer();
  await user.click(within(panel).getByRole("button", { name: /^Candidate oc_1/ }));
  const rec = within(panel).getByRole("complementary", { name: "Selected record" });
  expect(within(rec).getByText(/the agent's expectation, not measured/)).toBeDefined();
  expect(within(rec).getAllByText("predicted")).toHaveLength(2);
});

test("arrow keys move along the chain and between records of a column", async () => {
  const user = userEvent.setup();
  const panel = renderExplorer();
  within(panel).getByRole("button", { name: /^Verdict oc_1/ }).focus();
  await user.keyboard("{ArrowLeft}");
  expect(document.activeElement?.getAttribute("data-ev-node")).toBe("oc_1");
  await user.keyboard("{ArrowLeft}");
  expect(document.activeElement?.getAttribute("data-ev-node")).toBe("hy_1");
});

test("a link is readable from the record panel: source, target, relationship, field and class", async () => {
  const user = userEvent.setup();
  const panel = renderExplorer();
  await user.click(within(panel).getByRole("button", { name: /^Finding fd_1/ }));
  const rec = within(panel).getByRole("complementary", { name: "Selected record" });
  await user.hover(within(rec).getByRole("button", { name: new RegExp(`^Open evidence ${E1}; link`) }));
  const status = within(panel).getByRole("status");
  expect(status.textContent).toContain(`evidence ${E1} → finding fd_1`);
  expect(status.textContent).toContain("finding cites this evidence");
  expect(status.textContent).toContain("recorded field: finding.evidence_ids");
  // The inferred link names its basis and stays inferred.
  await user.hover(within(rec).getByRole("button", { name: /^Open hypothesis hy_1; link/ }));
  expect(within(panel).getByRole("status").textContent).toMatch(/^inferred.*inferred from shared supporting evidence ev_000000000001/);
  await user.keyboard("{Escape}");
  expect(within(panel).queryByRole("status")).toBeNull();
});

test("contradicting evidence keeps its own class in the record panel", async () => {
  const user = userEvent.setup();
  const contra = [{ ...hypotheses[0]!, contradictingEvidence: [E2] }, hypotheses[1]!] as Hypothesis[];
  render(<EvidenceExplorer findings={findings} hypotheses={contra} candidates={candidates} verifications={verifications} evidence={evidence} />);
  const panel = screen.getByRole("region", { name: "Evidence relationships" });
  await user.click(within(panel).getByRole("button", { name: /^Hypothesis hy_1/ }));
  const rec = within(panel).getByRole("complementary", { name: "Selected record" });
  const link = within(rec).getByRole("button", { name: new RegExp(`^Open evidence ${E2}; link: .*evidence contradicts the hypothesis, recorded · contradicting`) });
  expect(link).toBeDefined();
});

test("cards show a short ID and copy the full one", async () => {
  const user = userEvent.setup();
  const writeText = vi.fn(() => Promise.resolve());
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  const panel = renderExplorer();
  await user.click(within(panel).getByRole("button", { name: `Copy ID ${E3}` }));
  expect(writeText).toHaveBeenCalledWith(E3);
  expect(within(panel).getByText(`Copied ${E3}`)).toBeDefined();
});

test("stacked cards wrap long descriptions behind Show more, apart from selecting the record", async () => {
  const user = userEvent.setup();
  // A zero-width panel: the stacked layout used on phones and narrow panes.
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(private cb: () => void) {}
      observe() {
        this.cb();
      }
      disconnect() {}
    },
  );
  const long = "A long evidence summary that explains the sequential scan on orders, its estimated rows, its cost and the filter it applied.";
  const ev = new Map(evidence);
  ev.set(E1, { ...(evidence.get(E1) as EvidenceDetail), evidence: { ...(evidence.get(E1) as EvidenceDetail).evidence, summary: long } });
  render(<EvidenceExplorer findings={findings} hypotheses={hypotheses} candidates={candidates} verifications={verifications} evidence={ev} />);
  const panel = screen.getByRole("region", { name: "Evidence relationships" });
  const more = within(panel).getByRole("button", { name: "Show more" });
  expect(more.getAttribute("aria-expanded")).toBe("false");
  await user.click(more);
  expect(within(panel).getByRole("button", { name: "Show less" }).getAttribute("aria-expanded")).toBe("true");
  // Expanding did not select the record; the verdict is still selected.
  expect(within(panel).getByRole("button", { name: /^Verdict oc_1/ }).getAttribute("aria-pressed")).toBe("true");
  // The full ID is shown in the stacked layout.
  expect(within(panel).getAllByText(E1).length).toBeGreaterThan(0);
  vi.unstubAllGlobals();
});
