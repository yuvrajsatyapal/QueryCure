"use client";

import { useEffect, useState, type ReactNode } from "react";
import { Icon, type IconName } from "@/components/ui/Icon";
import type { LineageSource } from "@/components/lineage/LineageDrawer";
import { VerdictBadge } from "@/components/tournament/VerdictBadge";
import { describeCandidate } from "@/lib/benchmark/candidate";
import { REASON_TEXT, VERDICT_EXPLANATION, ms, x } from "@/lib/report/labels";
import { REPLAY_TONE, YES_NO, headlineBody, replayResultOf, reportTitle } from "@/lib/report/replay";
import { reportSections, sectionId, type ReportSection } from "@/lib/report/sections";
import type { CandidateAudit, Measurement, ReplayResult, ReportRound, ReportV1 } from "@/lib/report/types";

type Why = (source: LineageSource) => void;

/** Provenance always in words, plus a "Why?" that opens the lineage drawer. */
function Source({ provenance, evidenceIds = [], onWhy, claim, artifact }: {
  provenance: string | null;
  evidenceIds?: (string | null)[];
  onWhy?: Why;
  claim: string;
  artifact?: LineageSource["artifact"];
}) {
  const ids = evidenceIds.filter((i): i is string => Boolean(i));
  return (
    <span className="inline-flex items-center gap-1 font-mono text-[11px] text-muted">
      <span className="rounded border border-border px-1">{provenance ?? "recorded"}</span>
      {onWhy ? (
        <button
          type="button"
          className="text-link underline-offset-2 hover:underline"
          onClick={() => onWhy({ claim, provenance: provenance ?? "recorded", evidenceIds: ids, artifact })}
          aria-label={`Why: ${claim}`}
        >
          Why?
        </button>
      ) : null}
    </span>
  );
}

function AiLabel() {
  return <span className="rounded border border-hypothesis px-1 font-mono text-[10px] text-hypothesis">AI-written</span>;
}

/** Model-written prose, set apart from measured and recorded values (UI_UX §3.11). */
function AiBlock({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`border-l-2 border-hypothesis/60 pl-3 ${className}`}>
      <AiLabel /> {children}
    </div>
  );
}

const CALLOUT: Record<"info" | "warning" | "neutral", { icon: IconName; box: string; iconClass: string }> = {
  info: { icon: "flask", box: "border-border bg-surface-2", iconClass: "text-accent" },
  warning: { icon: "alert", box: "border-inconclusive/40 bg-inconclusive/10 text-inconclusive", iconClass: "text-inconclusive" },
  neutral: { icon: "bot", box: "border-border-strong bg-surface", iconClass: "text-muted" },
};

export function Callout({ tone, children }: { tone: keyof typeof CALLOUT; children: ReactNode }) {
  const c = CALLOUT[tone];
  return (
    <p role="note" className={`flex items-start gap-2 rounded-md border px-3 py-2 text-sm ${c.box}`}>
      <Icon name={c.icon} size={14} className={`mt-0.5 ${c.iconClass}`} />
      <span>{children}</span>
    </p>
  );
}

/** `n` is the section's 1-based position in reportSections(); 0 means the contents list omits it,
 * so the section is not rendered. The list is the only place that decides which sections show. */
function Section({ title, n, children }: { title: string; n: number; children: ReactNode }) {
  if (n < 1) return null;
  return (
    <section id={sectionId(title)} aria-label={title} className="flex scroll-mt-32 flex-col gap-3 border-t border-border pt-6">
      <h2 className="flex items-baseline gap-2 text-base font-semibold">
        <span aria-hidden="true" className="w-5 font-mono text-xs text-muted tabular-nums">
          {String(n).padStart(2, "0")}
        </span>
        {title}
      </h2>
      {children}
    </section>
  );
}

