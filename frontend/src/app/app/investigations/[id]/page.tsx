import { InvestigationView } from "@/components/investigation/InvestigationView";

// Session-gated client view; see the note in app/layout.tsx.
export const instant = false;

export default async function InvestigationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <InvestigationView id={id} />;
}
