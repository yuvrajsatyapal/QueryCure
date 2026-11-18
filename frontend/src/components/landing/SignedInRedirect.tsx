"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useLandingAuth } from "./useLandingAuth";

/** A visitor with an account has no use for the marketing page: send them to the dashboard. `replace`
 * keeps the landing page out of their history, so Back does not bounce them forward again. */
export function SignedInRedirect() {
  const auth = useLandingAuth();
  const router = useRouter();
  const signedIn = auth.status === "signedIn";
  useEffect(() => {
    if (signedIn) router.replace("/app");
  }, [signedIn, router]);
  return null;
}
