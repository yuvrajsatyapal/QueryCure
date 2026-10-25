import { afterEach, expect, test, vi } from "vitest";
import { act, cleanup, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { renderWithQuery } from "@/test/render";
import { ApiError } from "@/lib/api/client";
import type { Approval, Hypothesis, OptimizationCandidate } from "@/lib/api/types";
import { ApprovalReview } from "../ApprovalReview";
import { useApprovalDecision } from "../useApprovalDecision";

const decideApproval = vi.fn();
vi.mock("@/lib/api/optimization", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  decideApproval: (...args: unknown[]) => decideApproval(...args),
}));

afterEach(() => {
  cleanup();
  decideApproval.mockReset();
});

const LONG_SQL = `SELECT o.id, o.customer_id, o.created_at, o.total_amount\n  FROM orders o\n WHERE o.customer_id = $1\n   AND EXISTS (SELECT 1 FROM order_items oi WHERE oi.order_id = o.id AND oi.sku_identifier_that_is_quite_long_indeed = 'abcdefghijklmnopqrstuvwxyz0123456789')\n ORDER BY o.created_at DESC\n LIMIT 50`;
const approval = {
  id: "ap-1",
  runId: "run-1",
  round: 0,
  kind: "sandbox_execution",
  status: "pending",
  decidedBy: null,
  decidedAt: null,
  expiresAt: "2099-01-01T00:00:00Z",
  approvedCandidateIds: [],
  comment: "",
  createdAt: "2026-10-25T09:00:00Z",
  payload: {
    schemaVersion: 1,
    workloadId: "orders_ecommerce@v1:sf=0.1:seed=42",
    sandbox: "QueryCure sandbox",
    baselineQuery: "SELECT * FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 50",
    paramSets: [{ name: "hot", values: [1024] }],
    candidates: [
      { candidateId: "c-1", key: "oc_000000000001", kind: "create_index", ddl: ["CREATE INDEX ON orders (customer_id, created_at)"], querySql: null, sqlSha256: "1".repeat(64), expectedBenefit: "Avoids the sort", risks: ["Slower inserts"] },
      { candidateId: "c-2", key: "oc_000000000002", kind: "query_rewrite", ddl: [], querySql: LONG_SQL, sqlSha256: "2".repeat(64), expectedBenefit: "Semi-join", risks: [] },
    ],
  },
} as unknown as Approval;

const record = (id: string, key: string, sha: string, over: Record<string, unknown> = {}) =>
  ({
    id,
    key,
    sqlSha256: sha,
    addressesHypotheses: ["hy_000000000001"],
    estimatedCost: { writeOverhead: "medium", indexSizeEstimateBytes: null },
    rollbackSql: null,
    status: "proposed",
    ...over,
  }) as unknown as OptimizationCandidate;
const records = [record("c-1", "oc_000000000001", "1".repeat(64)), record("c-2", "oc_000000000002", "2".repeat(64))];
const hypotheses = [
  { key: "hy_000000000001", statement: "A sort dominates the plan", rank: 1, confidence: "high", supportingEvidence: ["ev_abcdef123456"], contradictingEvidence: [] },
] as unknown as Hypothesis[];

function Harness({ value = approval, recs = records, onEvidence = () => undefined }: { value?: Approval; recs?: OptimizationCandidate[]; onEvidence?: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <ApprovalReview
      approval={value}
      runId="run-1"
      showCard={value.status === "pending"}
      open={open}
      onOpen={() => setOpen(true)}
      onClose={() => setOpen(false)}
      investigationTitle="Nightly revenue rollup"
      candidates={recs}
      hypotheses={hypotheses}
      onEvidence={onEvidence}
    />
  );
}

async function openDrawer(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Review details" }));
  return screen.getByRole("dialog", { name: "Benchmark 2 changes in a sandbox?" });
}

test("the drawer opens from the card with focus on its title, and Escape returns focus to the opener", async () => {
  const user = userEvent.setup();
  renderWithQuery(<Harness />);
  const opener = screen.getByRole("button", { name: "Review details" });
  const dialog = await openDrawer(user);
  expect(dialog.getAttribute("aria-modal")).toBe("true");
  expect(document.activeElement).toBe(within(dialog).getByRole("heading", { level: 2 }));
  expect(document.getElementById(dialog.getAttribute("aria-describedby") ?? "")?.textContent).toBe("Round 1 · Nightly revenue rollup · runs only in QueryCure sandbox");
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(document.activeElement).toBe(opener);
});

test("Tab stays inside the drawer", async () => {
  const user = userEvent.setup();
  renderWithQuery(<Harness />);
  const dialog = await openDrawer(user);
  for (let i = 0; i < 40; i += 1) {
    await user.tab();
    expect(dialog.contains(document.activeElement)).toBe(true);
  }
});

