import { apiFetch } from "./client";
import type {
  CreateInvestigationInput,
  CreateInvestigationResponse,
  EvidenceDetail,
  FindingsResponse,
  InvestigationDetail,
  InvestigationPage,
  ModelsInfo,
  RunDetail,
  RunPlanList,
} from "./types";

export const investigationKeys = {
  all: ["investigations"] as const,
  list: (params: object) => ["investigations", "list", params] as const,
  detail: (id: string) => ["investigations", id] as const,
  run: (runId: string) => ["runs", runId] as const,
  findings: (runId: string) => ["runs", runId, "findings"] as const,
  plans: (runId: string) => ["runs", runId, "plans"] as const,
  evidence: (runId: string, id: string) => ["runs", runId, "evidence", id] as const,
  events: (runId: string) => ["runs", runId, "events"] as const,
  models: ["settings", "models"] as const,
};

/** One key per submit attempt: a double click or a retried request cannot start two runs. */
export function createInvestigation(
  input: CreateInvestigationInput,
  idempotencyKey: string,
): Promise<CreateInvestigationResponse> {
  return apiFetch("/investigations", {
    method: "POST",
    body: input,
    headers: { "Idempotency-Key": idempotencyKey },
  });
}

export function listInvestigations(
  params: { cursor?: string | null; q?: string; status?: string; outcome?: string; limit?: number },
  signal?: AbortSignal,
): Promise<InvestigationPage> {
  const search = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) search.set(k, String(v));
  const qs = search.toString();
  return apiFetch(`/investigations${qs ? `?${qs}` : ""}`, { signal });
}

export const getInvestigation = (id: string, signal?: AbortSignal) =>
  apiFetch<InvestigationDetail>(`/investigations/${id}`, { signal });
export const deleteInvestigation = (id: string) =>
  apiFetch<void>(`/investigations/${id}`, { method: "DELETE" });
export const restoreInvestigation = (id: string) =>
  apiFetch<InvestigationDetail>(`/investigations/${id}/restore`, { method: "POST" });
export const getRun = (runId: string, signal?: AbortSignal) =>
  apiFetch<RunDetail>(`/runs/${runId}`, { signal });
export const cancelRun = (runId: string) =>
  apiFetch<RunDetail>(`/runs/${runId}/cancel`, { method: "POST" });
export const getFindings = (runId: string, signal?: AbortSignal) =>
  apiFetch<FindingsResponse>(`/runs/${runId}/findings`, { signal });
export const getRunPlans = (runId: string, signal?: AbortSignal) =>
  apiFetch<RunPlanList>(`/runs/${runId}/plans`, { signal });
export const getEvidence = (runId: string, evidenceId: string, signal?: AbortSignal) =>
  apiFetch<EvidenceDetail>(`/runs/${runId}/evidence/${evidenceId}`, { signal });
export const getModels = (signal?: AbortSignal) =>
  apiFetch<ModelsInfo>("/settings/models", { signal });
