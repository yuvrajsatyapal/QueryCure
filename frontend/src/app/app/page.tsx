import { DashboardView } from "@/components/dashboard/DashboardView";

// Session-gated client view; see the note in app/layout.tsx.
export const instant = false;

export default function DashboardPage() {
  return <DashboardView />;
}
