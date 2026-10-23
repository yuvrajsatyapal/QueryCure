import { VerdictBadge } from "@/components/tournament/VerdictBadge";
import { describeCandidate } from "@/lib/benchmark/candidate";
import { OUTCOME_LABEL, VERDICT_EXPLANATION, x } from "@/lib/report/labels";
import type { ReportV1 } from "@/lib/report/types";
import { Callout } from "./ReportView";

/** The sealed report's conclusion above the trace (FINAL_UI_POLISH §2.1): outcome, verdict,
 * candidate, primary interval and every limitation, as stored. The AI-written summary and the
 * detail stay in the Report tab. */
export function ResultSummary({
  report: r,
  onReport,
  onBenchmark,
}: {
  report: ReportV1;
  onReport: () => void;
  /** Absent when the run has no sandbox benchmark. */
  onBenchmark?: () => void;
}) {
  const rec = r.recommendation;
  const m = rec.primaryMeasurement;
  const benchmarked = r.rounds.some((rnd) => rnd.experiment);
  const prerecorded = r.provenance.measurements.includes("prerecorded");
  const verified = rec.status === "verified" || rec.status === "verified_with_noise_warning";
  return (
    <section aria-label="Result summary" className="flex flex-col gap-3 rounded-lg border border-border bg-surface p-4">
      <div className="flex flex-col gap-1">
        <p className="qc-eyebrow">Result · run {r.run.runNumber}</p>
        <h2 className="text-lg font-semibold tracking-tight">{OUTCOME_LABEL[r.outcome ?? ""] ?? `Run ${r.finalStatus}`}</h2>
        <p className="text-sm">{r.headline}</p>
      </div>

      {rec.candidateKey ? (
        <div className="flex flex-col gap-1.5 border-t border-border pt-3">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <VerdictBadge status={rec.status} />
            <span className="font-medium">{describeCandidate({ kind: rec.kind ?? "", ddl: rec.ddl, querySql: rec.querySql })}</span>
            <span className="font-mono text-xs text-muted">{rec.candidateKey}</span>
          </div>
          {m ? (
            <p className="text-sm">
              <span className="text-muted">Speedup on </span>
              <span className="font-mono text-xs">{m.paramSet}</span>
              <span className="text-muted">: </span>
              <span className="text-base font-semibold tabular-nums">{x(m.speedup)}</span>
              <span className="text-muted">
                {" "}
                · 95% CI <span className="tabular-nums">{x(m.ciLow)}–{x(m.ciHigh)}</span> · n {m.baseline.n}/{m.candidate.n} ·{" "}
                {m.provenance ?? "recorded"}
              </span>
            </p>
          ) : null}
        </div>
      ) : (
        <p className="border-t border-border pt-3 text-sm text-muted">
          No recommendation was verified.{benchmarked && onBenchmark ? " Benchmark details give each candidate's verdict and its reason." : ""}
        </p>
      )}
      {verified && rec.status in VERDICT_EXPLANATION ? <p className="text-sm text-muted">{VERDICT_EXPLANATION[rec.status]}</p> : null}

      <div className="flex flex-col gap-2">
        {benchmarked ? (
          <Callout tone="info">Sandbox only: every measurement ran in a disposable copy of a demo database. Nothing was applied to your database.</Callout>
        ) : null}
        {prerecorded ? <Callout tone="warning">Contains prerecorded demo measurements: these are not live results.</Callout> : null}
        {r.provenance.stubModel ? <Callout tone="neutral">Agent text came from the offline stub model: canned, not a diagnosis.</Callout> : null}
        {r.partial ? <Callout tone="warning">Partial report: the run stopped ({r.stopReason ?? r.finalStatus}).</Callout> : null}
      </div>

      {r.limitations.length ? (
        <div className="text-sm">
          <h3 className="font-medium">Limitations</h3>
          <ul className="mt-1 list-disc pl-5 text-muted">
            {r.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={onReport} className="qc-btn-secondary py-1 text-xs">
          Full report
        </button>
        {onBenchmark && benchmarked ? (
          <button type="button" onClick={onBenchmark} className="qc-btn-secondary py-1 text-xs">
            Benchmark details
          </button>
        ) : null}
      </div>
    </section>
  );
}
