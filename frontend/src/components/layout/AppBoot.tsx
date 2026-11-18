"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ApiError } from "@/lib/api/client";
import { listInvestigations } from "@/lib/api/investigations";
import { getMe } from "@/lib/api/session";
import { LoadingScreen, type LoadingStep } from "./LoadingScreen";
import { RECENT_LIMIT, recentKey } from "./SideNav";

// Past this, the screen offers a way out instead of only a spinner.
const STALL_MS = 4000;

/** The loading screen shown while the app opens: it covers the shell until the account is confirmed and
 * the first investigations are in, so the dashboard appears complete. It reads the same two queries the
 * sidebar and dashboard use, so it adds no requests, and it is latched: it never returns on later changes. */
export function AppBoot() {
  const me = useQuery({ queryKey: ["me"], queryFn: ({ signal }) => getMe(signal), retry: false });
  const recent = useQuery({
    queryKey: recentKey,
    queryFn: ({ signal }) => listInvestigations({ limit: RECENT_LIMIT }, signal),
    enabled: me.isSuccess,
  });
  const [done, setDone] = useState(false);
  const [slow, setSlow] = useState(false);

  // A denied account is sent to the sign-in page by SessionGate: nothing left to wait for here.
  const denied = me.error instanceof ApiError && me.error.status === 403;
  const ready = denied || (me.isSuccess && !recent.isPending);
  // Latch during render (React's pattern for state derived from a changing value): never reopens.
  if (ready && !done) setDone(true);
  useEffect(() => {
    if (done) return;
    const timer = setTimeout(() => setSlow(true), STALL_MS);
    return () => clearTimeout(timer);
  }, [done]);

  if (done) return null;

  const unreachable = me.isError && !(me.error instanceof ApiError && me.error.status === 401);
  const steps: LoadingStep[] = [
    { label: "Confirm account", state: me.isSuccess ? "done" : "run" },
    { label: "Load investigations", state: !me.isSuccess ? "wait" : recent.isPending ? "run" : "done" },
  ];
  const status = !me.isSuccess ? "Confirming your account…" : "Loading your workspace…";
  const stalled =
    slow || unreachable
      ? {
          title: unreachable ? "Can't reach QueryCure" : "Still connecting to QueryCure",
          body: unreachable
            ? "The server did not answer. Check that it is running, then try again."
            : "The server is slower than usual to respond. This can happen right after it has been idle. We'll keep trying in the background.",
          onRetry: () => window.location.reload(),
        }
      : undefined;
  return <LoadingScreen title="Getting QueryCure ready" status={slow && !unreachable ? "Taking a little longer…" : status} steps={steps} hint="Opens your dashboard when everything is ready." stalled={stalled} />;
}
