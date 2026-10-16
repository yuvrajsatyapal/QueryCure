import { InvestigationView } from "@/components/investigation/InvestigationView";

// Session-gated client view; see the note in app/layout.tsx.
export const instant = false;

export default async function InvestigationPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ run?: string | string[] }>;
}) {
  const { id } = await params;
  const { run } = await searchParams;
  return <InvestigationView id={id} requestedRunId={typeof run === "string" ? run : undefined} />;
}
