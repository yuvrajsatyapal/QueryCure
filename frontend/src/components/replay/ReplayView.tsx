"use client";

import { manifestModelRows } from "@/lib/replay/manifestModels";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ErrorNotice } from "@/components/common/ErrorNotice";
import { ApiError } from "@/lib/api/client";
import { getRun, investigationKeys } from "@/lib/api/investigations";
import { getExperiment, getExperiments, optimizationKeys } from "@/lib/api/optimization";
import {
  cancelReplayAttempt,
  getManifest,
  listReplayAttempts,
  reinvestigate,
  replayExperiment,
  reportKeys,
  verifyReport,
} from "@/lib/api/reports";
import type { ExperimentSummary, ReplayAttempt } from "@/lib/api/types";
import {
  ACTIVE_REPLAY,
  REPLAY_CODE_TEXT,
  REPORT_REPLAY_STATUS,
  experimentReplayLabel,
  ms,
  x,
} from "@/lib/report/labels";
import type { Comparison, ReplayPair } from "@/lib/report/types";

const STATUS_TONE: Record<string, string> = {
  verified: "border-verified text-verified",
  verified_stored_only: "border-verified text-verified",
  reproduced: "border-verified text-verified",
  reproduced_with_drift: "border-inconclusive text-inconclusive",
  inconclusive: "border-inconclusive text-inconclusive",
  not_reproduced: "border-rejected text-rejected",
  integrity_failed: "border-rejected text-rejected",
  not_replayable: "border-border-strong text-muted",
  failed: "border-rejected text-rejected",
  error: "border-rejected text-rejected",
  cancelled: "border-border-strong text-muted",
};

export function attemptLabel(a: Pick<ReplayAttempt, "kind" | "status" | "result">): string {
  if (a.kind === "report") return REPORT_REPLAY_STATUS[a.status] ?? a.status;
  const mode = (a.result as { comparisonMode?: string }).comparisonMode;
  return experimentReplayLabel(a.status, mode);
}

export function StatusBadge({ attempt }: { attempt: Pick<ReplayAttempt, "kind" | "status" | "result"> }) {
  return (
    <span className={`inline-flex rounded border px-1.5 py-0.5 font-mono text-[11px] ${STATUS_TONE[attempt.status] ?? "border-border text-muted"}`}>
      {attemptLabel(attempt)}
    </span>
  );
}

/** Drift interval on a log axis against the equivalence band [1/m, m] (REPLAY_ENGINE §9.1). */
export function DriftBar({ pair, margin }: { pair: ReplayPair; margin: number }) {
  if (pair.driftCiLow === null || pair.driftCiHigh === null || pair.drift === null) return <span className="text-xs text-muted">n/a</span>;
  const span = Math.log(4);
  const pos = (v: number) => `${((Math.log(Math.min(Math.max(v, 0.25), 4)) + span) / (2 * span)) * 100}%`;
  return (
    <div className="relative h-3 w-full min-w-24 rounded bg-surface-2" role="img"
      aria-label={`drift ${pair.drift.toFixed(2)}, interval ${pair.driftCiLow.toFixed(2)} to ${pair.driftCiHigh.toFixed(2)}, band ${(1 / margin).toFixed(2)} to ${margin.toFixed(2)}`}>
      <div className="absolute inset-y-0 bg-verified/20" style={{ left: pos(1 / margin), width: `calc(${pos(margin)} - ${pos(1 / margin)})` }} />
      <div className="absolute inset-y-0.5 rounded bg-accent/60" style={{ left: pos(pair.driftCiLow), width: `calc(${pos(pair.driftCiHigh)} - ${pos(pair.driftCiLow)})` }} />
      <div className="absolute inset-y-0 w-0.5 bg-ink" style={{ left: pos(pair.drift) }} />
    </div>
  );
}

