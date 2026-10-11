import { ConnectionsView } from "@/components/connections/ConnectionsView";

// Session-gated client view; see the note in app/layout.tsx.
export const instant = false;

export default function ConnectionsPage() {
  return <ConnectionsView />;
}
