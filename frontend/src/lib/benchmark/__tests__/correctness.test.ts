import { describe, expect, test } from "vitest";
import type { ExperimentDetail } from "@/lib/api/types";
import { correctnessView } from "../correctness";
// Real bench@2 result (see analysis.test.ts): both arms returned identical fingerprints, gate null.
import recorded from "./recorded-result.json";

type Result = NonNullable<ExperimentDetail["result"]>;
const result = recorded as unknown as Result;
const ARM = "oc_70a238eea02a";

function withVerdict(gate: number | null, verdict: string, code?: string, detail = "") {
  return { ...result, verdicts: [{ arm: ARM, verdict, gate, reasons: code ? [{ code, detail }] : [] }] } as Result;
}

function withCandidatePrint(ps: string, patch: Record<string, unknown> | null, extra: Record<string, unknown> = {}) {
  return {
    ...result,
    measurements: result.measurements.map((m) =>
      m.arm === ARM && m.paramSet === ps ? { ...m, ...extra, fingerprint: patch === null ? null : { ...m.fingerprint!, ...patch } } : m,
    ),
  } as Result;
}

describe("correctnessView", () => {
  test("recorded result: passed, rows and both hashes match per param set", () => {
    const v = correctnessView(result, ARM);
    expect(v.outcome.status).toBe("passed");
    expect(v.orderRule).toMatch(/multiset/i);
    expect(v.rows.map((r) => r.paramSet)).toEqual(["hot_customer", "regular_customer"]);
    const hot = v.rows[0]!;
    expect(hot).toMatchObject({ baselineRows: 20, candidateRows: 20, sameRows: true, sameOrder: true, baselineConsistent: true, candidateConsistent: true, truncated: false });
    expect(hot.baselineMultiset).toHaveLength(64);
  });

  test("gate 3 rejection carries the recorded reason and detail", () => {
    const v = correctnessView(withVerdict(3, "rejected", "result_mismatch", "hot_customer: row count 20 vs 19"), ARM);
    expect(v.outcome).toMatchObject({ status: "failed", code: "result_mismatch", detail: "hot_customer: row count 20 vs 19" });
  });

  test("gate 3 inconclusive (ties under LIMIT) is not called a failure", () => {
    const v = correctnessView(withVerdict(3, "inconclusive", "nondeterministic_order", "hot_customer: ORDER BY with ties under LIMIT"), ARM);
    expect(v.outcome.status).toBe("inconclusive");
  });

  test("gates 1-2 stop before correctness; a later gate means it passed", () => {
    expect(correctnessView(withVerdict(1, "rejected", "ddl_failed"), ARM).outcome.status).toBe("not_reached");
    expect(correctnessView(withVerdict(2, "inconclusive", "unstable_execution"), ARM).outcome.status).toBe("not_reached");
    expect(correctnessView(withVerdict(5, "rejected", "regression"), ARM).outcome.status).toBe("passed");
    expect(correctnessView({ ...result, verdicts: [] } as Result, ARM).outcome.status).toBe("not_evaluated");
  });

  test("different multiset hash means different rows, even with the same row count", () => {
    const row = correctnessView(withCandidatePrint("hot_customer", { multiset: "f".repeat(64), ordered: "e".repeat(64) }), ARM).rows[0]!;
    expect(row.sameRows).toBe(false);
    expect(row.sameOrder).toBe(false);
  });

  test("a missing fingerprint is unknown, never a match", () => {
    const row = correctnessView(withCandidatePrint("hot_customer", null, { consistent: true }), ARM).rows[0]!;
    expect(row.sameRows).toBeNull();
    expect(row.sameOrder).toBeNull();
    expect(row.candidateRows).toBeNull();
  });

  test("truncation and inconsistency are surfaced", () => {
    const row = correctnessView(withCandidatePrint("regular_customer", { truncated: true }, { consistent: false }), ARM).rows[1]!;
    expect(row.truncated).toBe(true);
    expect(row.candidateConsistent).toBe(false);
  });

  test("a total ORDER BY means row order must match", () => {
    expect(correctnessView({ ...result, orderIsTotal: true } as Result, ARM).orderRule).toMatch(/order must match/i);
  });
});
