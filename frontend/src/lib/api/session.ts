import { apiFetch } from "./client";
import type { Me } from "./types";

export function getMe(signal?: AbortSignal): Promise<Me> {
  return apiFetch<Me>("/me", { signal });
}

export function createSession(): Promise<unknown> {
  return apiFetch("/session", { method: "POST" });
}
