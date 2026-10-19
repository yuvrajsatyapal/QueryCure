import { ReportPanel } from "@/components/report/ReportPanel";

// Session-gated client view; see the note in app/layout.tsx.
export const instant = false;

export default async function ReportPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  return (
    <div className="mx-auto w-full max-w-6xl">
      <ReportPanel runId={runId} standalone />
    </div>
  );
}
