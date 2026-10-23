import { apiFetch } from "./client";
import type { AuthOptions, Me } from "./types";

export function getMe(signal?: AbortSignal): Promise<Me> {
  return apiFetch<Me>("/me", { signal });
}

/** Public: which sign-in providers exist and whether access is restricted (ADR-0031). */
export function getAuthOptions(signal?: AbortSignal): Promise<AuthOptions> {
  return apiFetch<AuthOptions>("/auth/options", { signal });
}

export function createSession(): Promise<unknown> {
  return apiFetch("/session", { method: "POST" });
}

/** Revokes the session server-side; the CSRF header comes from apiFetch. */
export function logout(): Promise<void> {
  return apiFetch<void>("/auth/logout", { method: "POST" });
}
