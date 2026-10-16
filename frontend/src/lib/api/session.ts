import { apiFetch } from "./client";
import type { Me } from "./types";

export function getMe(signal?: AbortSignal): Promise<Me> {
  return apiFetch<Me>("/me", { signal });
}

export function createSession(): Promise<unknown> {
  return apiFetch("/session", { method: "POST" });
}

/** Revokes the session server-side; the CSRF header comes from apiFetch. */
export function logout(): Promise<void> {
  return apiFetch<void>("/auth/logout", { method: "POST" });
}