/** Sticky contents list for the sections this report renders; highlights the one in view. */
function ReportToc({ sections }: { sections: ReportSection[] }) {
  const [active, setActive] = useState(sections[0]?.id ?? "");
  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) setActive(visible[0].target.id);
      },
      { rootMargin: "-20% 0px -70% 0px" },
    );
    for (const s of sections) {
      const el = document.getElementById(s.id);
      if (el) io.observe(el);
    }
    return () => io.disconnect();
  }, [sections]);
  return (
    <nav aria-label="Report contents" className="sticky top-6 hidden max-h-[calc(100vh-3rem)] overflow-y-auto print:hidden lg:block">
      <p className="qc-eyebrow mb-2">On this page</p>
      <ol className="flex flex-col border-l border-border">
        {sections.map((s, i) => (
          <li key={s.id}>
            <a
              href={`#${s.id}`}
              aria-current={active === s.id ? "location" : undefined}
              className={`-ml-px flex gap-2 border-l py-1 pl-3 text-[13px] no-underline ${
                active === s.id ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink"
              }`}
            >
              <span className="font-mono text-[11px] tabular-nums">{String(i + 1).padStart(2, "0")}</span>
              {s.title}
            </a>
          </li>
        ))}
      </ol>
    </nav>
  );
}

function Sql({ lines }: { lines: string[] }) {
  return (
    <pre tabIndex={0} className="overflow-x-auto rounded-md border border-border bg-surface-2 p-2 font-mono text-xs">
      {lines.join(";\n")}
    </pre>
  );
}

