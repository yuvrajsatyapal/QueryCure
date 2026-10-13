"use client";

import type { ReactNode } from "react";
import type { LineageSource } from "@/components/lineage/LineageDrawer";
import { VerdictBadge } from "@/components/tournament/VerdictBadge";
import { OUTCOME_LABEL, REASON_TEXT, VERDICT_EXPLANATION, ms, x } from "@/lib/report/labels";
import type { CandidateAudit, Measurement, ReportRound, ReportV1 } from "@/lib/report/types";

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

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="flex flex-col gap-2">
      <h2 className="text-lg font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function Sql({ lines }: { lines: string[] }) {
  return (
    <pre className="overflow-x-auto rounded-md border border-border bg-surface-2 p-2 font-mono text-xs">
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
        <p key={i} className="text-xs">
          <AiLabel /> concern ({c.severity}): {c.text}{" "}
          <Source provenance="agent claim" evidenceIds={c.evidenceIds} onWhy={onWhy} claim={`Auditor concern: ${c.text}`} />
        </p>
      ))}
      {audit.notes ? (
        <p className="text-xs text-muted">
          <AiLabel /> {audit.notes}
        </p>
      ) : null}
    </div>
  );
}

function Round({ rnd, onWhy }: { rnd: ReportRound; onWhy?: Why }) {
  const exp = rnd.experiment;
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-4">
      <h3 className="font-semibold">Round {rnd.round + 1}</h3>
      <p className="text-sm">
        Approval: <span className="font-medium">{rnd.approval?.status ?? "not requested"}</span>
        {rnd.approval?.decidedBy ? <span className="text-muted"> by {rnd.approval.decidedBy}</span> : null}
      </p>
      {rnd.candidates.map((c) => (
        <div key={c.key} className="flex flex-col gap-1">
          <p className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-mono text-xs">{c.key}</span>
            <span className="text-muted">{c.kind.replaceAll("_", " ")}</span>
            <VerdictBadge status={c.status} />
            {c.reasons.map((r) => (
              <span key={r.code} className="text-xs text-muted" title={r.detail}>
                {REASON_TEXT[r.code] ?? r.code}
              </span>
            ))}
          </p>
          <Sql lines={c.ddl.length ? c.ddl : c.querySql ? [c.querySql] : []} />
          <p className="text-xs text-muted">
            <AiLabel /> Expected benefit: {c.expectedBenefit}
          </p>
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

export function ReportView({ report, onWhy }: { report: ReportV1; onWhy?: Why }) {
  const r = report;
  const rec = r.recommendation;
  const benchmarked = r.rounds.some((rnd) => rnd.experiment);
  const prerecorded = r.provenance.measurements.includes("prerecorded");
  return (
    <article className="flex max-w-[880px] flex-col gap-6" aria-label="Final report">
      <header className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-4">
        <p className="font-mono text-xs uppercase tracking-wider text-muted">
          Final report · {r.run.kind.replaceAll("_", " ")} · run {r.run.runNumber}
        </p>
        <h1 className="text-xl font-semibold">{OUTCOME_LABEL[r.outcome ?? ""] ?? `Run ${r.finalStatus}`}</h1>
        <p>{r.headline}</p>
        {r.recommendation.status in VERDICT_EXPLANATION ? (
          <p className="text-sm text-muted">{VERDICT_EXPLANATION[r.recommendation.status]}</p>
        ) : null}
        {benchmarked ? (
          <p role="note" className="rounded-md bg-surface-2 p-2 text-sm">
            Sandbox only: every measurement ran in a disposable copy of a demo database. Nothing was applied to your database.
          </p>
        ) : null}
        {prerecorded ? (
          <p role="note" className="rounded-md border border-inconclusive p-2 text-sm text-inconclusive">
            Contains prerecorded demo measurements: these are not live results.
          </p>
        ) : null}
        {r.provenance.stubModel ? (
          <p role="note" className="rounded-md border border-border-strong p-2 text-sm">
            Agent text came from the offline stub model: canned, not a diagnosis.
          </p>
        ) : null}
        {r.partial ? (
          <p role="note" className="text-sm text-inconclusive">
            Partial report: the run stopped ({r.stopReason ?? r.finalStatus}). Sections without data are listed under Missing evidence.
          </p>
        ) : null}
        {r.summary ? (
          <p className="text-sm">
            <AiLabel /> {r.summary}
          </p>
        ) : null}
      </header>

      <Section title="Query">
        {r.query.sql ? <Sql lines={[r.query.sql]} /> : <p className="text-sm text-muted">No query was provided.</p>}
        {r.query.paramSets?.map((p) => (
          <p key={p.name} className="font-mono text-xs">
            {p.name}: {JSON.stringify(p.values)}
            {p.edgeCase ? " (edge case)" : ""}
          </p>
        ))}
      </Section>

      <Section title="Observed problem">
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

      <Section title="Hypotheses">
        {r.hypotheses.length === 0 ? <p className="text-sm text-muted">No hypotheses were produced.</p> : null}
        <ol className="flex flex-col gap-2">
          {r.hypotheses.map((h) => (
            <li key={h.key} className="text-sm">
              <AiLabel /> <span className="font-medium">{h.category.replaceAll("_", " ")}</span> ({h.confidence} confidence): {h.statement}{" "}
              <Source provenance="agent claim" evidenceIds={h.supportingEvidence} onWhy={onWhy} claim={`Hypothesis: ${h.category}`} />
            </li>
          ))}
        </ol>
      </Section>

      {r.rounds.length ? (
        <Section title="Optimizations, approvals and benchmarks">
          {r.rounds.map((rnd) => (
            <Round key={rnd.round} rnd={rnd} onWhy={onWhy} />
          ))}
        </Section>
      ) : null}

      <Section title="Recommendation">
        {rec.candidateKey ? (
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

      {r.replay?.comparison ? (
        <Section title="Experiment replay">
          <p className="text-sm">
            Re-measured experiment <span className="font-mono">{r.replay.replayOf?.experimentId.slice(0, 8)}</span> with the same configuration and seed, no
            model calls: <span className="font-medium">{r.replay.comparison.status.replaceAll("_", " ")}</span> (
            {r.replay.comparison.comparisonMode.replaceAll("_", " ")}).
          </p>
        </Section>
      ) : null}

      <Section title="Limitations">
        <ul className="list-disc pl-5 text-sm">
          {r.limitations.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      </Section>
      <Section title="Next steps">
        <ul className="list-disc pl-5 text-sm">
          {r.nextSteps.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      </Section>
      {r.missing.length ? (
        <Section title="Missing evidence">
          <ul className="list-disc pl-5 text-sm">
            {r.missing.map((m) => (
              <li key={m.section}>
                <span className="font-mono">{m.section}</span>: {m.reason}
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
      <Section title="Provenance and integrity">
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
}
