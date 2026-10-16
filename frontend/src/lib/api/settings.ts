import { apiFetch } from "./client";
import type { LlmCredential, LlmCredentialList } from "./types";

export const settingsKeys = {
  credentials: ["settings", "llm-credentials"] as const,
  models: ["settings", "models"] as const,
};

export const listCredentials = (signal?: AbortSignal) =>
  apiFetch<LlmCredentialList>("/settings/llm-credentials", { signal });

/** The key goes to the API once; it is never returned, only its last 4 characters. */
export const addCredential = (input: { apiKey: string; defaultModel?: string }) =>
  apiFetch<LlmCredential>("/settings/llm-credentials", {
    method: "POST",
    body: { provider: "openrouter", apiKey: input.apiKey, defaultModel: input.defaultModel || null },
  });

export const deleteCredential = (id: string) =>
  apiFetch<void>(`/settings/llm-credentials/${id}`, { method: "DELETE" });
