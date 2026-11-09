"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { ApiError } from "@/lib/api/client";
import { getAuthOptions, getMe } from "@/lib/api/session";

export type LandingAuth =
  | { status: "pending" }
  /** The API cannot be reached: nothing is known about the visitor's account. */
  | { status: "unavailable" }
  | { status: "signedIn"; name: string | null }
  /** No account: no session, a local or anonymous one, or an account a restricted trial has not approved. */
  | { status: "signedOut"; restricted: boolean; canSignIn: boolean };

const apiStatus = (error: unknown, status: number) => error instanceof ApiError && error.status === status;

/** What the landing page knows about the visitor, from the same `["me"]` and `["auth-options"]` queries
 * the app uses. It only reads: starting a session is `SessionGate`'s job, so a landing visit never
 * creates an anonymous user. The session is read again on window focus and when the page returns from
 * the back/forward cache, so a sign-in or sign-out in another tab or after Back shows up here. */
export function useLandingAuth(): LandingAuth {
  // retry off, like every other reader of these keys: a 401 is an answer, not a failure.
  // Focus is handled below, unconditionally, instead of only once the data is stale.
  const me = useQuery({ queryKey: ["me"], queryFn: ({ signal }) => getMe(signal), retry: false, refetchOnWindowFocus: false });
  const options = useQuery({ queryKey: ["auth-options"], queryFn: ({ signal }) => getAuthOptions(signal), retry: false });
  const { refetch } = me;

  useEffect(() => {
    const refresh = () => void refetch({ cancelRefetch: false });
    const restored = (e: PageTransitionEvent) => {
      if (e.persisted) refresh();
    };
    window.addEventListener("focus", refresh);
    window.addEventListener("pageshow", restored);
    return () => {
      window.removeEventListener("focus", refresh);
      window.removeEventListener("pageshow", restored);
    };
  }, [refetch]);

  // A restricted trial answers 403 to a signed-in account it has not approved.
  if (apiStatus(me.error, 403)) return { status: "signedOut", restricted: true, canSignIn: true };
  if (apiStatus(me.error, 401)) return fromOptions(options.data, options.isError);
  // Any other failed read (offline, 5xx) keeps the last answer rather than demoting a signed-in account.
  if (me.data) {
    if (me.data.user.kind === "oauth") return { status: "signedIn", name: me.data.user.displayName };
    return { status: "signedOut", restricted: false, canSignIn: me.data.features.googleLogin || me.data.features.githubLogin };
  }
  return me.isError ? { status: "unavailable" } : { status: "pending" };
}

function fromOptions(options: { restrictedAccess: boolean; githubLogin: boolean; googleLogin: boolean } | undefined, failed: boolean): LandingAuth {
  if (options) return { status: "signedOut", restricted: options.restrictedAccess, canSignIn: options.githubLogin || options.googleLogin };
  return failed ? { status: "unavailable" } : { status: "pending" };
}
