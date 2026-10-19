import Link from "next/link";
import { ThemeToggle } from "@/components/theme/ThemeToggle";
import { Icon, type IconName } from "@/components/ui/Icon";
import { Logo } from "@/components/ui/Logo";

const STEPS: [string, string, IconName][] = [
  ["Investigate", "Specialist agents read the plan, the schema and the workload, and every claim cites evidence from your inputs.", "bot"],
  ["Propose", "An optimization engineer proposes indexes, statistics or rewrites, checked against a strict SQL allowlist.", "sparkles"],
  ["Approve", "Nothing runs until you approve the exact SQL, and it only ever runs in a disposable sandbox copy, never on your database.", "hand"],
  ["Verify", "A deterministic benchmark decides: verified, rejected, or inconclusive. A model can only downgrade a verdict, never invent one.", "gauge"],
  ["Replay", "Finished reports are sealed with digests; anyone can re-check them, and experiments can be re-measured.", "replay"],
];

// An illustration of the trace view's shape, not a recorded run: no timings, no results.
const SKETCH: { name: string; depth: number; tone: "done" | "running" | "approval" | "log" }[] = [
  { name: "collect_context", depth: 0, tone: "done" },
  { name: "query_analyzer", depth: 0, tone: "done" },
  { name: "get_plan_node", depth: 1, tone: "log" },
  { name: "index_strategist", depth: 0, tone: "done" },
  { name: "synthesize_hypotheses", depth: 0, tone: "done" },
  { name: "optimization_engineer", depth: 0, tone: "done" },
  { name: "approval_gate", depth: 0, tone: "approval" },
  { name: "run_experiment", depth: 0, tone: "running" },
];

const GLYPH = {
  done: <Icon name="checkCircle" size={13} className="text-verified" />,
  running: <Icon name="loader" size={13} className="text-running" />,
  approval: <Icon name="hand" size={13} className="text-approval" />,
  log: <Icon name="wrench" size={13} className="text-faint" />,
};

export default function Home() {
  return (
    <div className="flex flex-1 flex-col">
      <header className="mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-4 py-4 md:px-8">
        <Link href="/" className="flex items-center gap-2 text-sm font-semibold tracking-tight">
          <Logo />
          QueryCure
        </Link>
        <nav aria-label="Site" className="flex items-center gap-1 text-sm">
          <Link href="/demo" className="qc-btn-ghost">
            Demo
          </Link>
          <ThemeToggle />
        </nav>
      </header>

      <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-20 px-4 pt-14 pb-20 md:px-8 md:pt-24">
        <section className="grid grid-cols-1 items-center gap-12 lg:grid-cols-[1.1fr_0.9fr]">
          <div className="flex flex-col gap-6">
            <p className="qc-eyebrow">PostgreSQL performance, with evidence</p>
            <h1 className="text-4xl leading-[1.08] font-semibold tracking-tight md:text-5xl">
              QueryCure
              <span className="block text-muted">finds why a query is slow, and proves the fix.</span>
            </h1>
            <p className="max-w-xl text-base text-muted md:text-lg">
              A multi-agent investigator for slow PostgreSQL queries. Recommendations are measured in an isolated sandbox and judged by
              deterministic statistics, not by the model that suggested them.
            </p>
            <div className="flex flex-wrap gap-2">
              <Link href="/app" className="qc-btn-primary px-4 py-2">
                Open the app
                <Icon name="arrowRight" size={14} />
              </Link>
              <Link href="/demo" className="qc-btn-secondary px-4 py-2">
                Explore prerecorded investigations
              </Link>
            </div>
          </div>

          <figure className="qc-panel overflow-hidden shadow-pop" aria-label="Illustration of the investigation trace">
            <div className="flex items-center justify-between border-b border-border px-3 py-2">
              <span className="flex items-center gap-2 text-xs font-medium">
                <Icon name="node" size={13} className="text-muted" />
                Trace
              </span>
              <span className="text-[11px] text-muted">Illustration</span>
            </div>
            <ol className="py-1">
              {SKETCH.map((row) => (
                <li key={row.name} className="flex items-center gap-2 px-3 py-1.5" style={{ paddingLeft: 12 + row.depth * 18 }}>
                  {GLYPH[row.tone]}
                  <span className={`font-mono text-xs ${row.tone === "log" ? "text-muted" : "text-ink"}`}>{row.name}</span>
                  {row.tone === "approval" ? (
                    <span className="ml-auto rounded-full border border-approval/30 bg-approval/10 px-2 text-[11px] text-approval">Approval required</span>
                  ) : null}
                </li>
              ))}
            </ol>
          </figure>
        </section>

        <section aria-label="How it works" className="flex flex-col gap-6">
          <h2 className="text-xl font-semibold tracking-tight">Five steps, each one checkable</h2>
          <ol className="grid grid-cols-1 overflow-hidden rounded-lg border border-border md:grid-cols-5">
            {STEPS.map(([title, text, icon], i) => (
              <li key={title} className={`flex flex-col gap-2 bg-surface p-4 ${i ? "border-t border-border md:border-t-0 md:border-l" : ""}`}>
                <span className="flex items-center gap-2">
                  <Icon name={icon} size={15} className="text-accent" />
                  <span className="font-mono text-[11px] text-muted">0{i + 1}</span>
                </span>
                <span className="font-medium">{title}</span>
                <span className="text-sm text-muted">{text}</span>
              </li>
            ))}
          </ol>
        </section>

        <p className="max-w-3xl text-sm text-muted">
          On the public demo, benchmarks are prerecorded and labelled as such; live sandbox benchmarking and live database inspection run only
          on a local install. Analysis uses your own free OpenRouter key.
        </p>
      </main>
    </div>
  );
}
