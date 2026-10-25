"use client";

import { useState } from "react";
import { PlanDiffView, type BenchmarkMedians, type DiffLayout } from "@/components/plan/PlanDiffView";
import type { ExperimentDetail, OptimizationCandidate } from "@/lib/api/types";
import { describeCandidate } from "@/lib/benchmark/candidate";

/** Arms with at least one plan captured after timing (the baseline excluded). */
export function armsWithPlans(detail: ExperimentDetail): string[] {
  return [...new Set(detail.blocks.filter((b) => b.phase === "plan" && b.planSha256 && b.arm !== "baseline").map((b) => b.arm))];
}

/** Baseline vs candidate plan for one parameter set, from the post-timing EXPLAIN ANALYZE captures.
 * The candidate picker drives the studio's selection, so the whole studio shows the same arm. */
export function PlanCompare({
  runId,
  detail,
  candidates,
  arm,
  onSelectArm,
  compact,
}: {
  runId: string;
  detail: ExperimentDetail;
  candidates: OptimizationCandidate[];
  arm: string;
  onSelectArm: (arm: string) => void;
  compact: boolean;
}) {
  const plans = detail.blocks.filter((b) => b.phase === "plan" && b.planSha256);
  const arms = armsWithPlans(detail);
  const sets = [...new Set(plans.filter((b) => b.arm === arm).map((b) => b.paramSet))];
  const [ps, setPs] = useState<string | null>(null);
  // A set picked for another candidate falls back to this candidate's first set.
  const chosen = ps !== null && sets.includes(ps) ? ps : (sets[0] ?? null);
  const [layout, setLayout] = useState<DiffLayout | null>(null);
  const from = plans.find((b) => b.arm === "baseline" && b.paramSet === chosen)?.planSha256;
  const to = plans.find((b) => b.arm === arm && b.paramSet === chosen)?.planSha256;
  const byKey = new Map(candidates.map((c) => [c.key, c]));
  const name = (k: string) => {
    const c = byKey.get(k);
    return c ? `${k} · ${describeCandidate(c)}` : k;
  };
  const stat = detail.result?.stats.find((s) => s.arm === arm && s.paramSet === chosen);
  const benchmark: BenchmarkMedians | null = stat
    ? { baselineNs: stat.baseline.medianNs, candidateNs: stat.candidate.medianNs, nBaseline: stat.baseline.n, nCandidate: stat.candidate.n }
    : null;

  return (
    <section aria-label="Plan diff" className="flex min-w-0 flex-col gap-3">
      <header className="flex flex-col gap-2">
        <div className="flex min-w-0 flex-col">
          <h3 className="text-sm font-semibold">Plan diff · baseline → {arm}</h3>
          <p className="text-xs text-muted">EXPLAIN ANALYZE captured in the sandbox after timing, one capture per arm and parameter set.</p>
        </div>
        <div className="flex min-w-0 flex-wrap items-end gap-3">
          <label className="flex min-w-0 max-w-full flex-col gap-1">
            <span className="qc-label">Candidate</span>
            <select
              value={arm}
              onChange={(e) => onSelectArm(e.target.value)}
              disabled={arms.length < 2}
              className="qc-input max-w-full min-w-0 truncate font-mono text-[13px] pointer-coarse:min-h-10"
            >
              {arms.map((a) => (
                <option key={a} value={a}>
                  {name(a)}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="qc-label">Parameter set</span>
            <select
              value={chosen ?? ""}
              onChange={(e) => setPs(e.target.value)}
              disabled={sets.length < 2}
              className="qc-input font-mono text-[13px] pointer-coarse:min-h-10"
            >
              {sets.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
        </div>
      </header>
      {chosen && from && to ? (
        <PlanDiffView runId={runId} from={from} to={to} layout={layout ?? (compact ? "unified" : "side")} onLayout={setLayout} benchmark={benchmark} />
      ) : (
        <p role="note" className="text-sm text-muted">
          {!chosen
            ? `No plan was captured for ${arm}, so there is nothing to compare.`
            : !from
              ? `No baseline plan was captured for parameter set ${chosen}, so there is nothing to compare.`
              : `No plan was captured for ${arm} on parameter set ${chosen}.`}
        </p>
      )}
    </section>
  );
}
