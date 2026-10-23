"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { ErrorNotice } from "@/components/common/ErrorNotice";
import { API_BASE_URL, ApiError } from "@/lib/api/client";
import { createSession, getAuthOptions, getMe, logout } from "@/lib/api/session";

const NOT_APPROVED = "This account is not approved for this trial. Sign in with an approved account, or ask the owner for access.";

const AUTH_ERRORS: Record<string, string> = {
  access_denied: "Sign-in was cancelled.",
  state_missing: "The sign-in attempt expired. Please try again.",
  state_mismatch: "The sign-in response did not match this browser's request, so it was refused.",
  token_exchange_failed: "The sign-in provider did not confirm the sign-in. Please try again.",
  provider_unreachable: "The sign-in provider could not be reached. Please try again later.",
  profile_unavailable: "Your profile could not be read from the sign-in provider.",
  not_allowed: NOT_APPROVED,
};

const isDenied = (error: unknown) => error instanceof ApiError && error.status === 403 && error.code === "ACCESS_DENIED";

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

/** Restricted trial (ADR-0031): no anonymous session, so the app waits behind sign-in. */
function SignInScreen({ signedIn }: { signedIn: boolean }) {
  const queryClient = useQueryClient();
  const options = useQuery({ queryKey: ["auth-options"], queryFn: ({ signal }) => getAuthOptions(signal), retry: false });
  const out = useMutation({ mutationFn: logout, onSuccess: () => queryClient.resetQueries() });
  const returnTo = typeof window === "undefined" ? "/app" : window.location.pathname;
  const providers = [
    { id: "google", label: "Google", on: options.data?.googleLogin },
    { id: "github", label: "GitHub", on: options.data?.githubLogin },
  ].filter((p) => p.on);
  return (
    <div className="mx-auto max-w-md py-12">
      <h1 className="text-lg font-semibold text-ink">Sign in to QueryCure</h1>
      <p className="mt-2 text-sm text-muted">This trial is limited to approved accounts.</p>
      <div className="mt-4">
        {signedIn ? (
          <p role="alert" className="mb-4 rounded-md border border-rejected/40 bg-surface-2 p-3 text-sm text-rejected">
            {NOT_APPROVED}
          </p>
        ) : (
          <AuthErrorNotice />
        )}
      </div>
      <div className="flex flex-col gap-2">
        {providers.map((p) => (
          <a
            key={p.id}
            href={`${API_BASE_URL}/api/v1/auth/${p.id}/login?return_to=${encodeURIComponent(returnTo)}`}
            aria-label={`Sign in with ${p.label}`}
            className="qc-btn-primary justify-center"
          >
            Sign in with {p.label}
          </a>
        ))}
        {options.isError ? <ErrorNotice error={options.error} /> : null}
        {signedIn ? (
          <button type="button" onClick={() => out.mutate()} disabled={out.isPending} className="qc-btn-ghost justify-center">
            Sign out
          </button>
        ) : null}
      </div>
    </div>
  );
}

/** Ensures a session exists (local user, anonymous demo user, or an approved account in a
 * restricted trial) before rendering the app. */
export function SessionGate({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: ({ signal }) => getMe(signal), retry: false });
  const unauthenticated = me.error instanceof ApiError && me.error.status === 401;
  const [signInRequired, setSignInRequired] = useState(false);

  useEffect(() => {
    if (!unauthenticated) return;
    createSession()
      .then(() => queryClient.invalidateQueries({ queryKey: ["me"] }))
      .catch((error: unknown) => {
        if (isDenied(error)) setSignInRequired(true);
      });
  }, [unauthenticated, queryClient]);

  if (me.isSuccess)
    return (
      <>
        <AuthErrorNotice />
        {children}
      </>
    );
  if (isDenied(me.error)) return <SignInScreen signedIn />;
  if (unauthenticated && signInRequired) return <SignInScreen signedIn={false} />;
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
