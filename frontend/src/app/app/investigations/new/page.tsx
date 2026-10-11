import { Workspace } from "@/components/workspace/Workspace";

// Session-gated client view; see the note in app/layout.tsx.
export const instant = false;

export default function NewInvestigationPage() {
  return <Workspace />;
}
