"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon } from "@/components/ui/Icon";
import { ApiError } from "@/lib/api/client";
import { getMe } from "@/lib/api/session";
import { initials, useSignOut } from "@/lib/auth/account";
import { signInHref } from "@/lib/auth/returnTo";

// The API exposes no avatar or email (ADR-0013, ADR-0031: an email is stored only for the
// restricted-access check and never returned), so the account shows initials and a neutral line.
function Avatar({ name }: { name: string | null }) {
  const text = initials(name);
  return (
    <span
      aria-hidden="true"
      data-avatar={text ? "initials" : "icon"}
      className="flex size-8 shrink-0 items-center justify-center rounded-full bg-surface-2 text-[11px] font-semibold text-muted ring-1 ring-border"
    >
      {text ?? <Icon name="user" size={15} />}
    </span>
  );
}

/** The sidebar's account footer. A local or anonymous session gets one Sign in link to the
 * `/sign-in` page; a signed-in account gets a profile row with Settings and Sign out buttons. `onNavigate` closes the mobile drawer. */
export function SidebarAccount({ collapsed = false, onNavigate }: { collapsed?: boolean; onNavigate?: () => void }) {
  const pathname = usePathname();
  const me = useQuery({ queryKey: ["me"], queryFn: ({ signal }) => getMe(signal), retry: false });

  if (!me.data) {
    // A 401 means SessionGate is starting a session: still loading, never a "signed out" flash.
    const starting = me.error instanceof ApiError && me.error.status === 401;
    if (!me.isPending && !starting) return null;
    // Same footprint as the signed-in row, so signing in or out never makes the footer jump.
    return collapsed ? (
      <span role="status" aria-label="Loading account" className="mx-auto block size-8 rounded-full bg-surface-2 motion-safe:animate-pulse" />
    ) : (
      <div role="status" aria-label="Loading account" className="flex items-center gap-2.5 p-1.5 motion-safe:animate-pulse">
        <span className="size-8 shrink-0 rounded-full bg-surface-2" />
        <span className="flex flex-1 flex-col gap-1.5">
          <span className="h-3 w-24 rounded bg-surface-2" />
          <span className="h-2.5 w-14 rounded bg-surface-2" />
        </span>
      </div>
    );
  }

  const { user, features } = me.data;
  if (user.kind === "oauth") return <SignedIn key={user.id} name={user.displayName} collapsed={collapsed} settingsActive={isSettings(pathname)} onNavigate={onNavigate} />;

  const canSignIn = features.googleLogin || features.githubLogin;
  const href = signInHref(pathname ?? "/app");
  if (collapsed) {
    return canSignIn ? (
      <Link href={href} onClick={onNavigate} aria-label="Sign in" title="Sign in" className="qc-btn-ghost mx-auto size-8 p-0">
        <Icon name="login" size={16} className="text-accent" />
      </Link>
    ) : null;
  }
  return (
    <div className="flex flex-col gap-2">
      <p className="flex min-w-0 items-center gap-2 px-1 text-[13px] text-ink">
        <Icon name="userCircle" size={16} className="text-faint" />
        <span className="truncate">Local session</span>
      </p>
      {canSignIn ? (
        <Link href={href} onClick={onNavigate} className="qc-btn-secondary h-9 w-full justify-start shadow-sm pointer-coarse:h-11">
          <Icon name="login" size={15} className="text-accent" />
          <span className="flex-1 text-left">Sign in</span>
          <Icon name="chevronRight" size={15} className="text-faint" />
        </Link>
      ) : null}
    </div>
  );
}

const isSettings = (pathname: string | null) => !!pathname?.startsWith("/app/settings");

/** Settings lives in the account row for a signed-in account (a local session keeps the nav link). */
function SettingsLink({ active, onNavigate, className }: { active: boolean; onNavigate?: () => void; className: string }) {
  return (
    <Link
      href="/app/settings"
      onClick={onNavigate}
      aria-label="Settings"
      title="Settings"
      aria-current={active ? "page" : undefined}
      className={`${className} ${active ? "bg-accent-tint text-accent" : "text-faint hover:bg-surface-2 hover:text-ink"}`}
    >
      <Icon name="settings" size={16} />
    </Link>
  );
}

function SignedIn({
  name: displayName,
  collapsed,
  settingsActive,
  onNavigate,
}: {
  name: string | null;
  collapsed: boolean;
  settingsActive: boolean;
  onNavigate?: () => void;
}) {
  // SessionGate notices the resulting 401 and starts a fresh anonymous (or local) session.
  const out = useSignOut({ startSession: true });
  const name = displayName?.trim() || "Your account";
  const signOutLabel = out.isPending ? "Signing out…" : "Sign out";
  const size = collapsed ? "size-8" : "size-7 pointer-coarse:size-11";

  const signOut = (
    <button
      type="button"
      onClick={() => out.mutate()}
      disabled={out.isPending}
      aria-label={signOutLabel}
      title={signOutLabel}
      className={`flex ${size} shrink-0 items-center justify-center rounded-md text-faint hover:bg-surface-2 hover:text-ink disabled:opacity-60`}
    >
      <Icon name="logout" size={16} />
    </button>
  );
  const failed = out.isError ? (
    <p role="alert" className={collapsed ? "sr-only" : "px-2 pt-1 text-xs text-rejected"}>
      Sign-out failed. Check your connection and try again.
    </p>
  ) : null;

  if (collapsed) {
    return (
      <div className="flex flex-col items-center gap-1.5">
        <span title={name} aria-label={`Account: ${name}`} role="img" className={`rounded-full ${out.isError ? "ring-2 ring-rejected" : ""}`}>
          <Avatar name={displayName} />
        </span>
        <SettingsLink active={settingsActive} onNavigate={onNavigate} className={`flex ${size} items-center justify-center rounded-md`} />
        {signOut}
        {failed}
      </div>
    );
  }
  return (
    <div className="flex flex-col">
      <div className="flex items-center gap-0.5 rounded-md p-1.5 pr-1">
        <div title={name} className="flex min-w-0 flex-1 items-center gap-2.5">
          <Avatar name={displayName} />
          <span className="flex min-w-0 flex-1 flex-col">
            <span className="truncate text-[13px] font-medium text-ink">{name}</span>
            <span className="truncate text-xs text-muted">Signed in</span>
          </span>
        </div>
        <SettingsLink active={settingsActive} onNavigate={onNavigate} className={`flex ${size} shrink-0 items-center justify-center rounded-md`} />
        {signOut}
      </div>
      {failed}
    </div>
  );
}
