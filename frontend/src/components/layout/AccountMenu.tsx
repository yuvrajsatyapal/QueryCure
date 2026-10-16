"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { API_BASE_URL } from "@/lib/api/client";
import { getMe, logout } from "@/lib/api/session";

/** Who is signed in, Google and GitHub sign-in when the deployment offers them, and sign-out. */
export function AccountMenu() {
  const client = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: ({ signal }) => getMe(signal), retry: false });
  const out = useMutation({
    mutationFn: logout,
    // SessionGate notices the 401 and starts a fresh anonymous (or local) session.
    onSuccess: () => client.resetQueries(),
  });
  if (!me.data) return null;
  const { user, features } = me.data;
  const returnTo = typeof window === "undefined" ? "/app" : window.location.pathname;
  return (
    <div className="flex min-w-0 items-center gap-3 text-sm">
      {user.kind === "oauth" ? (
        <>
          <span className="truncate text-muted">Signed in as {user.displayName ?? "your account"}</span>
          <button type="button" onClick={() => out.mutate()} disabled={out.isPending} className="text-link">
            Sign out
          </button>
        </>
      ) : (
        <>
          {features.googleLogin ? <SignInLink provider="google" label="Google" returnTo={returnTo} /> : null}
          {features.githubLogin ? <SignInLink provider="github" label="GitHub" returnTo={returnTo} /> : null}
        </>
      )}
    </div>
  );
}

function SignInLink({ provider, label, returnTo }: { provider: "google" | "github"; label: string; returnTo: string }) {
  return (
    <a href={`${API_BASE_URL}/api/v1/auth/${provider}/login?return_to=${encodeURIComponent(returnTo)}`} className="whitespace-nowrap text-link">
      Sign in with {label}
    </a>
  );
}
