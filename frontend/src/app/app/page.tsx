// Session-gated client view; see the note in app/layout.tsx.
export const instant = false;

export default function DashboardPage() {
  return (
    <section className="max-w-2xl rounded-lg border border-border bg-surface p-6">
      <h1 className="text-2xl font-semibold">Dashboard</h1>
      <p className="mt-2 text-muted">
        No investigations yet. Multi-agent investigations arrive in Phase 2. Today you can add a
        connection and inspect query plans in the workspace.
      </p>
    </section>
  );
}
