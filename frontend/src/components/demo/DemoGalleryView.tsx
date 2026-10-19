"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { ErrorNotice } from "@/components/common/ErrorNotice";
import { VerdictBadge } from "@/components/tournament/VerdictBadge";
import { demoKeys, getDemoGallery } from "@/lib/api/demo";
import type { DemoBenchmark } from "@/lib/api/types";
import { PrerecordedBanner } from "./PrerecordedBanner";

const OUTCOME: Record<string, string> = {
  verified_recommendation: "verified recommendation",
  unverified_recommendations: "unverified recommendations (no benchmark)",
  no_action_needed: "no action needed",
  inconclusive: "inconclusive",
};

function BenchmarkCard({ b }: { b: DemoBenchmark }) {
  return (
    <li className="flex min-w-0 flex-col gap-2 qc-panel p-4">
      <p className="font-mono text-xs text-muted">{b.workloadId} · {b.engineVersion}</p>
      {b.arms.map((arm) => (
        <div key={arm.arm} className="flex min-w-0 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <VerdictBadge status={arm.verdict} />
            <span className="text-sm">{arm.kind.replaceAll("_", " ")}</span>
            {arm.reasons[0] ? <span className="text-xs text-muted">({arm.reasons[0].code})</span> : null}
          </div>
          <pre tabIndex={0} className="overflow-x-auto rounded bg-surface-2 p-2 font-mono text-xs">{(arm.ddl.length ? arm.ddl : [arm.query ?? ""]).join(";\n")}</pre>
        </div>
      ))}
      <ul className="text-xs text-muted">
        {b.stats.map((s) => (
          <li key={`${s.arm}:${s.paramSet}`}>
            {s.paramSet}: {s.baselineMedianMs} ms → {s.candidateMedianMs} ms, speed-up {s.speedup}× (95% CI {s.ciLow}–{s.ciHigh}×, n={s.n})
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted">{b.label}</p>
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
        <h1 className="text-2xl font-semibold">Prerecorded investigations</h1>
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
            <li key={item.slug} className="flex min-w-0 flex-col gap-2 qc-panel p-4">
              <Link href={`/demo/${item.slug}`} className="font-medium text-link">
                {item.title}
              </Link>
              <p className="text-sm">Outcome: {OUTCOME[item.outcome ?? ""] ?? item.outcome ?? "—"}</p>
              <p className="text-sm">{item.headline}</p>
              <details className="text-sm text-muted">
                <summary className="cursor-pointer">What this case tests</summary>
                <p className="mt-1">{item.summary}</p>
              </details>
              <p className="font-mono text-[11px] text-muted">
                prerecorded · {item.model} · {item.recordedAt}
                {item.measurementsRecordedOn ? ` · measured ${item.measurementsRecordedOn}` : " · no benchmark"}
              </p>
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
