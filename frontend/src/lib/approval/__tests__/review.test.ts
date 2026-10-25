import { expect, test } from "vitest";
import type { Approval, DecisionInput, Hypothesis, OptimizationCandidate } from "@/lib/api/types";
import { ApiError } from "@/lib/api/client";
import { candidateContext, decisionFor, decisionOutcome, expiryText, formatBytes, isRefusal, reviewPhase, statements } from "../review";

const NOW = Date.parse("2026-10-25T10:00:00Z");
const offered = ["c-1", "c-2"];
const cand = (candidateId: string, over: Record<string, unknown> = {}) => ({
  candidateId,
  key: `oc_${candidateId.replace("c-", "").padStart(12, "0")}`,
  kind: "create_index",
  ddl: ["CREATE INDEX ON orders (customer_id)"],
  querySql: null,
  sqlSha256: "a".repeat(64),
  expectedBenefit: "Fewer rows read.",
  risks: [],
  ...over,
});
const approval = (over: Partial<Approval> = {}) =>
  ({
    id: "ap-1",
    runId: "run-1",
    round: 0,
    kind: "sandbox_experiment",
    status: "pending",
    payload: { workloadId: "orders_ecommerce", sandbox: "sandbox clone", baselineQuery: "SELECT 1", paramSets: [{}], candidates: [cand("c-1"), cand("c-2")] },
    decidedBy: null,
    decidedAt: null,
    expiresAt: "2026-10-25T10:51:00Z",
    approvedCandidateIds: [],
    comment: "",
    createdAt: "2026-10-24T10:51:00Z",
    ...over,
  }) as unknown as Approval;

test("decisionFor keeps the inline card's semantics: all, a subset, or nothing", () => {
  expect(decisionFor(new Set(offered), offered)).toEqual({ decision: "approve", candidateIds: [] });
  expect(decisionFor(new Set(["c-2"]), offered)).toEqual({ decision: "partial", candidateIds: ["c-2"] });
  expect(decisionFor(new Set(), offered)).toBeNull();
  // An id that is not offered never reaches the request.
  expect(decisionFor(new Set(["c-9", "c-1"]), offered)).toEqual({ decision: "partial", candidateIds: ["c-1"] });
});

test("decisionOutcome tells our own recorded decision from one that was already made", () => {
  const partial: DecisionInput = { decision: "partial", candidateIds: ["c-1"] };
  expect(decisionOutcome(partial, approval({ status: "partially_approved", approvedCandidateIds: ["c-1"] }), offered)).toBe("recorded");
  // The server returns the first decision when the request was already decided.
  expect(decisionOutcome(partial, approval({ status: "declined", approvedCandidateIds: [] }), offered)).toBe("already_decided");
  expect(decisionOutcome({ decision: "approve", candidateIds: [] }, approval({ status: "approved", approvedCandidateIds: ["c-2", "c-1"] }), offered)).toBe("recorded");
  expect(decisionOutcome({ decision: "decline", candidateIds: [] }, approval({ status: "declined", approvedCandidateIds: [] }), offered)).toBe("recorded");
});

test("reviewPhase: pending, deadline passed, expired, decided by us or elsewhere", () => {
  expect(reviewPhase(approval(), NOW, null)).toEqual({ kind: "pending" });
  expect(reviewPhase(approval({ expiresAt: "2026-10-25T09:59:59Z" }), NOW, null)).toEqual({ kind: "expired", byClock: true });
  expect(reviewPhase(approval({ status: "expired" }), NOW, null)).toEqual({ kind: "expired", byClock: false });
  expect(reviewPhase(approval({ status: "approved" }), NOW, null)).toEqual({ kind: "decided", outcome: "already_decided" });
  const mine = approval({ status: "approved" });
  expect(reviewPhase(approval(), NOW, { approval: mine, outcome: "recorded" })).toEqual({ kind: "decided", outcome: "recorded" });
});

