"use client";

import { useId, useState, type ReactNode } from "react";
import { VerdictBadge } from "@/components/tournament/VerdictBadge";
import { Icon, type IconName } from "@/components/ui/Icon";
import { describeCandidate } from "@/lib/benchmark/candidate";
import { VERDICT_EXPLANATION, x } from "@/lib/report/labels";
import { LEGACY_REPLAY_NOTICE, LEGACY_REPLAY_TITLE, REPLAY_TONE, YES_NO, headlineBody, isLegacyReplayReport, replayResultOf, reportTitle } from "@/lib/report/replay";
import type { ReportV1 } from "@/lib/report/types";

const EXPANDED_KEY = "qc.resultSummary.expanded";

function readExpanded(): boolean {
  try {
    return typeof window !== "undefined" && window.localStorage.getItem(EXPANDED_KEY) === "1";
  } catch {
    return false;
  }
}

/** A one-line provenance note. Warnings keep their colour; none of these is ever collapsed. */
function Note({ icon, warn = false, children }: { icon: IconName; warn?: boolean; children: ReactNode }) {
  return (
    <li className={`flex items-start gap-1.5 ${warn ? "text-inconclusive" : "text-muted"}`}>
      <Icon name={icon} size={13} className={`mt-[3px] shrink-0 ${warn ? "" : "text-faint"}`} />
      <span>{children}</span>
    </li>
  );
}

