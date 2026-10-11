import { apiFetch } from "./client";
import type {
  ConnectionList,
  ConnectionSummary,
  ConnectionTestResult,
  CreateConnectionInput,
  ExplainResult,
} from "./types";

export const connectionKeys = { all: ["connections"] as const };

export function listConnections(signal?: AbortSignal): Promise<ConnectionList> {
  return apiFetch<ConnectionList>("/connections", { signal });
}

export function createConnection(input: CreateConnectionInput): Promise<ConnectionSummary> {
  return apiFetch<ConnectionSummary>("/connections", {
    method: "POST",
    body: { ...input, purpose: "inspection" },
  });
}

export function testConnection(id: string): Promise<ConnectionTestResult> {
  return apiFetch<ConnectionTestResult>(`/connections/${encodeURIComponent(id)}/test`, {
    method: "POST",
  });
}

export function deleteConnection(id: string): Promise<void> {
  return apiFetch<void>(`/connections/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function explainOnConnection(id: string, query: string): Promise<ExplainResult> {
  return apiFetch<ExplainResult>(`/connections/${encodeURIComponent(id)}/explain`, {
    method: "POST",
    body: { query },
  });
}
