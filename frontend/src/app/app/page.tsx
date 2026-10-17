import Link from "next/link";

// Session-gated client view; see the note in app/layout.tsx.
export const instant = false;

export default function DashboardPage() {
  return (
    <section className="max-w-2xl rounded-lg border border-border bg-surface p-6">
      <h1 className="text-2xl font-semibold">Dashboard</h1>
      <p className="mt-2 text-muted">
        Start a <Link href="/app/investigations/new" className="text-link">new investigation</Link> on
        a query, an uploaded plan or a demo workload, or open your past runs, reports and replays
        in <Link href="/app/history" className="text-link">History</Link>.
      </p>
    </section>
  );
}
