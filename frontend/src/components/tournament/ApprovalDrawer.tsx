"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { ErrorNotice } from "@/components/common/ErrorNotice";
import { useModal } from "@/components/command/useModal";
import { EvidenceChip } from "@/components/investigation/EvidenceChip";
import { Icon } from "@/components/ui/Icon";
import { StatusPill, type Tone } from "@/components/ui/StatusPill";
import type { Hypothesis, OptimizationCandidate } from "@/lib/api/types";
import {
  candidateContext,
  decisionFor,
  DECLINE_ALL,
  expiryText,
  formatBytes,
  statements,
  STATUS_LABEL,
  type ApprovalCandidate,
  type ReviewPhase,
} from "@/lib/approval/review";
import { describeCandidate } from "@/lib/benchmark/candidate";
import type { ApprovalDecision } from "./useApprovalDecision";
import { VerdictBadge } from "./VerdictBadge";

const STATUS_TONE: Record<string, Tone> = {
  pending: "approval",
  approved: "success",
  partially_approved: "success",
  declined: "neutral",
  expired: "warning",
  refused: "failed",
};

// Candidate statuses that mean an experiment has started or produced a verdict.
const MEASURED = new Set(["benchmarked", "verified", "verified_with_noise_warning", "rejected", "inconclusive"]);

