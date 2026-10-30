"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type ReactNode } from "react";
import { ContextMenu } from "@/components/ui/ContextMenu";
import { Icon } from "@/components/ui/Icon";
import { getMe, logout } from "@/lib/api/session";

/** Up to two initials from a display name, or null when there is nothing to take them from. */
function initials(name: string | null): string | null {
  const words = (name ?? "").trim().split(/\s+/).filter(Boolean);
  const letters = words.slice(0, 2).map((w) => Array.from(w)[0] ?? "");
  return letters.join("").toUpperCase() || null;
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

/** The sidebar's account footer: a local session with one Sign in button (the provider choice is
 * the SignInDialog, opened through `onSignIn`), or a signed-in account with a menu to sign out.
 * `trailing` (the theme toggle) sits beside the session line. */
export function AccountMenu({ collapsed = false, onSignIn, trailing }: { collapsed?: boolean; onSignIn: () => void; trailing?: ReactNode }) {
  const client = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: ({ signal }) => getMe(signal), retry: false });
  const out = useMutation({
    mutationFn: logout,
    // Drops every cached query (no stale name or runs); SessionGate then notices the 401 and
    // starts a fresh anonymous (or local) session.
    onSuccess: () => client.resetQueries(),
  });
  const button = useRef<HTMLButtonElement>(null);
  const [menu, setMenu] = useState<{ at: { x: number; y: number }; anchor: HTMLElement } | null>(null);
  const layout = collapsed ? "flex flex-col items-center gap-2" : "flex flex-col gap-2";

  if (!me.data) {
    return (
      <div className={layout}>
        {me.isPending ? (
          <span role="status" aria-label="Loading account" className={`block rounded-md bg-surface-2 ${collapsed ? "size-8" : "h-8 w-full"}`} />
        ) : null}
        {trailing}
      </div>
    );
  }

  const { user, features } = me.data;

  if (user.kind !== "oauth") {
    const canSignIn = features.googleLogin || features.githubLogin;
    if (collapsed) {
      return (
        <div className={layout}>
          {canSignIn ? (
            <button type="button" onClick={onSignIn} aria-label="Sign in" title="Sign in" className="qc-btn-ghost size-8 p-0 pointer-coarse:size-11">
              <Icon name="login" size={16} className="text-accent" />
            </button>
          ) : null}
          {trailing}
        </div>
      );
    }
    return (
      <div className={layout}>
        <div className="flex min-w-0 items-center gap-2 pl-1">
          <Icon name="userCircle" size={16} className="text-faint" />
          <span className="min-w-0 flex-1 truncate text-[13px] text-ink">Local session</span>
          {trailing}
        </div>
        {canSignIn ? (
          <button type="button" onClick={onSignIn} className="qc-btn-secondary h-9 w-full justify-start shadow-sm pointer-coarse:h-11">
            <Icon name="login" size={15} className="text-accent" />
            <span className="flex-1 text-left">Sign in</span>
            <Icon name="chevronRight" size={15} className="text-faint" />
          </button>
        ) : null}
      </div>
    );
  }

  const name = user.displayName?.trim() || "Your account";
  const toggleMenu = () => {
    if (menu) return setMenu(null);
    const anchor = button.current;
    if (!anchor) return;
    const r = anchor.getBoundingClientRect();
    out.reset();
    setMenu({ at: { x: r.left, y: r.top }, anchor });
  };
  const popup = menu ? (
    <ContextMenu
      label="Account"
      at={menu.at}
      anchor={menu.anchor}
      items={[{ id: "sign-out", label: "Sign out", icon: "logout", onSelect: () => out.mutate() }]}
      onClose={() => setMenu(null)}
    />
  ) : null;
  const failed = out.isError ? (
    <p role="alert" className={collapsed ? "sr-only" : "px-1 text-xs text-rejected"}>
      Sign-out failed. Check your connection and try again.
    </p>
  ) : null;
  const trigger = {
    ref: button,
    type: "button" as const,
    onClick: toggleMenu,
    disabled: out.isPending,
    "aria-haspopup": "menu" as const,
    "aria-expanded": !!menu,
    "aria-label": `Account: ${name}`,
  };

  if (collapsed) {
    return (
      <div className={layout}>
        <button {...trigger} title={name} className={`rounded-full disabled:opacity-60 ${out.isError ? "ring-2 ring-rejected" : ""}`}>
          <Avatar name={user.displayName} />
        </button>
        {failed}
        {popup}
        {trailing}
      </div>
    );
  }
  return (
    <div className={layout}>
      <div className="flex min-w-0 items-center gap-1">
        <button {...trigger} className="flex min-w-0 flex-1 items-center gap-2.5 rounded-md p-1.5 text-left hover:bg-hover disabled:cursor-default disabled:opacity-60 aria-expanded:bg-hover">
          <Avatar name={user.displayName} />
          <span className="flex min-w-0 flex-1 flex-col">
            <span className="truncate text-[13px] font-medium text-ink">{name}</span>
            <span className="truncate text-xs text-muted">{out.isPending ? "Signing out…" : "Signed in"}</span>
          </span>
          <Icon name="chevronDown" size={15} className="text-faint" />
        </button>
        {trailing}
      </div>
      {failed}
      {popup}
    </div>
  );
}
