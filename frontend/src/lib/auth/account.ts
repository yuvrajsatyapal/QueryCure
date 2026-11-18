import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api/client";
import { createSession, logout } from "@/lib/api/session";

/** First and last initials of a display name, or null when there is nothing to take them from. */
export function initials(name: string | null): string | null {
  const words = (name ?? "").trim().split(/\s+/).filter(Boolean);
  const picked = words.length > 1 ? [words[0], words.at(-1)] : words;
  return (
    picked
      .map((w) => Array.from(w ?? "")[0] ?? "")
      .join("")
      .toUpperCase() || null
  );
}

/** The one sign-out: revokes the session server-side (the CSRF header comes from apiFetch), optionally
 * (`startSession`, for the app shell) starts the replacement local/anonymous session right away, then drops every cached query so no stale name or
 * run survives and the session is read again. Starting the session here, while the account row still
 * shows "Signing out…", spares the app the 401 → create → re-read detour (and its empty gap). */
export function useSignOut({ startSession = false }: { startSession?: boolean } = {}) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      await logout();
      if (!startSession) return;
      try {
        await createSession();
      } catch (error) {
        // A restricted trial offers no anonymous session (ADR-0031), and any other failure is retried;
        // SessionGate owns both cases once the queries reset, so the sign-out itself still succeeded.
        if (!(error instanceof ApiError)) throw error;
      }
    },
    onSuccess: () => client.resetQueries(),
  });
}
