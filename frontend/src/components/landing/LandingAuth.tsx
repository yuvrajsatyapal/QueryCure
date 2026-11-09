"use client";

import Link from "next/link";
import { Icon } from "@/components/ui/Icon";
import { initials, useSignOut } from "@/lib/auth/account";
import { signInHref } from "@/lib/auth/returnTo";
import { LpIcon } from "./LpIcon";
import { useLandingAuth, type LandingAuth } from "./useLandingAuth";

/* The landing page's session-aware slots. The page itself stays a static server render; only these small
 * islands read the session (useLandingAuth) and fill in once it is known. Until then they reserve their
 * space and say nothing: any link shown before the answer could be wrong for this visitor. */

const APP = "/app";
// The dashboard is the default destination of the existing sign-in flow, so no `next` is needed.
const SIGN_IN = signInHref(APP);

interface Entry {
  label: string;
  href: string;
}

/** The one way in for this visitor, or null when the deployment offers none. */
function entry(auth: LandingAuth, signedOutLabel: string): Entry | null {
  switch (auth.status) {
    case "pending":
      return null;
    case "unavailable":
      return { label: signedOutLabel, href: SIGN_IN };
    case "signedIn":
      return { label: "Open dashboard", href: APP };
    case "signedOut":
      if (auth.canSignIn) return { label: auth.restricted ? "Sign in" : signedOutLabel, href: SIGN_IN };
      // No provider: an open deployment can still be used without an account; a restricted one cannot.
      return auth.restricted ? null : { label: "Open QueryCure", href: APP };
  }
}

function Slot({ small = false }: { small?: boolean }) {
  return <span data-auth-slot="pending" aria-hidden="true" className={`auth-slot${small ? " sm" : ""}`} />;
}

function Cta({ to, className, arrow = false }: { to: Entry; className: string; arrow?: boolean }) {
  return (
    <Link href={to.href} className={className}>
      {to.label}
      {arrow ? <LpIcon name="arrowRight" size={15} /> : null}
    </Link>
  );
}

/** The hero's primary action. */
export function HeroCta() {
  const auth = useLandingAuth();
  if (auth.status === "pending") return <Slot />;
  const to = entry(auth, "Get started");
  return to ? <Cta to={to} className="btn btn-primary" arrow /> : null;
}

/** The closing call to action: the primary action, and Open QueryCure as the way to try it without an account. */
export function FinalCtas() {
  const auth = useLandingAuth();
  if (auth.status === "pending") return <Slot />;
  const to = entry(auth, "Get started");
  const withoutAccount = auth.status === "signedOut" && auth.canSignIn && !auth.restricted;
  return (
    <>
      {to ? <Cta to={to} className="btn btn-primary" arrow /> : null}
      {withoutAccount ? <Cta to={{ label: "Open QueryCure", href: APP }} className="btn btn-secondary" /> : null}
    </>
  );
}

export function FooterAuthLink() {
  const auth = useLandingAuth();
  if (auth.status === "signedIn") return <Link href={APP}>Dashboard</Link>;
  const to = entry(auth, "Sign in");
  // Only a sign-in belongs in the footer; "Open QueryCure" is already in the header and the call to action.
  return to && to.href === SIGN_IN ? <Link href={to.href}>{to.label}</Link> : null;
}

export function NavAuth() {
  const auth = useLandingAuth();
  const signOut = useSignOut();
  if (auth.status === "pending") return <Slot small />;

  if (auth.status === "signedIn") {
    const name = auth.name?.trim() || null;
    const text = initials(name);
    const label = signOut.isPending ? "Signing out…" : "Sign out";
    return (
      <>
        <Link href={APP} className="btn btn-primary btn-sm">
          Open dashboard
        </Link>
        <span role="img" aria-label={name ? `Signed in as ${name}` : "Signed in"} title={name ?? undefined} className="nav-acct">
          {text ?? <Icon name="user" size={15} />}
        </span>
        <button type="button" onClick={() => signOut.mutate()} disabled={signOut.isPending} className="btn btn-secondary btn-sm">
          {label}
        </button>
        {signOut.isError ? (
          <span role="alert" className="nav-err">
            Sign-out failed. Check your connection and try again.
          </span>
        ) : null}
      </>
    );
  }

  const signIn = entry(auth, "Sign in");
  if (!signIn) return null;
  // Signed out with sign-in on offer in an open deployment: Open QueryCure remains available as the secondary.
  const withoutAccount = auth.status === "signedOut" && auth.canSignIn && !auth.restricted;
  return (
    <>
      {withoutAccount ? <Cta to={{ label: "Open QueryCure", href: APP }} className="btn btn-secondary btn-sm" /> : null}
      <Cta to={signIn} className="btn btn-primary btn-sm" />
    </>
  );
}
