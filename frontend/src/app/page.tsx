import Link from "next/link";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center gap-4 px-4 py-24">
      <h1 className="text-2xl font-semibold">QueryCure</h1>
      <p>Multi-agent investigation and verified optimization of PostgreSQL query performance.</p>
      <p className="text-sm text-muted">Phase 1 scaffolding. The investigation workspace is not built yet.</p>
      <Link href="/app" className="w-fit rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-fg">
        Open the app
      </Link>
    </main>
  );
}
