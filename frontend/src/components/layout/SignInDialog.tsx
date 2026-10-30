"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useModal } from "@/components/command/useModal";
import { Icon } from "@/components/ui/Icon";
import { ProviderIcon, type Provider } from "@/components/ui/ProviderIcon";
import { API_BASE_URL } from "@/lib/api/client";
import { getMe } from "@/lib/api/session";

const PROVIDERS: { id: Provider; label: string; flag: "googleLogin" | "githubLogin" }[] = [
  { id: "google", label: "Google", flag: "googleLogin" },
  { id: "github", label: "GitHub", flag: "githubLogin" },
];

/** The provider choice behind the sidebar's Sign in button. Each option is a plain link to the
 * API's existing login route, which runs the OAuth flow (state, PKCE) and redirects back to
 * `return_to`; a refused or failed sign-in comes back as `?auth_error=`, shown by SessionGate.
 * Rendered in a portal so neither the sidebar's scroll nor the mobile drawer can cover it. */
export function SignInDialog({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDivElement>(null);
  const me = useQuery({ queryKey: ["me"], queryFn: ({ signal }) => getMe(signal), retry: false });
  // Navigation to the provider has started: further clicks would only start a second flow.
  const [pending, setPending] = useState<Provider | null>(null);
  useModal(dialog, onClose);

  const ready = me.isSuccess;
  // First provider once the options are known (they normally are: the sidebar read /me already).
  useEffect(() => {
    const root = dialog.current;
    (root?.querySelector<HTMLElement>("a[href]") ?? root?.querySelector<HTMLElement>("button"))?.focus();
  }, [ready]);
  useEffect(() => {
    // Coming back with the browser's Back button can restore this page from the bfcache.
    const restored = (e: PageTransitionEvent) => {
      if (e.persisted) setPending(null);
    };
    window.addEventListener("pageshow", restored);
    return () => window.removeEventListener("pageshow", restored);
  }, []);

  const features = me.data?.features;
  const providers = PROVIDERS.filter((p) => features?.[p.flag]);
  const returnTo = window.location.pathname;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[12vh]">
      <div aria-hidden="true" onClick={onClose} className="absolute inset-0 bg-[var(--scrim)]" />
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="sign-in-title"
        aria-describedby="sign-in-description"
        className="relative w-full max-w-sm rounded-xl border border-border bg-surface p-5 shadow-pop"
      >
        <div className="flex items-start justify-between gap-3">
          <h2 id="sign-in-title" className="text-base font-semibold text-ink">
            Sign in to QueryCure
          </h2>
          <button type="button" onClick={onClose} aria-label="Close sign-in" className="qc-btn-ghost -mt-1 -mr-1 size-8 p-0 pointer-coarse:size-11">
            <Icon name="close" size={16} />
          </button>
        </div>
        <p id="sign-in-description" className="mt-1 text-sm text-muted">
          Choose how you&apos;d like to continue.
        </p>
        <div className="mt-4 flex flex-col gap-2">
          {providers.map((p) => (
            <a
              key={p.id}
              href={`${API_BASE_URL}/api/v1/auth/${p.id}/login?return_to=${encodeURIComponent(returnTo)}`}
              aria-disabled={pending ? true : undefined}
              onClick={(e) => {
                if (pending) e.preventDefault();
                else setPending(p.id);
              }}
              className="qc-btn-secondary h-11 w-full justify-center text-sm aria-disabled:cursor-default aria-disabled:opacity-60"
            >
              {pending === p.id ? <Icon name="loader" size={16} className="motion-safe:animate-spin" /> : <ProviderIcon provider={p.id} />}
              {pending === p.id ? `Redirecting to ${p.label}…` : `Continue with ${p.label}`}
            </a>
          ))}
          {me.isSuccess && !providers.length ? <p className="text-sm text-muted">Sign-in is not configured for this deployment.</p> : null}
        </div>
        <p className="mt-4 text-center text-xs text-muted">QueryCure never sees your password. You&apos;ll come back to this page afterwards.</p>
      </div>
    </div>,
    document.body,
  );
}