/** The sealed report's conclusion above the trace (FINAL_UI_POLISH §2.1, UI_UX §3.6a): outcome,
 * headline, verdict, candidate and primary interval, and every provenance warning, always shown;
 * the limitations and the verdict explanation sit behind a disclosure so the trace stays in
 * reach. The AI-written summary and the detail stay in the Report tab. */
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
  const [expanded, setExpanded] = useState(readExpanded);
  const panel = useId();
  const rec = r.recommendation;
  const m = rec.primaryMeasurement;
  const benchmarked = r.rounds.some((rnd) => rnd.experiment);
  const prerecorded = r.provenance.measurements.includes("prerecorded");
  const verified = rec.status === "verified" || rec.status === "verified_with_noise_warning";
  const explanation = verified && rec.status in VERDICT_EXPLANATION ? VERDICT_EXPLANATION[rec.status] : null;
  const more = r.limitations.length + (explanation ? 1 : 0);
  const rr = replayResultOf(r);
  const legacy = isLegacyReplayReport(r);
  const tone = rr ? { verified: "text-verified", inconclusive: "text-inconclusive", rejected: "text-rejected", muted: "text-muted" }[REPLAY_TONE[rr.result]] : "";

  function toggle() {
    const next = !expanded;
    setExpanded(next);
    try {
      window.localStorage.setItem(EXPANDED_KEY, next ? "1" : "0");
    } catch {
      // Remembering the choice is a convenience; without storage it resets on reload.
    }
  }

  return (
    <section aria-label="Result summary" className="flex flex-col gap-2.5 rounded-lg border border-border bg-surface px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
        <div className="flex min-w-0 flex-1 basis-96 flex-col gap-0.5">
          <p className="qc-eyebrow">Result · run {r.run.runNumber}</p>
          <h2 className={`text-base font-semibold tracking-tight ${tone}`}>{reportTitle(r)}</h2>
          <p className="text-sm">{headlineBody(r)}</p>
          {legacy ? (
            <p role="note" aria-label="Legacy replay" className="mt-1 flex flex-wrap items-baseline gap-x-2 text-[13px] text-muted">
              <span className="rounded border border-inconclusive/50 px-1 font-mono text-[11px] text-inconclusive">Legacy replay</span>
              <span>
                {LEGACY_REPLAY_TITLE} {LEGACY_REPLAY_NOTICE}
              </span>
            </p>
          ) : null}
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <button type="button" onClick={onReport} className="qc-btn-secondary py-1 text-xs pointer-coarse:min-h-11">
            Full report
          </button>
          {onBenchmark && benchmarked ? (
            <button type="button" onClick={onBenchmark} className="qc-btn-secondary py-1 text-xs pointer-coarse:min-h-11">
              Benchmark details
            </button>
          ) : null}
        </div>
      </div>

      {rr ? (
        <div className="flex flex-col gap-1 border-t border-border pt-2.5 text-sm">
          {rec.origin === "source_run" && rec.candidateKey ? (
            <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="qc-eyebrow">Original recommendation</span>
              <VerdictBadge status={rec.status} />
              <span className="font-medium">{describeCandidate({ kind: rec.kind ?? "", ddl: rec.ddl, querySql: rec.querySql })}</span>
              <span className="font-mono text-xs text-muted">{rec.candidateKey}</span>
              <span className="text-muted">from the source run, reproduced by this replay</span>
            </p>
          ) : (
            <p className="text-muted">This replay makes no recommendation of its own.</p>
          )}
          <p className="text-[13px] text-muted">
            Comparison {rr.comparisonStatus?.replaceAll("_", " ") ?? "none"}
            {rr.comparisonMode ? ` · ${rr.comparisonMode.replaceAll("_", " ")}` : ""} · correctness reproduced {YES_NO(rr.correctnessReproduced).toLowerCase()} · performance
            reproduced {YES_NO(rr.performanceReproduced).toLowerCase()}
          </p>
          {rr.replayMeasurement.engineWinner ? (
            <p className="text-[13px] text-muted">
              Replay&apos;s own best arm <span className="font-mono">{rr.replayMeasurement.engineWinner}</span>: {rr.replayMeasurement.label}
            </p>
          ) : null}
        </div>
      ) : rec.candidateKey ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border pt-2.5 text-sm">
          <VerdictBadge status={rec.status} />
          <span className="font-medium">{describeCandidate({ kind: rec.kind ?? "", ddl: rec.ddl, querySql: rec.querySql })}</span>
          <span className="font-mono text-xs text-muted">{rec.candidateKey}</span>
          {m ? (
            <span>
              <span className="text-muted">Speedup on </span>
              <span className="font-mono text-xs">{m.paramSet}</span>
              <span className="text-muted">: </span>
              <span className="font-semibold tabular-nums">{x(m.speedup)}</span>
              <span className="text-muted">
                {" "}
                · 95% CI <span className="tabular-nums">{x(m.ciLow)}–{x(m.ciHigh)}</span> · n {m.baseline.n}/{m.candidate.n} · {m.provenance ?? "recorded"}
              </span>
            </span>
          ) : null}
        </div>
      ) : (
        <p className="border-t border-border pt-2.5 text-sm text-muted">
          No recommendation was verified.{benchmarked && onBenchmark ? " Benchmark details give each candidate's verdict and its reason." : ""}
        </p>
      )}

      <ul aria-label="Provenance" className="flex flex-col gap-1 text-[13px] leading-5 empty:hidden">
        {benchmarked ? <Note icon="flask">Sandbox only: every measurement ran in a disposable copy of a demo database. Nothing was applied to your database.</Note> : null}
        {prerecorded ? (
          <Note icon="alert" warn>
            Contains prerecorded demo measurements: these are not live results.
          </Note>
        ) : null}
        {r.provenance.stubModel ? <Note icon="bot">Agent text came from the offline stub model: canned, not a diagnosis.</Note> : null}
        {r.partial ? (
          <Note icon="alert" warn>
            Partial report: the run stopped ({r.stopReason ?? r.finalStatus}).
          </Note>
        ) : null}
      </ul>

      {more ? (
        <div className="flex flex-col gap-2">
          <button
            type="button"
            aria-expanded={expanded}
            aria-controls={panel}
            onClick={toggle}
            className="flex w-fit items-center gap-1 text-[13px] font-medium text-ink hover:text-accent pointer-coarse:min-h-11"
          >
            <Icon name={expanded ? "chevronDown" : "chevronRight"} size={13} className="text-muted" />
            {r.limitations.length ? `Limitations (${r.limitations.length})` : "What this verdict means"}
          </button>
          <div id={panel} hidden={!expanded} className="flex flex-col gap-2 pl-[18px] text-sm">
            {explanation ? <p className="text-muted">{explanation}</p> : null}
            {r.limitations.length ? (
              <ul aria-label="Limitations" className="list-disc pl-4 text-muted">
                {r.limitations.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
