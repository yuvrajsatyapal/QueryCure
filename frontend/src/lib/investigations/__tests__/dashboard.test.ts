import { expect, test } from "vitest";
import type { InvestigationSummary } from "@/lib/api/types";
import { activeFirst, medianRunMs, outcomeBreakdown } from "../dashboard";

function inv(id: string, status: string | null, extra: Partial<NonNullable<InvestigationSummary["latestRun"]>> = {}, createdAt = "2026-10-20T10:00:00Z"): InvestigationSummary {
  return {
    id,
    title: id,
    objective: "o",
    modes: ["offline"],
    createdAt,
    latestRun: status
      ? {
          id: `run-${id}`,
          investigationId: id,
          kind: "investigation",
          runNumber: 1,
          status,
          outcome: null,
          finalized: false,
          createdAt,
          startedAt: null,
          finishedAt: null,
          ...extra,
        }
      : null,
  };
}

test("active investigations: only in-flight runs, approvals first, then running, cancelling, queued", () => {
  const items = [
    inv("q", "queued"),
    inv("done", "completed"),
    inv("r-old", "running", {}, "2026-10-20T09:00:00Z"),
    inv("a", "awaiting_approval"),
    inv("r-new", "running", {}, "2026-10-20T11:00:00Z"),
    inv("c", "cancelling"),
    inv("none", null),
  ];
  expect(activeFirst(items).map((i) => i.id)).toEqual(["a", "r-new", "r-old", "c", "q"]);
});

test("outcome breakdown counts each investigation's latest run once and skips runs still in flight", () => {
  const items = [
    inv("v1", "completed", { outcome: "verified_recommendation" }),
    inv("v2", "completed", { outcome: "verified_recommendation" }),
    inv("u", "completed", { outcome: "unverified_recommendations" }),
    inv("n", "completed", { outcome: "no_action_needed" }),
    inv("i", "completed", { outcome: "inconclusive" }),
    inv("f", "failed"),
    inv("x", "cancelled"),
    inv("live", "running"),
    inv("none", null),
  ];
  const b = outcomeBreakdown(items);
  expect(b.total).toBe(7);
  expect(Object.fromEntries(b.parts.map((p) => [p.key, p.count]))).toEqual({
    verified_recommendation: 2,
    unverified_recommendations: 1,
    no_action_needed: 1,
    inconclusive: 1,
    failed: 1,
    cancelled: 1,
  });
});

test("a completed run with an unknown outcome is counted as completed, not dropped", () => {
  const b = outcomeBreakdown([inv("w", "completed", { outcome: "something_new" }), inv("z", "completed")]);
  expect(b.total).toBe(2);
  expect(b.parts.find((p) => p.key === "completed")?.count).toBe(2);
});

test("median run time uses completed runs with both timestamps", () => {
  const t = (s: string) => `2026-10-20T10:${s}Z`;
  const items = [
    inv("a", "completed", { startedAt: t("00:00"), finishedAt: t("01:00") }), // 60 s
    inv("b", "completed", { startedAt: t("00:00"), finishedAt: t("03:00") }), // 180 s
    inv("c", "completed", { startedAt: t("00:00"), finishedAt: t("02:00") }), // 120 s
    inv("d", "failed", { startedAt: t("00:00"), finishedAt: t("09:00") }),
    inv("e", "completed", { startedAt: null, finishedAt: t("02:00") }),
  ];
  expect(medianRunMs(items)).toEqual({ ms: 120_000, n: 3 });
  expect(medianRunMs([inv("x", "running")])).toBeNull();
  expect(medianRunMs([inv("a", "completed", { startedAt: t("00:00"), finishedAt: t("01:00") }), inv("b", "completed", { startedAt: t("00:00"), finishedAt: t("02:00") })])).toEqual({ ms: 90_000, n: 2 });
});
