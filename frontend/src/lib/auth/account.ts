import { useMutation, useQueryClient } from "@tanstack/react-query";
import { logout } from "@/lib/api/session";
import { goHome } from "./navigate";
import { sleep, STEP_MS } from "./pacing";

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

/** The one sign-out: revokes the session server-side (the CSRF header comes from apiFetch). By default it
 * then drops every cached query so no stale name or run survives and the session is read again (the
 * landing page). With `toHome` (the app shell) it instead loads the home page afresh, which discards
 * the whole in-memory cache, so the app never shows a half-signed-out state on the way. */
export function useSignOut({ toHome = false }: { toHome?: boolean } = {}) {
  const client = useQueryClient();
  return useMutation({
    // The screen of the app shell is paced like the sign-in one: the request is not shown for less than a step.
    mutationFn: async () => {
      if (!toHome) return logout();
      const [result] = await Promise.all([logout(), sleep(STEP_MS)]);
      return result;
    },
    // Not awaited: the mutation must read as succeeded meanwhile, so the screen shows its second step.
    onSuccess: () => {
      if (toHome) setTimeout(goHome, STEP_MS);
      else void client.resetQueries();
    },
  });
}
