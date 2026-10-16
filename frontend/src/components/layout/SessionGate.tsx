"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { ErrorNotice } from "@/components/common/ErrorNotice";
import { ApiError } from "@/lib/api/client";
import { createSession, getMe } from "@/lib/api/session";

const AUTH_ERRORS: Record<string, string> = {
  access_denied: "Sign-in was cancelled.",
  state_missing: "The sign-in attempt expired. Please try again.",
  state_mismatch: "The sign-in response did not match this browser's request, so it was refused.",
  token_exchange_failed: "The sign-in provider did not confirm the sign-in. Please try again.",
  provider_unreachable: "The sign-in provider could not be reached. Please try again later.",
  profile_unavailable: "Your profile could not be read from the sign-in provider.",
};

function AuthErrorNotice() {
  // Mounted only after the session query resolves in the browser, so window exists here.
  const [code] = useState<string | null>(() =>
    typeof window === "undefined" ? null : new URLSearchParams(window.location.search).get("auth_error"),
  );
  if (!code) return null;
  return (
    <p role="alert" className="mb-4 rounded-md border border-rejected/40 bg-surface-2 p-3 text-sm text-rejected">
      {AUTH_ERRORS[code] ?? "Sign-in failed."}
    </p>
  );
}

/** Ensures a session exists (local user or anonymous demo user) before rendering the app. */
export function SessionGate({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: ({ signal }) => getMe(signal), retry: false });
  const unauthenticated = me.error instanceof ApiError && me.error.status === 401;

  useEffect(() => {
    if (!unauthenticated) return;
    createSession()
      .then(() => queryClient.invalidateQueries({ queryKey: ["me"] }))
      .catch(() => undefined);
  }, [unauthenticated, queryClient]);

  if (me.isSuccess)
    return (
      <>
        <AuthErrorNotice />
        {children}
      </>
    );
  if (me.isError && !unauthenticated) {
    return (
      <div className="max-w-xl">
        <ErrorNotice error={me.error} />
        <p className="mt-2 text-sm text-muted">Is the API running? See the README for local setup.</p>
      </div>
    );
  }
  return <p className="text-muted">Starting session…</p>;
}
