import { SettingsView } from "@/components/settings/SettingsView";

// Session-gated client view; see the note in app/layout.tsx.
export const instant = false;

export default function SettingsPage() {
  return <SettingsView />;
}