export function ComparisonView({ comparison, replayRunId }: { comparison: Comparison; replayRunId: string | null }) {
  const cross = comparison.comparisonMode === "cross_environment";
  return (
    <section aria-label="Replay comparison" className="flex flex-col gap-3">
      {cross ? (
        <p role="note" className="rounded-md border border-inconclusive p-2 text-sm text-inconclusive">
          Different environment: ratios may not transfer; absolute latencies are not comparable. This is a cross-environment comparison, not a reproduction.
        </p>
      ) : null}
      <p className="text-sm">
        <span className="font-medium">{experimentReplayLabel(comparison.status, comparison.comparisonMode)}</span>
        {comparison.failureCode ? <span className="text-muted"> · {REPLAY_CODE_TEXT[comparison.failureCode] ?? comparison.failureCode}</span> : null}
        <span className="text-muted"> · margin {comparison.config.margin}, {comparison.config.resamples} resamples</span>
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-sm">
          <caption className="pb-1 text-left text-xs text-muted">
            Per candidate and parameter set. Drift = replay speed-up ÷ original speed-up; the shaded band is the equivalence margin.
          </caption>
          <thead className="font-mono text-[11px] uppercase text-muted">
            <tr>
              <th className="py-1 pr-2">Pair</th>
              <th className="py-1 pr-2">Verdicts</th>
              <th className="py-1 pr-2">Speed-up</th>
              <th className="w-40 py-1 pr-2">Drift</th>
              <th className="py-1">Result</th>
            </tr>
          </thead>
          <tbody>
            {comparison.pairs.map((p) => (
              <tr key={`${p.arm}:${p.paramSet}`} className="border-t border-border align-top">
                <td className="py-1 pr-2 font-mono text-xs">
                  {p.arm}
                  <br />
                  {p.paramSet}
                </td>
                <td className="py-1 pr-2 text-xs">
                  {p.originalVerdict ?? "—"} → {p.replayVerdict ?? "—"}
                </td>
                <td className="py-1 pr-2 text-xs">
                  {x(p.originalSpeedup)} → {x(p.replaySpeedup)}
                </td>
                <td className="py-1 pr-2">
                  <DriftBar pair={p} margin={comparison.config.margin} />
                  {p.drift !== null ? (
                    <span className="font-mono text-[11px] text-muted">
                      {p.drift.toFixed(2)} [{p.driftCiLow?.toFixed(2)}, {p.driftCiHigh?.toFixed(2)}]
                    </span>
                  ) : null}
                </td>
                <td className="py-1 text-xs">
                  {experimentReplayLabel(p.status, comparison.comparisonMode)}
                  {p.code ? <span className="block text-muted">{REPLAY_CODE_TEXT[p.code] ?? p.code}</span> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <details className="text-sm">
        <summary className="cursor-pointer">Absolute latencies (not used for classification)</summary>
        <ul className="mt-1 font-mono text-xs">
          {comparison.pairs.map((p) => (
            <li key={`${p.arm}:${p.paramSet}:abs`}>
              {p.arm} · {p.paramSet}: original {ms(p.originalMediansNs?.[0])} / {ms(p.originalMediansNs?.[1])}, replay {ms(p.replayMediansNs?.[0])} /{" "}
              {ms(p.replayMediansNs?.[1])} (baseline / candidate medians)
            </li>
          ))}
        </ul>
      </details>
      <section aria-label="Environment differences" className="text-sm">
        <h3 className="font-semibold">Environment differences</h3>
        {comparison.environment.differences.length === 0 ? (
          <p className="text-muted">None: same recorded environment.</p>
        ) : (
          <ul className="font-mono text-xs">
            {comparison.environment.differences.map((d) => (
              <li key={d.field}>
                [{d.class}] {d.field}: {String(d.original)} → {String(d.replay)}
              </li>
            ))}
          </ul>
        )}
      </section>
      <ul className="list-disc pl-5 text-xs text-muted">
        {comparison.limitations.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
      {replayRunId ? (
        <Link className="text-sm text-link" href={`/app/reports/${replayRunId}`}>
          Open the replay run&apos;s report
        </Link>
      ) : null}
    </section>
  );
}

export function ReplayConfirm({ experiment, runId, onDone }: { experiment: ExperimentSummary; runId: string; onDone: () => void }) {
  const client = useQueryClient();
  const detail = useQuery({ queryKey: optimizationKeys.experiment(experiment.id), queryFn: ({ signal }) => getExperiment(experiment.id, signal) });
  // One key per opened confirmation: retries after a timeout or a double click reuse it.
  const [idemKey] = useState(() => crypto.randomUUID());
  const start = useMutation({
    mutationFn: () => replayExperiment(experiment.id, idemKey),
    onSettled: () => void client.invalidateQueries({ queryKey: reportKeys.attempts(runId) }),
    onSuccess: () => onDone(),
  });
  const arms = ((detail.data?.config as { candidates?: { arm: string; ddl: string[]; query: string | null }[] } | null)?.candidates ?? []);
  const apiError = start.error instanceof ApiError ? start.error : null;
  const notReplayable = apiError?.code === "EXPERIMENT_NOT_REPLAYABLE";
  const code = notReplayable ? (apiError?.details[0] as { code?: string } | undefined)?.code : undefined;
  return (
    <div role="dialog" aria-label="Confirm experiment replay" className="flex flex-col gap-2 rounded-md border border-accent bg-surface p-3 text-sm">
      <p className="font-medium">Re-run this experiment in a fresh sandbox?</p>
      <p className="text-muted">
        The exact SQL below runs again in disposable clones of the demo database, with the same configuration and seed. No model is called; nothing touches
        your database. Confirming approves exactly this SQL for the replay.
      </p>
      {arms.map((a) => (
        <pre key={a.arm} tabIndex={0} className="overflow-x-auto rounded border border-border bg-surface-2 p-2 font-mono text-xs">
          {a.arm}: {(a.ddl.length ? a.ddl : a.query ? [a.query] : []).join(";\n")}
        </pre>
      ))}
      {notReplayable ? (
        <p role="alert" className="text-rejected">
          Not replayable: {code ? REPLAY_CODE_TEXT[code] ?? code : apiError?.message}
        </p>
      ) : (
        <ErrorNotice error={start.error} />
      )}
      <div className="flex gap-2">
        <button type="button" disabled={start.isPending || arms.length === 0} onClick={() => start.mutate()}
          className="rounded-md bg-accent px-3 py-1 text-accent-fg">
          {start.isPending ? "Starting…" : "Confirm and re-run"}
        </button>
        <button type="button" onClick={onDone} className="rounded-md border border-border px-3 py-1">
          Close
        </button>
      </div>
    </div>
  );
}

export function ReplayView({ runId }: { runId: string }) {
  const client = useQueryClient();
  const router = useRouter();
  const run = useQuery({ queryKey: investigationKeys.run(runId), queryFn: ({ signal }) => getRun(runId, signal) });
  const manifest = useQuery({ queryKey: reportKeys.manifest(runId), queryFn: ({ signal }) => getManifest(runId, signal), retry: false });
  const experiments = useQuery({ queryKey: optimizationKeys.experiments(runId), queryFn: ({ signal }) => getExperiments(runId, signal) });
  const attempts = useQuery({
    queryKey: [...reportKeys.attempts(runId)],
    queryFn: ({ signal }) => listReplayAttempts(runId, signal),
    refetchInterval: (q) => ((q.state.data?.items ?? []).some((a) => ACTIVE_REPLAY.has(a.status)) ? 2000 : false),
  });
  const verify = useMutation({ mutationFn: () => verifyReport(runId), onSuccess: () => void client.invalidateQueries({ queryKey: reportKeys.attempts(runId) }) });
  const cancel = useMutation({ mutationFn: (id: string) => cancelReplayAttempt(id), onSuccess: () => void client.invalidateQueries({ queryKey: reportKeys.attempts(runId) }) });
  const [confirming, setConfirming] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [consent, setConsent] = useState(false);
  const [idemKey] = useState(() => crypto.randomUUID());
  const again = useMutation({
    mutationFn: () => reinvestigate(run.data?.investigationId ?? "", idemKey),
    onSuccess: (r) => router.push(`/app/investigations/${r.investigation.id}`),
  });

  const m = manifest.data?.manifest as Record<string, unknown> | undefined;
  const replayable = (experiments.data?.items ?? []).filter((e) => e.status === "completed");
  const items = attempts.data?.items ?? [];

  return (
    <div className="flex max-w-5xl flex-col gap-6">
      <header>
        <p className="font-mono text-xs uppercase tracking-wider text-muted">Reproducibility & replay</p>
        <h1 className="text-2xl font-semibold">Run {run.data?.runNumber ?? "…"}</h1>
        <p className="text-sm text-muted">
          Report replay checks stored evidence against stored digests (no model calls, no SQL). Experiment replay re-measures in a fresh sandbox (no model
          calls). Re-investigation is a new model run.
        </p>
        {run.data ? (
          <Link className="text-sm text-link" href={`/app/investigations/${run.data.investigationId}`}>
            Back to the investigation
          </Link>
        ) : null}
      </header>

      <section aria-label="Manifest" className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-4">
        <h2 className="text-lg font-semibold">Manifest</h2>
        {manifest.error instanceof ApiError && manifest.error.code === "NOT_FINALIZED" ? (
          <p className="text-sm text-muted">{REPLAY_CODE_TEXT.not_finalized}</p>
        ) : null}
        {m ? (
          <dl className="grid grid-cols-1 gap-x-4 gap-y-1 text-xs sm:grid-cols-[180px_1fr]">
            <dt className="text-muted">Manifest digest</dt>
            <dd className="break-all font-mono">sha256:{manifest.data?.manifestSha256}</dd>
            <dt className="text-muted">Final status</dt>
            <dd>{String(m.finalStatus)}{m.outcome ? ` · ${String(m.outcome)}` : ""}</dd>
            <dt className="text-muted">Events</dt>
            <dd className="break-all font-mono">
              1..{String((m.events as { cutoffSeq: number }).cutoffSeq)} · {String((m.events as { digest: string }).digest)}
            </dd>
            <dt className="text-muted">Report</dt>
            <dd className="font-mono">
              {String((m.report as { builderVersion: string }).builderVersion)} · {String((m.report as { mdRendererVersion: string }).mdRendererVersion)}
            </dd>
            <dt className="text-muted">Inputs</dt>
            <dd className="break-all font-mono">
              {Object.entries((m.inputs as Record<string, unknown>) ?? {})
                .filter(([, v]) => v)
                .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : String(v)}`)
                .join(" · ")}
            </dd>
            <dt className="text-muted">Models</dt>
            <dd>
              {manifestModelRows(m.llm).map((c) => (
                <span key={c.key} className="mr-2 font-mono">
                  {c.agent} {c.model} {c.promptVersion} ×{c.calls}
                </span>
              ))}
              {manifestModelRows(m.llm).length === 0 ? "none" : null}
            </dd>
            <dt className="text-muted">App</dt>
            <dd className="font-mono">
              {Object.entries((m.app as Record<string, unknown>) ?? {})
                .map(([k, v]) => `${k} ${String(v)}`)
                .join(" · ")}
            </dd>
          </dl>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={() => verify.mutate()} disabled={verify.isPending} className="rounded-md border border-accent px-3 py-1 text-sm text-accent">
            {verify.isPending ? "Verifying…" : "Verify & replay report"}
          </button>
        </div>
        {verify.data ? (
          <p className="text-sm">
            <StatusBadge attempt={verify.data} />{" "}
            {verify.data.failureCode ? REPLAY_CODE_TEXT[verify.data.failureCode] ?? verify.data.failureCode : null}
          </p>
        ) : null}
        <ErrorNotice error={verify.error} />
      </section>

      <section aria-label="Experiments" className="flex flex-col gap-2">
        <h2 className="text-lg font-semibold">Re-run an experiment</h2>
        {replayable.length === 0 ? <p className="text-sm text-muted">This run has no completed sandbox experiment to replay.</p> : null}
        <ul className="flex flex-col gap-2">
          {replayable.map((e) => (
            <li key={e.id} className="flex flex-col gap-2 rounded-md border border-border p-3 text-sm">
              <p>
                Round {e.round + 1}
                {e.replicate > 0 ? ` · replicate ${e.replicate}` : ""} · <span className="font-mono text-xs">{e.id.slice(0, 8)}</span> · {e.engineVersion}
              </p>
              {confirming === e.id ? (
                <ReplayConfirm experiment={e} runId={runId} onDone={() => setConfirming(null)} />
              ) : (
                <button type="button" onClick={() => setConfirming(e.id)} className="self-start rounded-md border border-border-strong px-3 py-1">
                  Re-run experiment…
                </button>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section aria-label="Replay history" className="flex flex-col gap-2">
        <h2 className="text-lg font-semibold">Replay history</h2>
        {items.length === 0 ? <p className="text-sm text-muted">No replays yet.</p> : null}
        <ul className="flex flex-col gap-2">
          {items.map((a) => {
            const comparison = (a.result as Partial<Comparison>).pairs ? (a.result as unknown as Comparison) : null;
            return (
              <li key={a.id} className="flex flex-col gap-2 rounded-md border border-border p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs">{a.kind}</span>
                  <StatusBadge attempt={a} />
                  {a.failureCode ? <span className="text-xs text-muted">{REPLAY_CODE_TEXT[a.failureCode] ?? a.failureCode}</span> : null}
                  <time className="font-mono text-[11px] text-muted" dateTime={a.createdAt}>
                    {new Date(a.createdAt).toLocaleString()}
                  </time>
                  {ACTIVE_REPLAY.has(a.status) ? (
                    <button type="button" onClick={() => cancel.mutate(a.id)} className="rounded-md border border-rejected px-2 py-0.5 text-xs text-rejected">
                      Cancel
                    </button>
                  ) : null}
                  {comparison ? (
                    <button type="button" onClick={() => setOpen(open === a.id ? null : a.id)} className="text-xs text-link">
                      {open === a.id ? "Hide comparison" : "Show comparison"}
                    </button>
                  ) : null}
                </div>
                {open === a.id && comparison ? <ComparisonView comparison={comparison} replayRunId={a.replayRunId} /> : null}
              </li>
            );
          })}
        </ul>
        <ErrorNotice error={cancel.error} />
      </section>

      <section aria-label="Re-investigate" className="flex flex-col gap-2 rounded-lg border border-dashed border-border-strong p-4">
        <h2 className="text-lg font-semibold">Re-investigate</h2>
        <p className="text-sm text-muted">
          Starts a new investigation run on the same inputs with new model calls (free models only), its own budget and provenance. Replays never do this.
        </p>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />I understand this makes new model calls.
        </label>
        <button type="button" disabled={!consent || again.isPending || !run.data} onClick={() => again.mutate()}
          className="self-start rounded-md border border-border-strong px-3 py-1 text-sm">
          {again.isPending ? "Starting…" : "Start re-investigation"}
        </button>
        <ErrorNotice error={again.error} />
      </section>
    </div>
  );
}