/** Copies text exactly as given; says so (or that it failed) in a polite live region. */
function CopyButton({ text, label }: { text: string; label: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  useEffect(() => {
    if (state === "idle") return;
    const t = setTimeout(() => setState("idle"), 2000);
    return () => clearTimeout(t);
  }, [state]);
  const copy = () => {
    if (!navigator.clipboard) return setState("failed");
    navigator.clipboard.writeText(text).then(
      () => setState("copied"),
      () => setState("failed"),
    );
  };
  return (
    <span className="inline-flex items-center gap-1.5">
      <span aria-live="polite" className="text-[11px] text-muted">
        {state === "copied" ? "Copied" : state === "failed" ? "Copy failed: select the text instead" : ""}
      </span>
      <button type="button" aria-label={label} onClick={copy} className="qc-btn-ghost qc-btn-sm h-7 gap-1 px-2 text-xs pointer-coarse:h-10">
        <Icon name="copy" size={13} />
        Copy
      </button>
    </span>
  );
}

/** SQL shown verbatim; long statements scroll inside a focusable region, never the page. */
function SqlBlock({ label, sql, name }: { label: string; sql: string; name: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <div className="flex items-center justify-between gap-2">
        <span className="qc-eyebrow text-[11px]">{label}</span>
        <CopyButton text={sql} label={`Copy ${name}`} />
      </div>
      <pre
        tabIndex={0}
        role="region"
        aria-label={name}
        className="max-h-72 overflow-auto rounded-md border border-border bg-bg px-3 py-2 font-mono text-[13px] leading-5 whitespace-pre-wrap text-ink [overflow-wrap:anywhere]"
      >
        {sql}
      </pre>
    </div>
  );
}

function Section({ title, children, note }: { title: string; children: ReactNode; note?: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <h4 className="qc-eyebrow text-[11px]">
        {title}
        {note ? <span className="ml-1.5 tracking-normal normal-case">· {note}</span> : null}
      </h4>
      {children}
    </div>
  );
}

function HypothesisItem({ hKey, hypothesis, onEvidence }: { hKey: string; hypothesis: Hypothesis | null; onEvidence: (id: string) => void }) {
  if (!hypothesis) {
    return (
      <li className="text-xs text-muted">
        <span className="font-mono">{hKey}</span> · not loaded for this run
      </li>
    );
  }
  return (
    <li className="flex min-w-0 flex-col gap-1 rounded-md border border-dashed border-border-strong px-2.5 py-2">
      <span className="font-mono text-[11px] text-muted">
        {hKey} · rank {hypothesis.rank} · {hypothesis.confidence} confidence · unverified
      </span>
      <span className="text-sm break-words">{hypothesis.statement}</span>
      {hypothesis.supportingEvidence.length ? (
        <span className="flex flex-wrap items-center gap-1 text-[11px] text-muted">
          Supporting evidence
          {hypothesis.supportingEvidence.map((id) => (
            <EvidenceChip key={id} id={id} onOpen={onEvidence} />
          ))}
        </span>
      ) : null}
      {hypothesis.contradictingEvidence.length ? (
        <span className="flex flex-wrap items-center gap-1 text-[11px] text-rejected">
          Contradicting evidence
          {hypothesis.contradictingEvidence.map((id) => (
            <EvidenceChip key={id} id={id} onOpen={onEvidence} />
          ))}
        </span>
      ) : null}
    </li>
  );
}

function CandidateCard({
  c,
  review,
  records,
  hypotheses,
  onEvidence,
}: {
  c: ApprovalCandidate;
  review: ApprovalDecision;
  records: OptimizationCandidate[];
  hypotheses: Hypothesis[];
  onEvidence: (id: string) => void;
}) {
  const ctx = candidateContext(c, records, hypotheses);
  const name = describeCandidate({ kind: c.kind, ddl: c.ddl, querySql: c.querySql });
  const pending = review.phase.kind === "pending";
  const checked = review.chosen.has(c.candidateId);
  const decided = review.mine?.approval ?? review.approval;
  const included = decided.approvedCandidateIds.includes(c.candidateId);
  const status = ctx.record?.status;
  const headingId = useId();
  return (
    <article
      aria-labelledby={headingId}
      className={`flex min-w-0 flex-col gap-3 rounded-lg border p-3.5 bg-surface ${pending && checked ? "border-accent/70 shadow-[inset_3px_0_0_var(--accent)]" : "border-border"}`}
    >
      <header className="flex min-w-0 items-start gap-2.5">
        {pending ? (
          <input
            type="checkbox"
            checked={checked}
            onChange={() => review.toggle(c.candidateId)}
            disabled={review.decide.isPending}
            aria-label={`Include ${name} (${c.key})`}
            className="mt-1 size-[18px] shrink-0 accent-[var(--accent)] pointer-coarse:size-6"
          />
        ) : null}
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <h3 id={headingId} className="text-[15px] leading-6 font-medium break-words">
            {name} <span className="font-mono text-xs font-normal text-muted">{c.key}</span>
          </h3>
          <span className="flex flex-wrap items-center gap-1.5">
            {status ? <VerdictBadge status={status} /> : null}
            {review.phase.kind === "decided" ? <span className="qc-tag h-5 text-[11px]">{included ? "included in the decision" : "not approved"}</span> : null}
          </span>
        </div>
      </header>

      {statements(c).map((s) => (
        <SqlBlock key={s.label} label={s.label} sql={s.sql} name={`${s.label.toLowerCase()} · ${c.key}`} />
      ))}

      <div className="flex min-w-0 flex-col gap-1">
        <div className="flex items-center justify-between gap-2">
          <span className="qc-eyebrow text-[11px]">SQL SHA-256</span>
          <CopyButton text={c.sqlSha256} label={`Copy SQL SHA-256 · ${c.key}`} />
        </div>
        <code className="font-mono text-xs break-all text-ink">{c.sqlSha256}</code>
        <span className="text-[11px] text-muted">
          Computed by the server over this candidate&apos;s statements, kind and query. The benchmark runs only SQL whose digest matches the one approved here.
        </span>
        {ctx.digestMatches === false ? (
          <p role="alert" className="rounded-md border border-rejected/40 px-2.5 py-1.5 text-xs text-rejected">
            The run&apos;s candidate record has a different digest ({ctx.record?.sqlSha256.slice(0, 12)}…). The SQL and digest above are the ones this request
            offers; the benchmark refuses SQL that differs from what is approved.
          </p>
        ) : null}
      </div>

      <Section title="Expected" note="proposed, not measured">
        <p className="text-sm break-words">{c.expectedBenefit}</p>
        {ctx.writeOverhead || ctx.indexSizeBytes !== null ? (
          <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-xs">
            {ctx.writeOverhead ? (
              <>
                <dt className="text-muted">Write overhead</dt>
                <dd>
                  <span className="font-mono">{ctx.writeOverhead}</span> <span className="text-muted">(proposer&apos;s estimate)</span>
                </dd>
              </>
            ) : null}
            {ctx.indexSizeBytes !== null ? (
              <>
                <dt className="text-muted">Index size</dt>
                <dd>
                  <span className="font-mono">≈ {formatBytes(ctx.indexSizeBytes)}</span> <span className="text-muted">(recorded estimate)</span>
                </dd>
              </>
            ) : null}
          </dl>
        ) : null}
      </Section>

      <Section title="Risks" note="as listed by the proposer">
        {c.risks.length ? (
          <ul className="list-disc pl-5 text-sm text-inconclusive">
            {c.risks.map((r) => (
              <li key={r} className="break-words">
                {r}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-muted">None listed. That is not a safety check.</p>
        )}
      </Section>

      {ctx.rollbackSql ? <SqlBlock label="Rollback (not run by QueryCure)" sql={ctx.rollbackSql} name={`rollback statement · ${c.key}`} /> : null}

      <Section title="Measured">
        <p className="text-xs text-muted">
          {status && MEASURED.has(status)
            ? "Sandbox results for this candidate are in the Tournament tab."
            : review.phase.kind === "decided" && !included
              ? "Not run: this candidate was not approved."
              : "Nothing measured yet. Timings exist only after an approved experiment runs; no speed-up is shown before then."}
        </p>
      </Section>

      <Section title="Supporting hypotheses">
        {ctx.record === null ? (
          <p className="text-xs text-muted">The run&apos;s candidate record is not loaded, so its hypotheses are not shown.</p>
        ) : ctx.hypotheses.length === 0 ? (
          <p className="text-xs text-muted">No hypothesis is linked to this candidate.</p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {ctx.hypotheses.map((h) => (
              <HypothesisItem key={h.key} hKey={h.key} hypothesis={h.hypothesis} onEvidence={onEvidence} />
            ))}
          </ul>
        )}
      </Section>
    </article>
  );
}

function PhaseNotice({ phase, review }: { phase: ReviewPhase; review: ApprovalDecision }) {
  if (phase.kind === "pending") return null;
  if (phase.kind === "refused") {
    // The server's own message is the alert in the footer; this says what it means here.
    return (
      <p className="flex gap-2 rounded-md border border-rejected/40 bg-rejected/8 px-3 py-2 text-sm">
        <Icon name="alert" size={15} className="mt-0.5 shrink-0 text-rejected" />
        <span>
          The server refused this decision. No decision was recorded and nothing ran in the sandbox. The request&apos;s expiry time is{" "}
          {new Date(review.approval.expiresAt).toLocaleString()}; its current status is being reloaded.
        </span>
      </p>
    );
  }
  if (phase.kind === "expired") {
    return (
      <p className="flex gap-2 rounded-md border border-inconclusive/40 bg-inconclusive/8 px-3 py-2 text-sm">
        <Icon name="alert" size={15} className="mt-0.5 shrink-0 text-inconclusive" />
        <span>
          This approval request expired at {new Date(review.approval.expiresAt).toLocaleString()}
          {phase.byClock ? " and can no longer be decided" : ""}. Nothing ran in the sandbox.
        </span>
      </p>
    );
  }
  const decided = review.mine?.approval ?? review.approval;
  const n = decided.approvedCandidateIds.length;
  const total = decided.payload.candidates.length;
  const what =
    decided.status === "declined"
      ? "Declined: nothing will run."
      : `${STATUS_LABEL[decided.status] ?? decided.status}: ${n} of ${total} candidate${total === 1 ? "" : "s"} will be benchmarked in the sandbox.`;
  const when = decided.decidedAt ? ` Decided ${new Date(decided.decidedAt).toLocaleString()}.` : "";
  return phase.outcome === "recorded" ? (
    <p className="flex gap-2 rounded-md border border-verified/40 bg-verified/8 px-3 py-2 text-sm">
      <Icon name="check" size={15} className="mt-0.5 shrink-0 text-verified" />
      <span>
        Decision recorded. {what}
        {when}
      </span>
    </p>
  ) : (
    <p className="flex gap-2 rounded-md border border-border-strong bg-surface-2 px-3 py-2 text-sm">
      <Icon name="alert" size={15} className="mt-0.5 shrink-0 text-muted" />
      <span>
        This request was already decided, so no new decision was recorded. {what}
        {when}
      </span>
    </p>
  );
}

/** Detailed review of one approval request (UI_UX §3.21): a right-side drawer on wide screens, a
 * bottom sheet on phones. Everything shown comes from the approval payload and the run's own
 * records; decisions go through the same endpoint and semantics as the inline card. */
export function ApprovalDrawer({
  review,
  investigationTitle,
  candidates,
  hypotheses,
  onClose,
  onEvidence,
}: {
  review: ApprovalDecision;
  investigationTitle: string;
  candidates: OptimizationCandidate[];
  hypotheses: Hypothesis[];
  onClose: () => void;
  onEvidence: (id: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const title = useRef<HTMLHeadingElement>(null);
  const titleId = useId();
  const descId = useId();
  useModal(ref, onClose);
  useEffect(() => {
    title.current?.focus();
    const body = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = body;
    };
  }, []);

  const { approval, phase, chosen, decide, submit, offered } = review;
  const p = approval.payload;
  const n = p.candidates.length;
  const shownStatus = phase.kind === "expired" ? "expired" : phase.kind === "refused" ? "refused" : (review.mine?.approval.status ?? approval.status);
  const heading =
    phase.kind === "pending"
      ? `Benchmark ${n === 1 ? "this change" : `${n} changes`} in a sandbox?`
      : phase.kind === "expired"
        ? "Approval request expired"
        : phase.kind === "refused"
          ? "Decision not recorded"
        : phase.outcome === "recorded"
          ? "Decision recorded"
          : "Already decided";
  const input = decisionFor(chosen, offered);
  const busy = decide.isPending;

  return (
    <div className="fixed inset-0 z-50 flex flex-col justify-end md:flex-row">
      <button type="button" aria-label="Close review" tabIndex={-1} onClick={onClose} className="absolute inset-0 bg-[var(--scrim)]" />
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descId}
        className="relative flex max-h-[92dvh] w-full min-w-0 flex-col rounded-t-xl border-t border-border-strong bg-sidebar pb-[env(safe-area-inset-bottom)] shadow-pop md:ml-auto md:h-full md:max-h-none md:w-[min(600px,100vw)] md:rounded-none md:border-t-0 md:border-l"
      >
        <span aria-hidden="true" className="mx-auto mt-2 h-1 w-10 shrink-0 rounded-full bg-border-strong md:hidden" />
        <header className="flex shrink-0 flex-col gap-1.5 border-b border-border px-4 pt-2 pb-3 md:px-6 md:pt-4">
          <div className="flex items-center gap-2">
            <StatusPill tone={STATUS_TONE[shownStatus] ?? "neutral"} label={shownStatus === "refused" ? "Not recorded" : (STATUS_LABEL[shownStatus] ?? shownStatus)} />
            {phase.kind === "pending" ? <span className="font-mono text-xs whitespace-nowrap text-inconclusive">{expiryText(approval.expiresAt, review.now)}</span> : null}
            <button type="button" onClick={onClose} aria-label="Close review" className="qc-btn-ghost ml-auto size-8 p-0 pointer-coarse:size-11">
              <Icon name="close" size={16} />
            </button>
          </div>
          <h2 ref={title} id={titleId} tabIndex={-1} className="text-lg leading-7 font-semibold outline-none md:text-xl">
            {heading}
          </h2>
          {/* One line: the full title and sandbox are in Request below. */}
          <p id={descId} className="truncate text-sm text-muted" title={`${investigationTitle} · round ${approval.round + 1} · runs only in ${p.sandbox}`}>
            Round {approval.round + 1} · {investigationTitle}
            <span className="sr-only"> · runs only in {p.sandbox}</span>
          </p>
        </header>

        <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto overscroll-contain px-4 py-4 md:px-6">
          <div aria-live="polite">
            <PhaseNotice phase={phase} review={review} />
          </div>

          <Section title="Request">
            <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-0.5 text-[13px] leading-5">
              <dt className="text-muted">Investigation</dt>
              <dd className="break-words">{investigationTitle}</dd>
              <dt className="text-muted">Run</dt>
              <dd className="font-mono text-xs break-all">{approval.runId}</dd>
              <dt className="text-muted">Workload</dt>
              <dd className="font-mono text-xs break-all">{p.workloadId}</dd>
              <dt className="text-muted">Sandbox</dt>
              <dd className="break-words">{p.sandbox}</dd>
              <dt className="text-muted">Parameter sets</dt>
              <dd>{p.paramSets.length}, timed with the baseline query</dd>
              <dt className="text-muted">Requested</dt>
              <dd>{new Date(approval.createdAt).toLocaleString()}</dd>
              <dt className="text-muted">Expires</dt>
              <dd>{new Date(approval.expiresAt).toLocaleString()}</dd>
              {approval.decidedAt ? (
                <>
                  <dt className="text-muted">Decided</dt>
                  <dd>{new Date(approval.decidedAt).toLocaleString()}</dd>
                </>
              ) : null}
            </dl>
            <details className="rounded-md border border-border bg-surface">
              <summary className="cursor-pointer px-3 py-2 text-sm text-muted hover:text-ink">Baseline query (measured alongside, unchanged)</summary>
              <div className="border-t border-border p-3">
                <SqlBlock label="Baseline query" sql={p.baselineQuery} name="baseline query" />
              </div>
            </details>
          </Section>

          <section aria-label="Candidates" className="flex min-w-0 flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="qc-eyebrow text-[11px]">Candidates · {n}</h3>
              {phase.kind === "pending" && n > 1 ? (
                <span className="ml-auto flex gap-1">
                  <button type="button" disabled={busy} onClick={() => review.setAll(true)} className="qc-btn-ghost qc-btn-sm pointer-coarse:h-10">
                    Select all
                  </button>
                  <button type="button" disabled={busy} onClick={() => review.setAll(false)} className="qc-btn-ghost qc-btn-sm pointer-coarse:h-10">
                    Select none
                  </button>
                </span>
              ) : null}
            </div>
            {p.candidates.map((c) => (
              <CandidateCard key={c.candidateId} c={c} review={review} records={candidates} hypotheses={hypotheses} onEvidence={onEvidence} />
            ))}
          </section>

          <Section title="If you approve">
            <ol className="list-decimal space-y-1 pl-5 text-sm">
              <li>Only the statements shown for the selected candidates run, in a disposable clone in {p.sandbox}.</li>
              <li>The benchmark checks each candidate against the digest approved here and refuses SQL that differs.</li>
              <li>The baseline query and {p.paramSets.length} parameter set(s) are timed alongside each candidate.</li>
              <li>If the measurements are too noisy to decide, the same approved SQL may be re-measured up to two more times in new disposable clones.</li>
              <li>Verdicts come from the deterministic benchmark; the auditor can only downgrade them. They hold only for the tested data, parameters and sandbox.</li>
            </ol>
          </Section>
        </div>

        <footer className="flex shrink-0 flex-col gap-2 border-t border-border px-4 py-3 md:px-6">
          <ErrorNotice error={decide.error} />
          {phase.kind === "pending" ? (
            <div className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-2 sm:flex">
              <button type="button" disabled={busy} onClick={() => submit(DECLINE_ALL)} className="qc-btn-danger pointer-coarse:h-11">
                Decline all
              </button>
              <span className="order-first col-span-2 font-mono text-xs text-muted sm:order-none sm:ml-auto" aria-live="polite">
                {chosen.size} of {n} selected
              </span>
              <button
                type="button"
                disabled={busy || input === null}
                aria-busy={busy}
                onClick={() => {
                  if (input) submit(input);
                }}
                className="qc-btn-primary pointer-coarse:h-11"
              >
                {busy ? <Icon name="loader" size={14} className="animate-spin motion-reduce:animate-none" /> : null}
                {busy ? "Recording decision…" : "Approve selected"}
              </button>
            </div>
          ) : (
            <div className="flex justify-end">
              <button type="button" onClick={onClose} className="qc-btn-secondary pointer-coarse:h-11">
                Close
              </button>
            </div>
          )}
        </footer>
      </div>
    </div>
  );
}