test("each candidate shows its exact SQL, full digest, and context, with expectations apart from measurements", async () => {
  const user = userEvent.setup();
  renderWithQuery(<Harness />);
  const dialog = await openDrawer(user);
  const rewrite = within(dialog).getByRole("article", { name: /oc_000000000002/ });
  // Verbatim, line breaks included: nothing is reformatted client-side.
  expect(within(rewrite).getByRole("region", { name: "rewritten query · oc_000000000002" }).textContent).toBe(LONG_SQL);
  expect(within(rewrite).getByText("2".repeat(64))).toBeTruthy();
  expect(within(rewrite).getByText("None listed. That is not a safety check.")).toBeTruthy();
  const index = within(dialog).getByRole("article", { name: /oc_000000000001/ });
  expect(within(index).getByRole("region", { name: "statement · oc_000000000001" }).textContent).toBe("CREATE INDEX ON orders (customer_id, created_at)");
  expect(within(index).getByText("Slower inserts")).toBeTruthy();
  expect(within(index).getByText("proposed, not measured", { exact: false })).toBeTruthy();
  expect(within(index).getByText(/Nothing measured yet/)).toBeTruthy();
  // No size was recorded, so none is shown.
  expect(within(index).queryByText("Index size")).toBeNull();
  expect(within(index).getByText("A sort dominates the plan")).toBeTruthy();
});

test("an evidence link closes through the given handler", async () => {
  const user = userEvent.setup();
  const onEvidence = vi.fn();
  renderWithQuery(<Harness onEvidence={onEvidence} />);
  const dialog = await openDrawer(user);
  await user.click(within(within(dialog).getByRole("article", { name: /oc_000000000001/ })).getByRole("button", { name: "Evidence ev_abcdef123456" }));
  expect(onEvidence).toHaveBeenCalledWith("ev_abcdef123456");
});

test("selection is shared with the card; partial approval sends the chosen ids and shows the recorded result", async () => {
  const user = userEvent.setup();
  decideApproval.mockResolvedValue({ ...approval, status: "partially_approved", approvedCandidateIds: ["c-2"], decidedAt: "2026-10-25T09:30:00Z" });
  renderWithQuery(<Harness />);
  await user.click(screen.getByRole("checkbox", { name: /Include oc_000000000001/ }));
  const dialog = await openDrawer(user);
  expect(within(dialog).getByText("1 of 2 selected")).toBeTruthy();
  expect((within(dialog).getByRole("checkbox", { name: /oc_000000000001/ }) as HTMLInputElement).checked).toBe(false);
  await user.click(within(dialog).getByRole("button", { name: "Approve selected" }));
  expect(decideApproval).toHaveBeenCalledWith("ap-1", { decision: "partial", candidateIds: ["c-2"] });
  await screen.findByRole("heading", { name: "Decision recorded" });
  expect(screen.getByText(/Partially approved: 1 of 2 candidates will be benchmarked/)).toBeTruthy();
  expect(screen.getAllByText("not approved")).toHaveLength(1);
});

test("Select none disables approval; Decline all sends decline", async () => {
  const user = userEvent.setup();
  decideApproval.mockResolvedValue({ ...approval, status: "declined", approvedCandidateIds: [] });
  renderWithQuery(<Harness />);
  const dialog = await openDrawer(user);
  await user.click(within(dialog).getByRole("button", { name: "Select none" }));
  expect((within(dialog).getByRole("button", { name: "Approve selected" }) as HTMLButtonElement).disabled).toBe(true);
  await user.click(within(dialog).getByRole("button", { name: "Decline all" }));
  expect(decideApproval).toHaveBeenCalledWith("ap-1", { decision: "decline", candidateIds: [] });
  expect(await screen.findByText(/Declined: nothing will run/)).toBeTruthy();
});

test("a request someone else decided first is reported as already decided", async () => {
  const user = userEvent.setup();
  decideApproval.mockResolvedValue({ ...approval, status: "declined", approvedCandidateIds: [] });
  renderWithQuery(<Harness />);
  const dialog = await openDrawer(user);
  await user.click(within(dialog).getByRole("button", { name: "Approve selected" }));
  expect(await screen.findByRole("heading", { name: "Already decided" })).toBeTruthy();
  expect(screen.getByText(/already decided, so no new decision was recorded/)).toBeTruthy();
});

test("while recording, both actions are disabled and say so", async () => {
  const user = userEvent.setup();
  decideApproval.mockReturnValue(new Promise(() => undefined));
  renderWithQuery(<Harness />);
  const dialog = await openDrawer(user);
  await user.click(within(dialog).getByRole("button", { name: "Approve selected" }));
  const busy = within(dialog).getByRole("button", { name: "Recording decision…" }) as HTMLButtonElement;
  expect(busy.disabled).toBe(true);
  expect((within(dialog).getByRole("button", { name: "Decline all" }) as HTMLButtonElement).disabled).toBe(true);
});

