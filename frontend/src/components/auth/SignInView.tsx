"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ErrorNotice } from "@/components/common/ErrorNotice";
import { ThemeToggle } from "@/components/theme/ThemeToggle";
import { Icon } from "@/components/ui/Icon";
import { Logo } from "@/components/ui/Logo";
import { ProviderIcon, type Provider } from "@/components/ui/ProviderIcon";
import { API_BASE_URL, ApiError } from "@/lib/api/client";
import { getAuthOptions, getMe, logout } from "@/lib/api/session";
import { NOT_APPROVED, authErrorMessage } from "@/lib/auth/errors";
import { rememberReturnTo, safeReturnTo } from "@/lib/auth/returnTo";

const PROVIDERS: { id: Provider; label: string; flag: "googleLogin" | "githubLogin" }[] = [
  { id: "google", label: "Google", flag: "googleLogin" },
  { id: "github", label: "GitHub", flag: "githubLogin" },
];

/** The dedicated sign-in page. Each provider is a plain link to the API's existing login route,
 * which runs the whole OAuth flow (state, PKCE, session rotation) and redirects back to the
 * validated `next` path; a refused or cancelled sign-in comes back here as `?auth_error=`. It is the
 * only sign-in screen: a restricted trial (ADR-0031) sends its gated pages here too. */
export function SignInView({ next, authError }: { next: string | null; authError: string | null }) {
  const router = useRouter();
  const returnTo = safeReturnTo(next);
  // Public: lists the providers without needing a session (and works in a restricted trial).
  const options = useQuery({ queryKey: ["auth-options"], queryFn: ({ signal }) => getAuthOptions(signal), retry: false });
  // A 401 here just means there is no session yet, which is fine for signing in.
  const me = useQuery({ queryKey: ["me"], queryFn: ({ signal }) => getMe(signal), retry: false });
  const signedIn = me.data?.user.kind === "oauth";
  // A restricted trial refuses a session whose account is not (or no longer) approved.
  const denied = me.error instanceof ApiError && me.error.status === 403 && me.error.code === "ACCESS_DENIED";
  const restricted = options.data?.restrictedAccess === true;
  const client = useQueryClient();
  const out = useMutation({ mutationFn: logout, onSuccess: () => client.resetQueries() });
  const notice = authError ? authErrorMessage(authError) : denied ? NOT_APPROVED : null;
  // Navigation to a provider has started: further clicks would only start a second flow.
  const [pending, setPending] = useState<Provider | null>(null);

  useEffect(() => {
    if (signedIn) router.replace(returnTo);
  }, [signedIn, returnTo, router]);
  useEffect(() => {
    // Coming back with the browser's Back button can restore this page from the bfcache.
    const restored = (e: PageTransitionEvent) => {
      if (e.persisted) setPending(null);
    };
    window.addEventListener("pageshow", restored);
    return () => window.removeEventListener("pageshow", restored);
  }, []);

  const providers = PROVIDERS.filter((p) => options.data?.[p.flag]);
  // Wait for both answers so neither the options nor a signed-in account flash in first.
  const loading = options.isPending || me.isPending;

  let body;
  if (signedIn) {
    body = <Placeholder label="Already signed in. Redirecting…" />;
  } else if (loading) {
    body = <Placeholder label="Loading sign-in options" />;
  } else if (options.isError) {
    body = (
      <div className="flex flex-col gap-3">
        <ErrorNotice error={options.error} />
        <button type="button" onClick={() => options.refetch()} className="qc-btn-secondary h-10 w-full">
          Try again
        </button>
      </div>
    );
  } else if (!providers.length) {
    body = <p className="rounded-md border border-border bg-surface-2 p-3 text-sm text-muted">Sign-in is not configured for this deployment.</p>;
  } else {
    body = (
      <div className="flex flex-col gap-2.5">
        {providers.map((p) => (
          <a
            key={p.id}
            href={`${API_BASE_URL}/api/v1/auth/${p.id}/login?return_to=${encodeURIComponent(returnTo)}`}
            aria-disabled={pending ? true : undefined}
            onClick={(e) => {
              if (pending) {
                e.preventDefault();
                return;
              }
              rememberReturnTo(returnTo);
              setPending(p.id);
            }}
            className="qc-btn-secondary h-11 w-full justify-center gap-2.5 text-sm aria-disabled:cursor-default aria-disabled:opacity-60"
          >
            {pending === p.id ? <Icon name="loader" size={16} className="motion-safe:animate-spin" /> : <ProviderIcon provider={p.id} size={17} />}
            {pending === p.id ? `Redirecting to ${p.label}…` : `Continue with ${p.label}`}
          </a>
        ))}
        {denied ? (
          <button type="button" onClick={() => out.mutate()} disabled={out.isPending} className="qc-btn-ghost h-10 w-full justify-center">
            {out.isPending ? "Signing out…" : "Sign out"}
          </button>
        ) : null}
      </div>
    );
  }

  return (
    <div className="flex min-h-dvh flex-1 flex-col">
      <header className="flex h-14 shrink-0 items-center justify-between gap-3 px-3 sm:px-5">
        {/* In a restricted trial the app itself would only send the user back here. */}
        <Link href={restricted ? "/" : returnTo} className="qc-btn-ghost h-9 gap-2 px-2.5 pointer-coarse:h-11">
          <Icon name="arrowLeft" size={15} />
          Back to QueryCure
        </Link>
        <ThemeToggle className="size-9 pointer-coarse:size-11" />
      </header>
      {/* Centred, slightly above the middle; on a short screen the content just grows the page. */}
      <main className="flex flex-1 items-center justify-center px-4 pt-6 pb-[12vh] sm:pt-0 sm:pb-[10vh]">
        <div className="w-full max-w-[380px]">
          <Logo size={36} />
          <h1 className="mt-6 text-2xl font-semibold tracking-tight text-ink">Welcome to QueryCure</h1>
          <p className="mt-2 text-sm leading-relaxed text-muted">Sign in to manage your investigations and database connections.</p>
          {restricted ? <p className="mt-1 text-sm leading-relaxed text-muted">This trial is limited to approved accounts.</p> : null}
          {notice ? (
            <p role="alert" className="mt-6 rounded-md border border-rejected/40 bg-surface-2 p-3 text-sm text-rejected">
              {notice}
            </p>
          ) : null}
          <div className="mt-8">{body}</div>
          <p className="mt-8 flex gap-2.5 border-t border-border pt-5 text-xs leading-relaxed text-muted">
            <Icon name="lock" size={14} className="mt-px shrink-0 text-faint" />
            <span>QueryCure never sees your password. Google or GitHub confirms who you are, and you come back to where you left off.</span>
          </p>
        </div>
      </main>
    </div>
  );
}

function Placeholder({ label }: { label: string }) {
  return (
    <div role="status" aria-label={label} className="flex flex-col gap-2.5">
      <span className="block h-11 rounded-md bg-surface-2" />
      <span className="block h-11 rounded-md bg-surface-2" />
    </div>
  );
}
