"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useId, useState } from "react";
import { Icon } from "@/components/ui/Icon";
import { ApiError } from "@/lib/api/client";
import { getMe, logout } from "@/lib/api/session";
import { signInHref } from "@/lib/auth/returnTo";

/** First and last initials of a display name, or null when there is nothing to take them from. */
function initials(name: string | null): string | null {
  const words = (name ?? "").trim().split(/\s+/).filter(Boolean);
  const picked = words.length > 1 ? [words[0], words.at(-1)] : words;
  return (
    picked
      .map((w) => Array.from(w ?? "")[0] ?? "")
      .join("")
      .toUpperCase() || null
  );
}

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
  if (user.kind === "oauth") return <SignedIn key={user.id} name={user.displayName} collapsed={collapsed} />;

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

function SignedIn({ name: displayName, collapsed }: { name: string | null; collapsed: boolean }) {
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const regionId = useId();
  const out = useMutation({
    mutationFn: logout,
    // Drops every cached query (no stale name or runs); SessionGate then notices the 401 and
    // starts a fresh anonymous (or local) session.
    onSuccess: () => client.resetQueries(),
  });
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
        <div id={regionId} role="group" aria-label="Account" hidden={!open}>
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
      <button
        {...disclosure}
        className="flex w-full min-w-0 items-center gap-2.5 rounded-md p-1.5 text-left hover:bg-hover aria-expanded:bg-hover pointer-coarse:py-2"
      >
        <Avatar name={displayName} />
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-[13px] font-medium text-ink">{name}</span>
          <span className="truncate text-xs text-muted">Signed in</span>
        </span>
        <Icon name="chevronDown" size={15} className={`shrink-0 text-faint motion-safe:transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      <div id={regionId} role="group" aria-label="Account" hidden={!open} className="pt-1">
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
