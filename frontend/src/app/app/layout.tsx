import type { ReactNode } from "react";
import { AppShell } from "@/components/layout/AppShell";

// The app is session-gated in the browser (SessionGate) and reads data from the separate API, so
// a server render cannot produce the page segments; opt out of instant-navigation validation.
export const instant = false;

export default function AppLayout({ children }: { children: ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
