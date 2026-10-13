import { ReplayView } from "@/components/replay/ReplayView";

// Session-gated client view; see the note in app/layout.tsx.
export const instant = false;

export default async function ReplayPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  return <ReplayView runId={runId} />;
}
