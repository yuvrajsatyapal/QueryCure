"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
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
 * `/sign-in` page; a signed-in account gets a profile row that expands its actions inline, in the
 * sidebar's own flow (no menu, popover or portal). `onNavigate` closes the mobile drawer. */
export function SidebarAccount({ collapsed = false, onNavigate }: { collapsed?: boolean; onNavigate?: () => void }) {
  const pathname = usePathname();
  const me = useQuery({ queryKey: ["me"], queryFn: ({ signal }) => getMe(signal), retry: false });

  if (!me.data) {
    // A 401 means SessionGate is starting a session: still loading, never a "signed out" flash.
    const starting = me.error instanceof ApiError && me.error.status === 401;
    if (!me.isPending && !starting) return null;
    return <span role="status" aria-label="Loading account" className={`block rounded-md bg-surface-2 ${collapsed ? "mx-auto size-8" : "h-[60px] w-full"}`} />;
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
  const [open, setOpen] = useState(false);
  const regionId = useId();
  const region = useRef<HTMLDivElement>(null);
  // On a short screen the footer sits at the sidebar's bottom edge, so the revealed actions would
  // open below it: bring them into view (instant; nothing moves when they are already visible).
  useEffect(() => {
    if (open) region.current?.scrollIntoView?.({ block: "nearest" });
  }, [open]);
  // SessionGate notices the resulting 401 and starts a fresh anonymous (or local) session.
  const out = useSignOut();
  const name = displayName?.trim() || "Your account";
  const toggle = () => {
    if (open) out.reset();
    setOpen(!open);
  };
  const signOutLabel = out.isPending ? "Signing out…" : "Sign out";

  const disclosure = { type: "button" as const, onClick: toggle, "aria-expanded": open, "aria-controls": regionId, title: name };
  const failed = out.isError ? (
    <p role="alert" className={collapsed ? "sr-only" : "px-2 pt-1 text-xs text-rejected"}>
      Sign-out failed. Check your connection and try again.
    </p>
  ) : null;

  if (collapsed) {
    return (
      <div className="flex flex-col items-center gap-1.5">
        <button {...disclosure} aria-label={`Account: ${name}`} className={`rounded-full ${out.isError ? "ring-2 ring-rejected" : ""}`}>
          <Avatar name={displayName} />
        </button>
        <SettingsLink active={settingsActive} onNavigate={onNavigate} className="flex size-8 items-center justify-center rounded-md" />
        <div ref={region} id={regionId} role="group" aria-label="Account" hidden={!open}>
          <button
            type="button"
            onClick={() => out.mutate()}
            disabled={out.isPending}
            aria-label={signOutLabel}
            title={signOutLabel}
            className="qc-btn-ghost size-8 p-0"
          >
            <Icon name="logout" size={16} />
          </button>
          {failed}
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-col">
      <div className={`flex items-center gap-0.5 rounded-md pr-0.5 hover:bg-hover ${open ? "bg-hover" : ""}`}>
        <button
          {...disclosure}
          className="flex min-w-0 flex-1 items-center gap-2.5 rounded-md p-1.5 text-left pointer-coarse:py-2"
        >
          <Avatar name={displayName} />
          <span className="flex min-w-0 flex-1 flex-col">
            <span className="truncate text-[13px] font-medium text-ink">{name}</span>
            <span className="truncate text-xs text-muted">Signed in</span>
          </span>
        </button>
        <SettingsLink active={settingsActive} onNavigate={onNavigate} className="flex size-7 shrink-0 items-center justify-center rounded-md pointer-coarse:size-11" />
        <button
          type="button"
          onClick={toggle}
          aria-label="Account actions"
          aria-expanded={open}
          aria-controls={regionId}
          className="flex size-7 shrink-0 items-center justify-center rounded-md text-faint hover:bg-surface-2 hover:text-ink pointer-coarse:size-11"
        >
          <Icon name="chevronDown" size={15} className={`motion-safe:transition-transform ${open ? "rotate-180" : ""}`} />
        </button>
      </div>
      <div ref={region} id={regionId} role="group" aria-label="Account" hidden={!open} className="pt-1">
        <button
          type="button"
          onClick={() => out.mutate()}
          disabled={out.isPending}
          className="flex h-8 w-full items-center gap-2.5 rounded-md px-2.5 text-[13px] font-medium text-muted hover:bg-hover hover:text-ink disabled:opacity-60 pointer-coarse:h-11"
        >
          <Icon name="logout" size={15} className="text-faint" />
          {signOutLabel}
        </button>
        {failed}
      </div>
    </div>
  );
}