test("a server refusal (409 expired) closes the request at once, keeping the server's message and the expiry time", async () => {
  const user = userEvent.setup();
  decideApproval.mockRejectedValueOnce(new ApiError("INVALID_STATE", "This approval request has expired.", 409, [], "req-1"));
  // The list still says pending (the refetch has not landed): the refusal alone must close it.
  renderWithQuery(<Harness />);
  const dialog = await openDrawer(user);
  await user.click(within(dialog).getByRole("button", { name: "Approve selected" }));
  await within(dialog).findByRole("heading", { name: "Decision not recorded" });
  expect(within(dialog).getAllByRole("alert").map((a) => a.textContent).join(" ")).toMatch(/This approval request has expired\..*request req-1/);
  expect(within(dialog).getByText(/No decision was recorded and nothing ran in the sandbox/).textContent).toContain(new Date(approval.expiresAt).toLocaleString());
  expect(within(dialog).queryByRole("button", { name: "Approve selected" })).toBeNull();
  expect(within(dialog).queryByRole("button", { name: "Decline all" })).toBeNull();
  expect(within(dialog).queryByRole("checkbox")).toBeNull();
  expect(within(dialog).getByText("Not recorded")).toBeTruthy();
  // The inline card behind the drawer stops offering a decision too.
  const card = screen.getByRole("region", { name: "Approval required", hidden: true });
  expect((within(card).getByRole("button", { name: "Approve and run", hidden: true }) as HTMLButtonElement).disabled).toBe(true);
  await user.click(within(dialog).getByRole("button", { name: "Close" }));
  expect(decideApproval).toHaveBeenCalledTimes(1);
});

test("once the server's status arrives, an expired request shows as expired with the server's message kept", async () => {
  const user = userEvent.setup();
  decideApproval.mockRejectedValueOnce(new ApiError("INVALID_STATE", "This approval request has expired.", 409, [], "req-1"));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const view = render(<Harness />, { wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> });
  const dialog = await openDrawer(user);
  await user.click(within(dialog).getByRole("button", { name: "Approve selected" }));
  await within(dialog).findByRole("heading", { name: "Decision not recorded" });
  view.rerender(<Harness value={{ ...approval, status: "expired" } as Approval} />);
  expect(within(dialog).getByRole("heading", { name: "Approval request expired" })).toBeTruthy();
  expect(within(dialog).getByRole("alert").textContent).toMatch(/This approval request has expired\./);
  expect(within(dialog).getByRole("button", { name: "Close" })).toBeTruthy();
});

test("a failure that is not a refusal is shown and can be retried", async () => {
  const user = userEvent.setup();
  decideApproval.mockRejectedValueOnce(new ApiError("INTERNAL", "The service is unavailable.", 503, [], "req-2"));
  renderWithQuery(<Harness />);
  const dialog = await openDrawer(user);
  await user.click(within(dialog).getByRole("button", { name: "Approve selected" }));
  expect((await within(dialog).findByRole("alert")).textContent).toMatch(/The service is unavailable\./);
  // Never shown as a decision.
  expect(within(dialog).queryByRole("heading", { name: /Decision recorded|Already decided/ })).toBeNull();
  expect((within(dialog).getByRole("button", { name: "Approve selected" }) as HTMLButtonElement).disabled).toBe(false);
});

test("a pending request turns expired at its deadline without waiting for the next clock tick", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  try {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const soon = { ...approval, expiresAt: new Date(Date.now() + 3_000).toISOString() } as Approval;
    renderWithQuery(<Harness value={soon} />);
    await user.click(screen.getByRole("button", { name: "Review details" }));
    expect(screen.getByRole("dialog", { name: "Benchmark 2 changes in a sandbox?" })).toBeTruthy();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_500);
    });
    const dialog = screen.getByRole("dialog", { name: "Approval request expired" });
    expect(within(dialog).queryByRole("button", { name: "Approve selected" })).toBeNull();
    expect(within(dialog).getByRole("button", { name: "Close" })).toBeTruthy();
  } finally {
    vi.useRealTimers();
  }
});

