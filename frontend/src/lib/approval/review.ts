import { ApiError } from "@/lib/api/client";
import type { Approval, DecisionInput, Hypothesis, OptimizationCandidate } from "@/lib/api/types";

/** One candidate exactly as the approval request offers it (SECURITY §6.6). */
export type ApprovalCandidate = Approval["payload"]["candidates"][number];

export const DECLINE_ALL: DecisionInput = { decision: "decline", candidateIds: [] };

/** The inline card's semantics: every offered candidate is a full approval, a non-empty subset is
 * a partial one, nothing selected is no request at all. Ids that are not offered are dropped. */
export function decisionFor(selected: ReadonlySet<string>, offered: string[]): DecisionInput | null {
  const ids = offered.filter((id) => selected.has(id));
  if (!ids.length) return null;
  return ids.length === offered.length ? { decision: "approve", candidateIds: [] } : { decision: "partial", candidateIds: ids };
}

export type DecisionOutcome = "recorded" | "already_decided";

/** The decision endpoint is idempotent: a request that was already decided returns the first
 * decision unchanged. A response that differs from what we asked for therefore means someone
 * (another tab, another session) decided first. */
export function decisionOutcome(input: DecisionInput, response: Approval, offered: string[]): DecisionOutcome {
  const expected =
    input.decision === "approve" ? offered : input.decision === "decline" ? [] : offered.filter((id) => input.candidateIds.includes(id));
  const status = input.decision === "approve" ? "approved" : input.decision === "decline" ? "declined" : "partially_approved";
  const got = new Set(response.approvedCandidateIds);
  const same = got.size === expected.length && expected.every((id) => got.has(id));
  return response.status === status && same ? "recorded" : "already_decided";
}

export type ReviewPhase =
  | { kind: "pending" }
  /** `byClock`: still pending on the server but past its expiry time; the worker marks it
   * expired on its next sweep, so no decision is offered. */
  | { kind: "expired"; byClock: boolean }
  | { kind: "decided"; outcome: DecisionOutcome }
  /** The server refused our decision (409: expired, or decided concurrently) while the list we
   * hold still says pending. Nothing was recorded; no further decision is offered. */
  | { kind: "refused"; message: string };

/** A 409 from the decision endpoint means the request can no longer be decided (it expired, or
 * another decision won). Anything else (validation, server or network failure) may be retried. */
export function isRefusal(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 409;
}

/** The server's status wins over everything we hold locally; a refusal outranks the client clock
 * because it is the server's answer for this very request. */
export function reviewPhase(
  approval: Approval,
  now: number,
  mine: { approval: Approval; outcome: DecisionOutcome } | null,
  refused: string | null = null,
): ReviewPhase {
  if (mine && mine.approval.id === approval.id) return { kind: "decided", outcome: mine.outcome };
  if (approval.status === "expired") return { kind: "expired", byClock: false };
  if (approval.status !== "pending") return { kind: "decided", outcome: "already_decided" };
  if (refused !== null) return { kind: "refused", message: refused };
  if (Date.parse(approval.expiresAt) <= now) return { kind: "expired", byClock: true };
  return { kind: "pending" };
}

export const STATUS_LABEL: Record<string, string> = {
  pending: "Waiting on you",
  approved: "Approved",
  partially_approved: "Partially approved",
  declined: "Declined",
  expired: "Expired",
};

export function expiryText(expiresAt: string, now: number): string {
  const ms = Date.parse(expiresAt) - now;
  if (ms <= 0) return "expiry time passed";
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 1) return "expires in under 1m";
  if (minutes < 60) return `expires in ${minutes}m`;
  return `expires in ${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
}

/** The SQL a candidate would run, verbatim from the approval payload: each DDL statement, then
 * the rewritten query if there is one. Never joined, trimmed or reformatted. */
export function statements(c: ApprovalCandidate): { label: string; sql: string }[] {
  const ddl = c.ddl.map((sql, i) => ({ label: c.ddl.length > 1 ? `Statement ${i + 1} of ${c.ddl.length}` : "Statement", sql }));
  return c.querySql !== null ? [...ddl, { label: "Rewritten query", sql: c.querySql }] : ddl;
}

export interface CandidateContext {
  /** The run's candidate record with the same id, for what the approval payload does not carry. */
  record: OptimizationCandidate | null;
  /** Whether the record's digest equals the approval's; null without a record. The approval's
   * SQL and digest are what is shown and what runs either way. */
  digestMatches: boolean | null;
  hypotheses: { key: string; hypothesis: Hypothesis | null }[];
  /** Only when recorded; never estimated here. */
  indexSizeBytes: number | null;
  writeOverhead: string | null;
  rollbackSql: string | null;
}

export function candidateContext(c: ApprovalCandidate, records: OptimizationCandidate[], hypotheses: Hypothesis[]): CandidateContext {
  const record = records.find((r) => r.id === c.candidateId) ?? null;
  const byKey = new Map(hypotheses.map((h) => [h.key, h]));
  return {
    record,
    digestMatches: record ? record.sqlSha256 === c.sqlSha256 : null,
    hypotheses: (record?.addressesHypotheses ?? []).map((key) => ({ key, hypothesis: byKey.get(key) ?? null })),
    indexSizeBytes: record?.estimatedCost.indexSizeEstimateBytes ?? null,
    writeOverhead: record?.estimatedCost.writeOverhead ?? null,
    rollbackSql: record?.rollbackSql ?? null,
  };
}

export function formatBytes(bytes: number): string {
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let v = bytes;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return i === 0 ? `${v} B` : `${v.toFixed(1)} ${units[i]}`;
}
