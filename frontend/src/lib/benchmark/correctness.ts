import { BASELINE, paramSetsOf, type ExperimentResult } from "./analysis";

// Result-correctness display (FINAL_UI_POLISH §2.4, UI_UX §3.8). Reads recorded fingerprints
// and the rule verdict only. "Same rows" uses the backend's definition (equal row count and
// multiset hash, as in correctness_check evidence); nothing here decides a verdict.

export type CorrectnessStatus = "passed" | "failed" | "inconclusive" | "not_reached" | "not_evaluated";

export interface CorrectnessOutcome {
  status: CorrectnessStatus;
  code: string | null;
  detail: string | null;
}

export interface CorrectnessRow {
  paramSet: string;
  baselineRows: number | null;
  candidateRows: number | null;
  /** null when either arm has no fingerprint (no successful execution). */
  sameRows: boolean | null;
  sameOrder: boolean | null;
  baselineMultiset: string | null;
  candidateMultiset: string | null;
  baselineConsistent: boolean | null;
  candidateConsistent: boolean | null;
  truncated: boolean;
}

export interface CorrectnessView {
  outcome: CorrectnessOutcome;
  orderRule: string;
  rows: CorrectnessRow[];
}

// Gate 3 of benchmark/rules.py is the correctness gate; gates 1-2 stop before it.
const CORRECTNESS_GATE = 3;

function outcomeOf(result: ExperimentResult, arm: string): CorrectnessOutcome {
  const v = result.verdicts.find((x) => x.arm === arm);
  if (!v) return { status: "not_evaluated", code: null, detail: null };
  const reason = v.reasons[0] ?? null;
  const base = { code: reason?.code ?? null, detail: reason?.detail || null };
  if (v.gate === null || v.gate > CORRECTNESS_GATE) return { status: "passed", code: null, detail: null };
  if (v.gate < CORRECTNESS_GATE) return { status: "not_reached", ...base };
  return { status: v.verdict === "rejected" ? "failed" : "inconclusive", ...base };
}

export function correctnessView(result: ExperimentResult, arm: string): CorrectnessView {
  const rows = paramSetsOf(result, null).map((ps): CorrectnessRow => {
    const b = result.measurements.find((m) => m.arm === BASELINE && m.paramSet === ps);
    const c = result.measurements.find((m) => m.arm === arm && m.paramSet === ps);
    const bf = b?.fingerprint ?? null;
    const cf = c?.fingerprint ?? null;
    const both = bf !== null && cf !== null;
    return {
      paramSet: ps,
      baselineRows: bf?.rows ?? null,
      candidateRows: cf?.rows ?? null,
      sameRows: both ? bf.rows === cf.rows && bf.multiset === cf.multiset : null,
      sameOrder: both ? bf.ordered === cf.ordered : null,
      baselineMultiset: bf?.multiset ?? null,
      candidateMultiset: cf?.multiset ?? null,
      baselineConsistent: b ? b.consistent : null,
      candidateConsistent: c ? c.consistent : null,
      truncated: Boolean(bf?.truncated || cf?.truncated),
    };
  });
  return {
    outcome: outcomeOf(result, arm),
    orderRule: result.orderIsTotal
      ? "The ORDER BY fixes a unique row order, so row order must match as well as the rows."
      : "Rows are compared as a multiset: the query has no ORDER BY that fixes a unique order, so row order is not required to match.",
    rows,
  };
}
