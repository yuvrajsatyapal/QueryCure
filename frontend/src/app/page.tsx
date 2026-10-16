import Link from "next/link";

const STEPS = [
  ["Investigate", "Specialist agents read the plan, the schema and the workload, and every claim cites evidence from your inputs."],
  ["Propose", "An optimization engineer proposes indexes, statistics or rewrites, checked against a strict SQL allowlist."],
  ["Approve", "Nothing runs until you approve the exact SQL, and it only ever runs in a disposable sandbox copy, never on your database."],
  ["Verify", "A deterministic benchmark decides: verified, rejected, or inconclusive. A model can only downgrade a verdict, never invent one."],
  ["Replay", "Finished reports are sealed with digests; anyone can re-check them, and experiments can be re-measured."],
] as const;

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-10 px-4 py-16 md:py-24">
      <header className="flex flex-col gap-4">
        <p className="font-mono text-xs uppercase tracking-wider text-muted">PostgreSQL performance, with evidence</p>
        <h1 className="text-3xl font-semibold md:text-4xl">QueryCure</h1>
        <p className="max-w-2xl text-lg">
          A multi-agent investigator for slow PostgreSQL queries that proves its advice. Recommendations are measured in an isolated sandbox and
          judged by deterministic statistics, not by the model that suggested them.
        </p>
        <div className="flex flex-wrap gap-3">
          <Link href="/demo" className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-fg">
            Explore prerecorded investigations
          </Link>
          <Link href="/app" className="rounded-md border border-border-strong px-4 py-2 text-sm font-medium">
            Open the app
          </Link>
        </div>
      </header>
      <ol className="grid grid-cols-1 gap-3 md:grid-cols-5">
        {STEPS.map(([title, text], i) => (
          <li key={title} className="flex flex-col gap-1 rounded-lg border border-border bg-surface p-3">
            <span className="font-mono text-xs text-muted">{i + 1}</span>
            <span className="font-medium">{title}</span>
            <span className="text-sm text-muted">{text}</span>
          </li>
        ))}
      </ol>
      <p className="text-sm text-muted">
        On the public demo, benchmarks are prerecorded and labelled as such; live sandbox benchmarking and live database inspection run only
        on a local install. Analysis uses your own free OpenRouter key.
      </p>
    </main>
  );
}