test("a decision is sent once: repeated calls, the card and the drawer, and calls after the outcome are ignored", async () => {
  let resolve: (a: Approval) => void = () => undefined;
  decideApproval.mockReturnValue(new Promise<Approval>((r) => (resolve = r)));
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const { result } = renderHook(() => useApprovalDecision(approval, "run-1"), {
    wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
  });
  act(() => {
    // Same tick, before any re-render could disable a button (double click, Enter + click).
    result.current.submit({ decision: "approve", candidateIds: [] });
    result.current.submit({ decision: "approve", candidateIds: [] });
    result.current.submit({ decision: "decline", candidateIds: [] });
  });
  await waitFor(() => expect(decideApproval).toHaveBeenCalledTimes(1));
  expect(decideApproval).toHaveBeenCalledWith("ap-1", { decision: "approve", candidateIds: [] });
  await act(async () => resolve({ ...approval, status: "approved", approvedCandidateIds: ["c-1", "c-2"] } as Approval));
  await waitFor(() => expect(result.current.phase).toEqual({ kind: "decided", outcome: "recorded" }));
  act(() => result.current.submit({ decision: "decline", candidateIds: [] }));
  await act(async () => undefined);
  expect(decideApproval).toHaveBeenCalledTimes(1);
});

test("Enter on the focused approve button sends one request with the exact selected ids", async () => {
  const user = userEvent.setup();
  decideApproval.mockReturnValue(new Promise(() => undefined));
  renderWithQuery(<Harness />);
  const dialog = await openDrawer(user);
  await user.click(within(dialog).getByRole("checkbox", { name: /oc_000000000002/ }));
  within(dialog).getByRole("button", { name: "Approve selected" }).focus();
  await user.keyboard("{Enter}{Enter}");
  expect(decideApproval).toHaveBeenCalledTimes(1);
  expect(decideApproval).toHaveBeenCalledWith("ap-1", { decision: "partial", candidateIds: ["c-1"] });
});

test("an expired request offers no decision", async () => {
  const user = userEvent.setup();
  const expired = { ...approval, expiresAt: "2020-01-01T00:00:00Z" } as Approval;
  renderWithQuery(<Harness value={expired} />);
  await user.click(screen.getByRole("button", { name: "Review details" }));
  const dialog = screen.getByRole("dialog", { name: "Approval request expired" });
  expect(within(dialog).getByText(/can no longer be decided\. Nothing ran in the sandbox/)).toBeTruthy();
  expect(within(dialog).queryByRole("button", { name: "Approve selected" })).toBeNull();
  expect(within(dialog).queryByRole("checkbox")).toBeNull();
});

test("a candidate record whose digest differs from the approval is flagged", async () => {
  const user = userEvent.setup();
  renderWithQuery(<Harness recs={[record("c-1", "oc_000000000001", "f".repeat(64)), records[1] as OptimizationCandidate]} />);
  const dialog = await openDrawer(user);
  const index = within(dialog).getByRole("article", { name: /oc_000000000001/ });
  expect(within(index).getByRole("alert").textContent).toMatch(/different digest \(ffffffffffff…\)/);
  // The approval's own digest is still the one displayed.
  expect(within(index).getByText("1".repeat(64))).toBeTruthy();
});

test("copy writes the exact digest to the clipboard", async () => {
  const user = userEvent.setup();
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  renderWithQuery(<Harness />);
  const dialog = await openDrawer(user);
  await user.click(within(dialog).getByRole("button", { name: "Copy SQL SHA-256 · oc_000000000002" }));
  expect(writeText).toHaveBeenCalledWith("2".repeat(64));
  await waitFor(() => expect(within(dialog).getByText("Copied")).toBeTruthy());
});

test("a failed copy says so and points to selecting the text", async () => {
  const user = userEvent.setup();
  Object.defineProperty(navigator, "clipboard", { value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) }, configurable: true });
  renderWithQuery(<Harness />);
  const dialog = await openDrawer(user);
  await user.click(within(dialog).getByRole("button", { name: "Copy statement · oc_000000000001" }));
  await waitFor(() => expect(within(dialog).getByText("Copy failed: select the text instead")).toBeTruthy());
});

test("long SQL scrolls inside a focusable region; digests and keys wrap instead of widening the drawer", async () => {
  const user = userEvent.setup();
  renderWithQuery(<Harness />);
  const dialog = await openDrawer(user);
  const sql = within(dialog).getByRole("region", { name: "rewritten query · oc_000000000002" });
  expect(sql.tabIndex).toBe(0);
  expect(sql.className).toMatch(/max-h-72/);
  expect(sql.className).toMatch(/overflow-auto/);
  expect(within(dialog).getByText("2".repeat(64)).className).toMatch(/break-all/);
});

test("a candidate record without linked hypotheses says so instead of an empty list", async () => {
  const user = userEvent.setup();
  renderWithQuery(<Harness recs={[record("c-1", "oc_000000000001", "1".repeat(64), { addressesHypotheses: [] }), records[1] as OptimizationCandidate]} />);
  const dialog = await openDrawer(user);
  const index = within(dialog).getByRole("article", { name: /oc_000000000001/ });
  expect(within(index).getByText("No hypothesis is linked to this candidate.")).toBeTruthy();
});
