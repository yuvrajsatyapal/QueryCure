"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { ErrorNotice } from "@/components/common/ErrorNotice";
import { ApiError } from "@/lib/api/client";
import { createSession, getMe } from "@/lib/api/session";
import { authErrorMessage } from "@/lib/auth/errors";
import { rememberedReturnTo, signInHref } from "@/lib/auth/returnTo";

const isDenied = (error: unknown) => error instanceof ApiError && error.status === 403 && error.code === "ACCESS_DENIED";

// Where the API's OAuth callback sends a failed or cancelled sign-in (`/app?auth_error=`).
const authErrorCode = () => new URLSearchParams(window.location.search).get("auth_error");

/** Hands over to the one sign-in page. After a failed attempt the URL is the API's
 * `/app?auth_error=`, so the destination is the one remembered when that attempt started. */
function ToSignIn() {
  const router = useRouter();
  useEffect(() => {
    const code = authErrorCode();
    router.replace(code ? signInHref(rememberedReturnTo(), code) : signInHref(window.location.pathname + window.location.search));
  }, [router]);
  return <p className="text-muted">Opening sign-in…</p>;
}

/** Without an account yet, a failed sign-in is shown on the sign-in page, where it can be retried;
 * a signed-in account (trying another one) keeps the notice on the page it came back to. */
function SignedInOrRetry({ oauth, children }: { oauth: boolean; children: ReactNode }) {
  // Mounted only after the session query resolves in the browser, so window exists here.
  const [code] = useState(authErrorCode);
  if (code !== null && !oauth) return <ToSignIn />;
  return (
    <>
      {code ? (
        <p role="alert" className="mb-4 rounded-md border border-rejected/40 bg-surface-2 p-3 text-sm text-rejected">
          {authErrorMessage(code)}
        </p>
      ) : null}
      {children}
    </>
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

  if (me.isSuccess) return <SignedInOrRetry oauth={me.data.user.kind === "oauth"}>{children}</SignedInOrRetry>;
  // Restricted trial (ADR-0031): no anonymous session, so the app waits behind the sign-in page,
  // which also tells a signed-in account that is not approved, and lets it sign out.
  if (isDenied(me.error) || (unauthenticated && signInRequired)) return <ToSignIn />;
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
