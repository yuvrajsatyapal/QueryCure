import { HistoryView } from "@/components/history/HistoryView";

// Session-gated client view; see the note in app/layout.tsx.
export const instant = false;

export default function HistoryPage() {
  return <HistoryView />;
}
