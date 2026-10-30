import type { Metadata } from "next";
import { Suspense } from "react";
import { SignInFromParams } from "@/components/auth/SignInFromParams";

export const metadata: Metadata = { title: "Sign in · QueryCure" };

// Reads the session and the sign-in options from the API in the browser.
export const instant = false;

export default function SignInPage() {
  // The view reads `next` and `auth_error` from the URL, so it renders in the browser.
  return (
    <Suspense fallback={<div className="min-h-dvh flex-1" />}>
      <SignInFromParams />
    </Suspense>
  );
}
