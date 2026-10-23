import { FASTER_IS_NOT_VERIFIED, STATS_GLOSSARY } from "@/lib/benchmark/glossary";

/** "How to read these numbers": closed by default so the measurements stay first. */
export function StatsGlossary() {
  return (
    <details className="rounded-md border border-border bg-surface p-3 text-sm">
      <summary className="cursor-pointer font-medium select-none">How to read these numbers</summary>
      <dl className="mt-3 grid grid-cols-1 gap-x-4 gap-y-2 sm:grid-cols-[11rem_minmax(0,1fr)]">
        {STATS_GLOSSARY.map((e) => (
          <div key={e.term} className="contents">
            <dt className="font-medium">{e.term}</dt>
            <dd className="text-muted">{e.text}</dd>
          </div>
        ))}
      </dl>
      <p role="note" className="mt-3 border-l-2 border-inconclusive/60 pl-3 text-muted">
        {FASTER_IS_NOT_VERIFIED}
      </p>
    </details>
  );
}