function MeasurementTable({ rows, onWhy }: { rows: Measurement[]; onWhy?: Why }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-left text-sm">
        <caption className="pb-1 text-left text-xs text-muted">
          Medians and the 95% bootstrap interval of the speed-up, measured in the sandbox.
        </caption>
        <thead className="font-mono text-[11px] uppercase text-muted">
          <tr>
            <th className="py-1 pr-2">Candidate</th>
            <th className="py-1 pr-2">Param set</th>
            <th className="py-1 pr-2">Baseline</th>
            <th className="py-1 pr-2">Candidate</th>
            <th className="py-1 pr-2">Speed-up (interval)</th>
            <th className="py-1 pr-2">n</th>
            <th className="py-1">Source</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((m) => (
            <tr key={`${m.arm}:${m.paramSet}`} className="border-t border-border">
              <td className="py-1 pr-2 font-mono text-xs">{m.arm}</td>
              <td className="py-1 pr-2 font-mono text-xs">{m.paramSet}</td>
              <td className="py-1 pr-2">{ms(m.baseline.medianNs)}</td>
              <td className="py-1 pr-2">{ms(m.candidate.medianNs)}</td>
              <td className="py-1 pr-2">
                {x(m.speedup)} <span className="text-muted">({x(m.ciLow)}–{x(m.ciHigh)})</span>
              </td>
              <td className="py-1 pr-2 font-mono text-xs">
                {m.baseline.n}/{m.candidate.n}
              </td>
              <td className="py-1">
                <Source
                  provenance={m.provenance}
                  evidenceIds={[m.evidenceId]}
                  onWhy={onWhy}
                  claim={`Speed-up ${x(m.speedup)} for ${m.arm} on ${m.paramSet}`}
                  artifact={{ sha256: m.source.artifactSha256, pointer: m.source.pointer, label: "Experiment result artifact" }}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const CHECK_ICON: Record<string, string> = { pass: "✓", warn: "!", fail: "✕", skip: "–" };

export function AuditSummary({ audit, onWhy }: { audit: CandidateAudit; onWhy?: Why }) {
  return (
    <div className="flex flex-col gap-1 rounded-md border border-border p-3 text-sm" aria-label={`Audit of ${audit.arm}`}>
      <p className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs">{audit.arm}</span>
        {audit.downgraded ? (
          <>
            <VerdictBadge status={audit.engineVerdict} /> → <VerdictBadge status={audit.verdict} />
            <span className="text-xs text-inconclusive">Downgraded by the Benchmark Auditor</span>
          </>
        ) : (
          <>
            <VerdictBadge status={audit.verdict} />
            <span className="text-xs text-muted">unchanged by the audit</span>
          </>
        )}
        <span className="text-xs text-muted">
          review: {audit.auditorStatus === "completed" ? "checks + narrative" : "deterministic checks only"}
        </span>
      </p>
      <ul className="flex flex-col gap-0.5">
        {audit.checks.map((c) => (
          <li key={c.name} className="flex flex-wrap items-start gap-2 text-xs">
            <span aria-hidden="true" className={c.status === "fail" ? "text-rejected" : c.status === "warn" ? "text-inconclusive" : "text-muted"}>
              {CHECK_ICON[c.status]}
            </span>
            <span className="font-mono">{c.name}</span>
            <span className="text-muted">{c.status}</span>
            <span className="min-w-0 flex-1 break-words">{c.detail}</span>
            {c.evidenceIds.length && onWhy ? (
              <Source provenance="derived" evidenceIds={c.evidenceIds} onWhy={onWhy} claim={`Audit check ${c.name}: ${c.status}`} />
            ) : null}
          </li>
        ))}
      </ul>
      {audit.concerns.map((c, i) => (
        <AiBlock key={i} className="text-xs">
          concern ({c.severity}): {c.text}{" "}
          <Source provenance="agent claim" evidenceIds={c.evidenceIds} onWhy={onWhy} claim={`Auditor concern: ${c.text}`} />
        </AiBlock>
      ))}
      {audit.notes ? (
        <AiBlock className="text-xs text-muted">{audit.notes}</AiBlock>
      ) : null}
    </div>
  );
}

function Round({ rnd, onWhy }: { rnd: ReportRound; onWhy?: Why }) {
  const exp = rnd.experiment;
  return (
    <div className="flex flex-col gap-2 qc-panel p-4">
      <h3 className="font-semibold">Round {rnd.round + 1}</h3>
      <p className="text-sm">
        Approval: <span className="font-medium">{rnd.approval?.status ?? "not requested"}</span>
        {rnd.approval?.decidedBy ? <span className="text-muted"> by {rnd.approval.decidedBy}</span> : null}
      </p>
      {rnd.candidates.map((c) => (
        <div key={c.key} className="flex flex-col gap-1">
          <p className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-medium">{describeCandidate(c)}</span>
            <span className="font-mono text-xs">{c.key}</span>
            <VerdictBadge status={c.status} />
            {c.reasons.map((r) => (
              <span key={r.code} className="text-xs text-muted" title={r.detail}>
                {REASON_TEXT[r.code] ?? r.code}
              </span>
            ))}
          </p>
          <Sql lines={c.ddl.length ? c.ddl : c.querySql ? [c.querySql] : []} />
          <AiBlock className="text-xs text-muted">Expected benefit: {c.expectedBenefit}</AiBlock>
        </div>
      ))}
      {exp ? (
        <>
          <p className="text-xs text-muted">
            Experiment <span className="font-mono">{exp.id.slice(0, 8)}</span> · {exp.status} · engine {exp.engineVersion} · seed {exp.seed} ·
            samples {exp.provenance ?? "none"}
            {exp.environment.pgVersion ? ` · PostgreSQL ${exp.environment.pgVersion}, ${exp.environment.cpuArch}, ${exp.environment.containerRuntime}` : ""}
          </p>
          {exp.errorCode ? <p className="text-sm text-rejected">Experiment error: {exp.errorCode}</p> : null}
          {exp.measurements.length ? <MeasurementTable rows={exp.measurements} onWhy={onWhy} /> : null}
          {exp.correctness.length ? (
            <ul className="text-xs">
              {exp.correctness.map((c) => (
                <li key={`${c.arm}:${c.paramSet}`}>
                  Correctness {c.arm} on {c.paramSet}:{" "}
                  {c.sameRows === null ? "not comparable" : c.sameRows ? "same rows as the baseline" : "different rows than the baseline"} ({c.rows} vs{" "}
                  {c.baselineRows} rows){" "}
                  <Source provenance={c.provenance} evidenceIds={[c.evidenceId]} onWhy={onWhy} claim={`Correctness of ${c.arm} on ${c.paramSet}`} />
                </li>
              ))}
            </ul>
          ) : null}
          {exp.replication?.verdicts.map((v) => (
            <p key={v.arm} className="text-xs">
              Replication {v.arm}: <VerdictBadge status={v.verdict} /> over {v.experimentIds.length} independent experiments
              {v.ciLow !== null && v.ciHigh !== null ? ` · interval range ${x(v.ciLow)}–${x(v.ciHigh)}` : ""}
            </p>
          ))}
          {exp.audit.map((a) => (
            <AuditSummary key={a.arm} audit={a} onWhy={onWhy} />
          ))}
        </>
      ) : (
        <p className="text-sm text-muted">Not benchmarked.</p>
      )}
    </div>
  );
}

const TONE_TEXT = { verified: "text-verified", inconclusive: "text-inconclusive", rejected: "text-rejected", muted: "text-muted" } as const;

/** Identifiers and digests for reproducing a claim: always shown in full, set small and after the
 * content they support so they do not compete with it on narrow screens. */
function SourceDetails({ rows }: { rows: [string, string | null | undefined][] }) {
  return (
    <ul aria-label="Source details" className="flex flex-col gap-1 rounded-md border border-border px-3 py-2 text-xs text-muted">
      {rows.map(([k, v]) => (
        <li key={k} className="flex min-w-0 flex-col sm:flex-row sm:gap-2">
          <span className="shrink-0 sm:w-40">{k}</span>
          <span className="min-w-0 font-mono break-all text-ink">{v ?? "not recorded"}</span>
        </li>
      ))}
    </ul>
  );
}

/** Schema 2, experiment replays: the builder's sealed facts about the replay and its source. */
function ReplayResultSection({ rr, n }: { rr: ReplayResult; n: number }) {
  const src = rr.source;
  const winner = rr.replayMeasurement.engineWinner;
  const facts: [string, string][] = [
    ["Comparison", rr.comparisonStatus ? `${rr.comparisonStatus.replaceAll("_", " ")}${rr.comparisonMode ? ` · ${rr.comparisonMode.replaceAll("_", " ")}` : ""}${rr.comparisonFailureCode ? ` · ${rr.comparisonFailureCode.replaceAll("_", " ")}` : ""}` : "None recorded"],
    ["Correctness reproduced", YES_NO(rr.correctnessReproduced)],
    ["Performance reproduced", YES_NO(rr.performanceReproduced)],
    ["Material drift", YES_NO(rr.materialDrift)],
    ["Environments comparable", YES_NO(rr.environmentComparable) + (rr.materialDifferences.length ? ` · differs in ${rr.materialDifferences.join(", ")}` : "")],
    ["Matching experiment", rr.experimentMatch.matches === null ? "No measured original recommendation" : rr.experimentMatch.matches ? "The original recommendation was measured by this experiment" : "The original recommendation was measured by another experiment"],
    [src?.outcome === "no_action_needed" ? "Original conclusion reproduced" : "Original recommendation reproduced", YES_NO(rr.originalReproduced)],
  ];
  return (
    <Section title="Experiment replay result" n={n}>
      <p className="text-sm">Re-measured one experiment of the original investigation with the same configuration and seed; no model calls.</p>
      <p className={`text-sm font-medium ${TONE_TEXT[REPLAY_TONE[rr.result]]}`}>{rr.explanation}</p>
      <dl className="grid grid-cols-1 gap-x-4 gap-y-1 text-sm sm:grid-cols-[minmax(0,14rem)_minmax(0,1fr)]">
        {facts.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-muted">{k}</dt>
            <dd className="max-sm:mb-1">{v}</dd>
          </div>
        ))}
      </dl>
      {rr.snapshotError ? <Callout tone="warning">Source snapshot could not be read: {rr.snapshotError}</Callout> : null}
      <p className="text-sm text-muted">
        Replay&apos;s own best arm:{" "}
        {winner ? (
          <>
            <span className="font-mono text-ink">{winner}</span> ({rr.replayMeasurement.provenance ?? "recorded"}): {rr.replayMeasurement.label}
          </>
        ) : (
          "none"
        )}
      </p>
      <SourceDetails
        rows={[
          ["Source run", src ? `${src.runId} (${src.runKind.replaceAll("_", " ")})` : "no source snapshot was read"],
          ["Source experiment", src?.experimentId ?? rr.experimentMatch.replayedExperimentId],
          ["Stored source outcome", src ? (src.outcome ?? "none") : null],
          ["Source sealed by", src?.builderVersion],
          ["Source manifest", src ? `sha256:${src.manifestSha256}` : null],
          ["Source report JSON", src ? `sha256:${src.reportJsonSha256}` : null],
          ["Replayed result", rr.experimentMatch.replayedResultSha256 ? `sha256:${rr.experimentMatch.replayedResultSha256}` : null],
          ["Classification basis", rr.basis?.code],
        ]}
      />
    </Section>
  );
}

export function ReportView({ report, onWhy, toc = false }: { report: ReportV1; onWhy?: Why; toc?: boolean }) {
  const r = report;
  const rec = r.recommendation;
  const benchmarked = r.rounds.some((rnd) => rnd.experiment);
  const prerecorded = r.provenance.measurements.includes("prerecorded");
  const sections = reportSections(r);
  const rr = replayResultOf(r);
  const fromSource = rr !== null && rec.origin === "source_run";
  const n = (title: string) => sections.findIndex((s) => s.title === title) + 1;
  const article = (
    <article className="flex min-w-0 max-w-[46rem] flex-col gap-6" aria-label="Final report">
      <header className="flex flex-col gap-3 qc-panel p-5">
        <p className="qc-eyebrow">
          Final report · {r.run.kind.replaceAll("_", " ")} · run {r.run.runNumber}
        </p>
        <h1 className={`text-2xl font-semibold tracking-tight ${rr ? TONE_TEXT[REPLAY_TONE[rr.result]] : ""}`}>{reportTitle(r)}</h1>
        <p className="text-[15px] leading-relaxed">{headlineBody(r)}</p>
        {rr ? (
          fromSource ? (
            <p className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border pt-3 text-sm">
              <span className="qc-eyebrow">Original recommendation</span>
              <VerdictBadge status={rec.status} />
              <span className="font-mono text-xs">{rec.candidateKey}</span>
              <span className="text-muted">from the source run, reproduced by this replay</span>
            </p>
          ) : null
        ) : rec.candidateKey || rec.status in VERDICT_EXPLANATION ? (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border pt-3 text-sm">
            <VerdictBadge status={rec.status} />
            {rec.candidateKey ? <span className="font-mono text-xs">{rec.candidateKey}</span> : null}
            {rec.primaryMeasurement ? (
              <span className="text-muted">
                {rec.primaryMeasurement.paramSet}: <span className="font-medium text-ink">{x(rec.primaryMeasurement.speedup)}</span> (
                {x(rec.primaryMeasurement.ciLow)}–{x(rec.primaryMeasurement.ciHigh)}) · {rec.primaryMeasurement.provenance}
              </span>
            ) : null}
          </div>
        ) : null}
        {!rr && r.recommendation.status in VERDICT_EXPLANATION ? (
          <p className="text-sm text-muted">{VERDICT_EXPLANATION[r.recommendation.status]}</p>
        ) : null}
        {benchmarked ? (
          <Callout tone="info">Sandbox only: every measurement ran in a disposable copy of a demo database. Nothing was applied to your database.</Callout>
        ) : null}
        {prerecorded ? <Callout tone="warning">Contains prerecorded demo measurements: these are not live results.</Callout> : null}
        {r.provenance.stubModel ? <Callout tone="neutral">Agent text came from the offline stub model: canned, not a diagnosis.</Callout> : null}
        {r.partial ? (
          <Callout tone="warning">
            Partial report: the run stopped ({r.stopReason ?? r.finalStatus}). Sections without data are listed under Missing evidence.
          </Callout>
        ) : null}
        {r.summary ? <AiBlock className="text-sm">{r.summary}</AiBlock> : null}
      </header>

      <Section title="Query" n={n("Query")}>
        {r.query.sql ? <Sql lines={[r.query.sql]} /> : <p className="text-sm text-muted">No query was provided.</p>}
        {r.query.paramSets?.map((p) => (
          <p key={p.name} className="font-mono text-xs">
            {p.name}: {JSON.stringify(p.values)}
            {p.edgeCase ? " (edge case)" : ""}
          </p>
        ))}
      </Section>

      <Section title="Observed problem" n={n("Observed problem")}>
        {r.problem.materiality ? (
          <p className="text-sm">
            Materiality check: <span className="font-medium">{r.problem.materiality.verdict.replaceAll("_", " ")}</span>{" "}
            <span className="text-muted">{r.problem.materiality.reasons.join(" ")}</span>
          </p>
        ) : null}
        <ul className="flex flex-col gap-1 text-sm">
          {r.problem.evidence.map((e) => (
            <li key={e.id}>
              {e.summary} <Source provenance={e.provenance} evidenceIds={[e.id]} onWhy={onWhy} claim={e.summary} />
            </li>
          ))}
          {r.problem.evidence.length === 0 ? <li className="text-muted">No plan evidence was collected.</li> : null}
        </ul>
      </Section>

      <Section title="Hypotheses" n={n("Hypotheses")}>
        {r.hypotheses.length === 0 ? <p className="text-sm text-muted">No hypotheses were produced.</p> : null}
        <ol className="flex flex-col gap-2">
          {r.hypotheses.map((h) => (
            <li key={h.key} className="text-sm">
              <AiBlock>
                <span className="font-medium">{h.category.replaceAll("_", " ")}</span> ({h.confidence} confidence): {h.statement}{" "}
                <Source provenance="agent claim" evidenceIds={h.supportingEvidence} onWhy={onWhy} claim={`Hypothesis: ${h.category}`} />
              </AiBlock>
            </li>
          ))}
        </ol>
      </Section>

      {r.rounds.length && rr ? (
        <Section title="Replay measurement" n={n("Replay measurement")}>
          <p className="text-sm text-muted">These are the replay&apos;s own sandbox measurements: a single re-measurement, not a verification.</p>
          {r.rounds.map((rnd) => (
            <Round key={rnd.round} rnd={rnd} onWhy={onWhy} />
          ))}
        </Section>
      ) : null}
      {r.rounds.length && !rr ? (
        <Section title="Optimizations, approvals and benchmarks" n={n("Optimizations, approvals and benchmarks")}>
          {r.rounds.map((rnd) => (
            <Round key={rnd.round} rnd={rnd} onWhy={onWhy} />
          ))}
        </Section>
      ) : null}

      {rr ? <ReplayResultSection rr={rr} n={n("Experiment replay result")} /> : null}

      {rr && !fromSource ? (
        <Section title="Recommendation" n={n("Recommendation")}>
          <p className="text-sm">This replay makes no recommendation of its own.</p>
          {rr.sourceRecommendation ? (
            <p className="text-sm text-muted">
              The source investigation&apos;s recommendation <span className="font-mono">{rr.sourceRecommendation.candidateKey}</span> (
              {rr.sourceRecommendation.status.replaceAll("_", " ")}) is shown for reference and is not confirmed by this replay.
            </p>
          ) : null}
        </Section>
      ) : null}

      {!rr || fromSource ? (
        <Section title={fromSource ? "Original recommendation" : "Recommendation"} n={n(fromSource ? "Original recommendation" : "Recommendation")}>
          {fromSource ? (
            <>
              <div className="flex flex-col gap-1.5">
                <h3 className="text-[15px] font-semibold">{rec.candidateKey && rec.kind ? describeCandidate({ ...rec, kind: rec.kind }) : (rec.candidateKey ?? "Original recommendation")}</h3>
                <p className="flex flex-wrap items-center gap-2 text-sm">
                  <VerdictBadge status={rec.status} />
                  <span>Verified in the sandbox by the source investigation and reproduced by this replay. Review it before applying it.</span>
                </p>
              </div>
              <Sql lines={rec.ddl.length ? rec.ddl : rec.querySql ? [rec.querySql] : []} />
              {rec.primaryMeasurement ? (
                <p className="text-sm">
                  Speed-up on {rec.primaryMeasurement.paramSet} in the source run: <span className="font-medium">{x(rec.primaryMeasurement.speedup)}</span>{" "}
                  <span className="text-muted">
                    (interval {x(rec.primaryMeasurement.ciLow)}–{x(rec.primaryMeasurement.ciHigh)})
                  </span>{" "}
                  <Source
                    provenance={rec.primaryMeasurement.provenance}
                    evidenceIds={[rec.primaryMeasurement.evidenceId]}
                    onWhy={onWhy}
                    claim={`Original speed-up ${x(rec.primaryMeasurement.speedup)}`}
                    artifact={{
                      sha256: rec.primaryMeasurement.source.artifactSha256,
                      pointer: rec.primaryMeasurement.source.pointer,
                      label: "Experiment result artifact",
                    }}
                  />
                </p>
              ) : null}
              <SourceDetails
                rows={[
                  ["Candidate", rec.candidateKey],
                  ["Source run", rec.sourceRunId],
                  ["Source experiment", rr?.source?.experimentId],
                  ["Evidence", rec.primaryMeasurement?.evidenceId],
                  [
                    "Result artifact",
                    rec.primaryMeasurement ? `sha256:${rec.primaryMeasurement.source.artifactSha256} ${rec.primaryMeasurement.source.pointer}` : null,
                  ],
                ]}
              />
            </>
          ) : rec.candidateKey ? (
            <>
              <p className="text-sm">
                Apply <span className="font-mono">{rec.candidateKey}</span> after your own review: <VerdictBadge status={rec.status} /> in the sandbox.
              </p>
              <Sql lines={rec.ddl.length ? rec.ddl : rec.querySql ? [rec.querySql] : []} />
              {rec.primaryMeasurement ? (
                <p className="text-sm">
                  Primary parameter set {rec.primaryMeasurement.paramSet}: {x(rec.primaryMeasurement.speedup)} (interval{" "}
                  {x(rec.primaryMeasurement.ciLow)}–{x(rec.primaryMeasurement.ciHigh)}){" "}
                  <Source
                    provenance={rec.primaryMeasurement.provenance}
                    evidenceIds={[rec.primaryMeasurement.evidenceId]}
                    onWhy={onWhy}
                    claim={`Recommended speed-up ${x(rec.primaryMeasurement.speedup)}`}
                    artifact={{
                      sha256: rec.primaryMeasurement.source.artifactSha256,
                      pointer: rec.primaryMeasurement.source.pointer,
                      label: "Experiment result artifact",
                    }}
                  />
                </p>
              ) : null}
            </>
          ) : (
            <p className="text-sm">
              {rec.status === "unverified"
                ? "No change is recommended as verified. The hypotheses and candidates above are unverified."
                : "No change is recommended."}
            </p>
          )}
        </Section>
      ) : null}

      {r.replay?.comparison ? (
        <Section title={rr ? "Comparison with the original" : "Experiment replay"} n={n(rr ? "Comparison with the original" : "Experiment replay")}>
          <p className="text-sm">
            Re-measured experiment <span className="font-mono">{r.replay.replayOf?.experimentId.slice(0, 8)}</span> with the same configuration and seed, no
            model calls: <span className="font-medium">{r.replay.comparison.status.replaceAll("_", " ")}</span> (
            {r.replay.comparison.comparisonMode.replaceAll("_", " ")}).
          </p>
        </Section>
      ) : null}

      <Section title="Limitations" n={n("Limitations")}>
        <ul className="list-disc pl-5 text-sm">
          {r.limitations.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      </Section>
      <Section title="Next steps" n={n("Next steps")}>
        <ul className="list-disc pl-5 text-sm">
          {r.nextSteps.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      </Section>
      {r.missing.length ? (
        <Section title="Missing evidence" n={n("Missing evidence")}>
          <ul className="list-disc pl-5 text-sm">
            {r.missing.map((m) => (
              <li key={m.section}>
                <span className="font-mono">{m.section}</span>: {m.reason}
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
      <Section title="Provenance and integrity" n={n("Provenance and integrity")}>
        <ul className="flex flex-col gap-1 text-xs text-muted">
          {r.provenance.llm.length === 0 ? <li>No language-model calls were made for this run.</li> : null}
          {r.provenance.llm.map((c) => (
            <li key={`${c.agent}:${c.model}:${c.status}:${c.promptVersion}`}>
              {c.agent}: {c.model} · {c.promptVersion} · {c.status} · {c.calls} call(s)
            </li>
          ))}
          <li>
            Events sealed through sequence {r.events.cutoffSeq}, digest <span className="break-all font-mono">{r.events.digest}</span>
          </li>
          <li>
            {r.builderVersion} · report schema {r.schemaVersion} · finalized {r.finalizedAt}
          </li>
          <li>Integrity checks compare stored records with stored digests: they show consistency, not authenticity.</li>
        </ul>
      </Section>
    </article>
  );
  if (!toc) return article;
  return (
    <div className="grid grid-cols-1 gap-10 lg:grid-cols-[minmax(0,46rem)_13rem]">
      {article}
      <ReportToc sections={sections} />
    </div>
  );
}
