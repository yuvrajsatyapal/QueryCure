import { apiFetch } from "./client";
import type {
  Approval,
  ApprovalList,
  CandidateList,
  DecisionInput,
  ExperimentDetail,
  ExperimentList,
  WorkloadCatalog,
} from "./types";

export const optimizationKeys = {
  candidates: (runId: string) => ["runs", runId, "candidates"] as const,
  approvals: (runId: string) => ["runs", runId, "approvals"] as const,
  experiments: (runId: string) => ["runs", runId, "experiments"] as const,
  experiment: (id: string) => ["experiments", id] as const,
  workloads: ["workloads"] as const,
};

export const getCandidates = (runId: string, signal?: AbortSignal) =>
  apiFetch<CandidateList>(`/runs/${runId}/candidates`, { signal });
export const getApprovals = (runId: string, signal?: AbortSignal) =>
  apiFetch<ApprovalList>(`/runs/${runId}/approvals`, { signal });
export const getExperiments = (runId: string, signal?: AbortSignal) =>
  apiFetch<ExperimentList>(`/runs/${runId}/experiments`, { signal });
export const getExperiment = (id: string, signal?: AbortSignal) =>
  apiFetch<ExperimentDetail>(`/experiments/${id}`, { signal });
export const listWorkloads = (signal?: AbortSignal) =>
  apiFetch<WorkloadCatalog>("/workloads", { signal });

/** Human-in-the-loop: the only path by which candidate SQL can reach the sandbox. */
export const decideApproval = (approvalId: string, input: DecisionInput) =>
  apiFetch<Approval>(`/approvals/${approvalId}/decision`, { method: "POST", body: input });
