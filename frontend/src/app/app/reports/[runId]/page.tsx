import Link from "next/link";
import { ReportPanel } from "@/components/report/ReportPanel";

// Session-gated client view; see the note in app/layout.tsx.
export const instant = false;

export default async function ReportPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  return (
    <div className="flex flex-col gap-4">
      <Link className="text-sm text-link" href={`/app/replay/${runId}`}>
        Reproducibility & replay
      </Link>
      <ReportPanel runId={runId} />
    </div>
  );
}
