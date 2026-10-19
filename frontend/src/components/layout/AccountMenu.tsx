"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { API_BASE_URL } from "@/lib/api/client";
import { getMe, logout } from "@/lib/api/session";
import { Icon } from "@/components/ui/Icon";

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
  const name = user.kind === "oauth" ? (user.displayName ?? "Your account") : "Local session";
  return (
    <div className="flex min-w-0 flex-col gap-2 text-sm">
      <div className="flex min-w-0 items-center gap-2">
        <span aria-hidden="true" className="flex size-6 shrink-0 items-center justify-center rounded-full bg-surface-2 text-[11px] font-semibold text-muted">
          {name.slice(0, 1).toUpperCase()}
        </span>
        <span className="min-w-0 flex-1 truncate text-[13px] text-ink">
          {user.kind === "oauth" ? `Signed in as ${name}` : name}
        </span>
        {user.kind === "oauth" ? (
          <button type="button" onClick={() => out.mutate()} disabled={out.isPending} aria-label="Sign out" title="Sign out" className="qc-btn-ghost size-7 p-0">
            <Icon name="logout" size={14} />
          </button>
        ) : null}
      </div>
      {user.kind !== "oauth" && (features.googleLogin || features.githubLogin) ? (
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
          {features.googleLogin ? <SignInLink provider="google" label="Google" returnTo={returnTo} /> : null}
          {features.githubLogin ? <SignInLink provider="github" label="GitHub" returnTo={returnTo} /> : null}
        </div>
      ) : null}
    </div>
  );
}

function SignInLink({ provider, label, returnTo }: { provider: "google" | "github"; label: string; returnTo: string }) {
  return (
    <a
      href={`${API_BASE_URL}/api/v1/auth/${provider}/login?return_to=${encodeURIComponent(returnTo)}`}
      aria-label={`Sign in with ${label}`}
      className="whitespace-nowrap text-link"
    >
      Sign in with {label}
    </a>
  );
}
