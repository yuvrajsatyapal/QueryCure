"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { ErrorNotice } from "@/components/common/ErrorNotice";
import { VerdictBadge } from "@/components/tournament/VerdictBadge";
import { demoKeys, getDemoGallery } from "@/lib/api/demo";
import type { DemoBenchmark } from "@/lib/api/types";
import { PrerecordedBanner } from "./PrerecordedBanner";
import { Icon } from "@/components/ui/Icon";
import { StatusPill, type Tone } from "@/components/ui/StatusPill";

const OUTCOME: Record<string, { label: string; tone: Tone }> = {
  verified_recommendation: { label: "verified recommendation", tone: "success" },
  unverified_recommendations: { label: "unverified recommendations (no benchmark)", tone: "neutral" },
  no_action_needed: { label: "no action needed", tone: "neutral" },
  inconclusive: { label: "inconclusive", tone: "warning" },
};

/** Always on the card, so a prerecorded case can never read as a live result. */
function PrerecordedTag() {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-inconclusive/40 bg-inconclusive/10 px-2 py-px text-[11px] font-medium text-inconclusive">
      <Icon name="replay" size={11} />
      Prerecorded
    </span>
  );
}

function BenchmarkCard({ b }: { b: DemoBenchmark }) {
  return (
    <li className="flex min-w-0 flex-col gap-3 qc-panel p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-mono text-xs text-muted">
          {b.workloadId} · {b.engineVersion}
        </p>
        <PrerecordedTag />
      </div>
      {b.arms.map((arm) => (
        <div key={arm.arm} className="flex min-w-0 flex-col gap-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <VerdictBadge status={arm.verdict} />
            <span className="text-sm">{arm.kind.replaceAll("_", " ")}</span>
            {arm.reasons[0] ? <span className="font-mono text-[11px] text-muted">({arm.reasons[0].code})</span> : null}
          </div>
          <pre tabIndex={0} className="overflow-x-auto rounded-md border border-border bg-surface-2 p-2 font-mono text-xs">
            {(arm.ddl.length ? arm.ddl : [arm.query ?? ""]).join(";\n")}
          </pre>
        </div>
      ))}
      {b.stats.length ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[420px] text-left text-xs">
            <caption className="sr-only">Recorded medians and speed-up per parameter set</caption>
            <thead className="text-[11px] text-muted">
              <tr>
                <th className="py-1 pr-2 font-medium">Param set</th>
                <th className="py-1 pr-2 text-right font-medium">Baseline</th>
                <th className="py-1 pr-2 text-right font-medium">Candidate</th>
                <th className="py-1 pr-2 text-right font-medium">Speed-up (95% CI)</th>
                <th className="py-1 text-right font-medium">n</th>
              </tr>
            </thead>
            <tbody className="font-mono tabular-nums">
              {b.stats.map((st) => (
                <tr key={`${st.arm}:${st.paramSet}`} className="border-t border-border">
                  <td className="py-1 pr-2">{st.paramSet}</td>
                  <td className="py-1 pr-2 text-right">{st.baselineMedianMs} ms</td>
                  <td className="py-1 pr-2 text-right">{st.candidateMedianMs} ms</td>
                  <td className="py-1 pr-2 text-right">
                    {st.speedup}× <span className="text-muted">({st.ciLow}–{st.ciHigh}×)</span>
                  </td>
                  <td className="py-1 text-right">{st.n}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <p className="border-t border-border pt-2 text-xs text-muted">{b.label}</p>
    </li>
  );
}

export function DemoGalleryView() {
  const gallery = useQuery({ queryKey: demoKeys.gallery, queryFn: ({ signal }) => getDemoGallery(signal) });
  if (gallery.error) return <ErrorNotice error={gallery.error} />;
  if (!gallery.data) return <p className="text-muted">Loading the demo gallery…</p>;
  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <p className="qc-eyebrow">Demo gallery</p>
        <h1 className="text-xl font-semibold tracking-tight">Prerecorded investigations</h1>
        <p className="max-w-3xl text-sm text-muted">
          Each entry is a sealed run replayed from stored records: real answers recorded from a free model, and (for sandbox runs) real
          measurements recorded on the machine named in the label. Nothing runs when you open them, and none of it describes your database.
          Your own investigations live in the app, never here.
        </p>
      </header>
      <section aria-label="Investigations" className="flex flex-col gap-3">
        <h2 className="font-medium">Investigations</h2>
        <ul className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {gallery.data.items.map((item) => (
            <li key={item.slug} className="qc-panel flex min-w-0 flex-col gap-3 p-4 hover:border-border-strong">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <Link href={`/demo/${item.slug}`} className="font-medium text-ink hover:underline">
                  {item.title}
                </Link>
                {item.outcome && OUTCOME[item.outcome] ? (
                  <StatusPill tone={OUTCOME[item.outcome]!.tone} label={OUTCOME[item.outcome]!.label} />
                ) : (
                  <span className="text-xs text-muted">{item.outcome ?? "—"}</span>
                )}
              </div>
              <p className="text-sm">{item.headline}</p>
              <details className="text-sm text-muted">
                <summary className="cursor-pointer hover:text-ink">What this case tests</summary>
                <p className="mt-1">{item.summary}</p>
              </details>
              <div className="mt-auto flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-border pt-3 text-[11px] text-muted">
                <PrerecordedTag />
                <span className="font-mono">{item.model}</span>
                <span>· {item.recordedAt}</span>
                <span>{item.measurementsRecordedOn ? `· measured ${item.measurementsRecordedOn}` : "· no benchmark"}</span>
              </div>
            </li>
          ))}
        </ul>
      </section>
      <section aria-label="Benchmark verdicts" className="flex flex-col gap-3">
        <h2 className="font-medium">Benchmark verdicts (prerecorded experiments)</h2>
        <PrerecordedBanner label="Deterministic verdicts from real sandbox experiments recorded on the hardware named in each card. Not your database." />
        <ul className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {gallery.data.benchmarks.map((b) => (
            <BenchmarkCard key={b.id} b={b} />
          ))}
        </ul>
        <p className="text-xs text-muted">
          No prerecorded experiment currently ends in “verified with noise warning” (that needs three agreeing experiments); it is shown when a
          recorded run has one.
        </p>
      </section>
    </div>
  );
}
