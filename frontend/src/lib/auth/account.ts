import { useMutation, useQueryClient } from "@tanstack/react-query";
import { logout } from "@/lib/api/session";

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

/** The one sign-out: revokes the session server-side (the CSRF header comes from apiFetch), then drops
 * every cached query so no stale name or run survives and the session is read again. */
export function useSignOut() {
  const client = useQueryClient();
  return useMutation({ mutationFn: logout, onSuccess: () => client.resetQueries() });
}