test("reviewPhase: a server refusal closes a request the list still shows as pending, until the server's own status arrives", () => {
  const refused = "This approval request has expired.";
  // The list has not caught up yet: the refusal alone is enough to stop offering a decision.
  expect(reviewPhase(approval(), NOW, null, refused)).toEqual({ kind: "refused", message: refused });
  // Once refetched, the server's status is what is shown.
  expect(reviewPhase(approval({ status: "expired" }), NOW, null, refused)).toEqual({ kind: "expired", byClock: false });
  expect(reviewPhase(approval({ status: "declined" }), NOW, null, refused)).toEqual({ kind: "decided", outcome: "already_decided" });
  // A refusal never reads as a recorded decision, and the deadline still applies.
  expect(reviewPhase(approval({ expiresAt: "2026-10-25T09:00:00Z" }), NOW, null, refused)).toEqual({ kind: "refused", message: refused });
});

test("isRefusal: only a 409 means the request can no longer be decided; other failures can be retried", () => {
  expect(isRefusal(new ApiError("INVALID_STATE", "This approval request has expired.", 409, [], null))).toBe(true);
  expect(isRefusal(new ApiError("INTERNAL", "Something broke.", 500, [], null))).toBe(false);
  expect(isRefusal(new ApiError("VALIDATION_FAILED", "A partial approval names some of the offered candidates.", 422, [], null))).toBe(false);
  expect(isRefusal(new TypeError("Failed to fetch"))).toBe(false);
});

test("expiryText counts down and never shows a negative time", () => {
  expect(expiryText("2026-10-25T10:51:00Z", NOW)).toBe("expires in 51m");
  expect(expiryText("2026-10-25T13:05:00Z", NOW)).toBe("expires in 3h 05m");
  expect(expiryText("2026-10-25T10:00:30Z", NOW)).toBe("expires in under 1m");
  expect(expiryText("2026-10-25T09:00:00Z", NOW)).toBe("expiry time passed");
});

test("statements are the payload's own text, unchanged and in order", () => {
  const ddl = ["CREATE INDEX ON orders (status)", "ANALYZE orders"];
  expect(statements(cand("c-1", { ddl }) as never)).toEqual([
    { label: "Statement 1 of 2", sql: ddl[0] },
    { label: "Statement 2 of 2", sql: ddl[1] },
  ]);
  const rewrite = "SELECT o.id\n  FROM orders o\n WHERE EXISTS (SELECT 1)";
  expect(statements(cand("c-1", { kind: "query_rewrite", ddl: [], querySql: rewrite }) as never)).toEqual([{ label: "Rewritten query", sql: rewrite }]);
});

const hyp = (key: string) => ({ key, statement: `Statement ${key}`, rank: 1, confidence: "medium", supportingEvidence: ["ev_1"], contradictingEvidence: [] }) as unknown as Hypothesis;
const record = (over: Record<string, unknown> = {}) =>
  ({
    id: "c-1",
    key: "oc_000000000001",
    sqlSha256: "a".repeat(64),
    addressesHypotheses: ["hy_000000000001", "hy_00000000000f"],
    estimatedCost: { writeOverhead: "low", indexSizeEstimateBytes: null },
    rollbackSql: "DROP INDEX x",
    status: "proposed",
    ...over,
  }) as unknown as OptimizationCandidate;

test("candidateContext joins the record by id, checks its digest, and never invents a size", () => {
  const ctx = candidateContext(cand("c-1") as never, [record()], [hyp("hy_000000000001")]);
  expect(ctx.digestMatches).toBe(true);
  expect(ctx.indexSizeBytes).toBeNull();
  expect(ctx.writeOverhead).toBe("low");
  expect(ctx.rollbackSql).toBe("DROP INDEX x");
  expect(ctx.hypotheses.map((h) => [h.key, h.hypothesis?.statement ?? null])).toEqual([
    ["hy_000000000001", "Statement hy_000000000001"],
    ["hy_00000000000f", null],
  ]);
  expect(candidateContext(cand("c-1") as never, [record({ estimatedCost: { writeOverhead: "unknown", indexSizeEstimateBytes: 4096 } })], []).indexSizeBytes).toBe(4096);
  expect(candidateContext(cand("c-1") as never, [record({ sqlSha256: "b".repeat(64) })], []).digestMatches).toBe(false);
  const missing = candidateContext(cand("c-1") as never, [], []);
  expect(missing.record).toBeNull();
  expect(missing.digestMatches).toBeNull();
});

test("formatBytes uses binary units", () => {
  expect(formatBytes(512)).toBe("512 B");
  expect(formatBytes(40 * 1024 * 1024)).toBe("40.0 MiB");
});
