import { API_BASE_URL, apiFetch } from "./client";
import type {
  CreateInvestigationResponse,
  ManifestOut,
  PlanDiffOut,
  ReplayAttempt,
  ReplayAttemptPage,
  ReportOut,
  VerificationList,
} from "./types";

export const reportKeys = {
  report: (runId: string) => ["runs", runId, "report"] as const,
  markdown: (runId: string) => ["runs", runId, "report.md"] as const,
  manifest: (runId: string) => ["runs", runId, "manifest"] as const,
  attempts: (runId: string) => ["runs", runId, "replay-attempts"] as const,
  attempt: (id: string) => ["replay-attempts", id] as const,
  verifications: (runId: string) => ["runs", runId, "verifications"] as const,
  planDiff: (runId: string, from: string, to: string) => ["runs", runId, "plan-diff", from, to] as const,
};

/** Report schema versions this client renders; others show the stored Markdown (REPLAY_ENGINE §7). */
export const SUPPORTED_REPORT_SCHEMAS = [1];

export const getReport = (runId: string, signal?: AbortSignal) =>
  apiFetch<ReportOut>(`/runs/${runId}/report`, { signal });
export const getManifest = (runId: string, signal?: AbortSignal) =>
  apiFetch<ManifestOut>(`/runs/${runId}/replay/manifest`, { signal });
export const getVerifications = (runId: string, signal?: AbortSignal) =>
  apiFetch<VerificationList>(`/runs/${runId}/verifications`, { signal });
export const getPlanDiff = (runId: string, from: string, to: string, signal?: AbortSignal) =>
  apiFetch<PlanDiffOut>(`/runs/${runId}/plans/diff?from=${from}&to=${to}`, { signal });

/** Export URLs (the API answers with an attachment; the cookie session authorizes the download). */
export const reportExportUrl = (runId: string, format: "md" | "json") =>
  `${API_BASE_URL}/api/v1/runs/${runId}/report.${format}`;

/** The stored Markdown, for report schemas this client cannot render. */
export async function getReportMarkdown(runId: string, signal?: AbortSignal): Promise<string> {
  const response = await fetch(reportExportUrl(runId, "md"), { credentials: "include", signal });
  if (!response.ok) throw new Error("The stored Markdown report could not be loaded.");
  return (await response.text()).split("<!-- qc-export-footer -->")[0] ?? "";
}

/** Report replay: synchronous, no LLM, no SQL. */
export const verifyReport = (runId: string) =>
  apiFetch<ReplayAttempt>(`/runs/${runId}/replay/report`, {
    method: "POST",
    body: { clientSchemaVersions: SUPPORTED_REPORT_SCHEMAS },
  });
export const listReplayAttempts = (runId: string, signal?: AbortSignal) =>
  apiFetch<ReplayAttemptPage>(`/runs/${runId}/replay/attempts?limit=50`, { signal });
export const getReplayAttempt = (id: string, signal?: AbortSignal) =>
  apiFetch<ReplayAttempt>(`/replay-attempts/${id}`, { signal });
/** Experiment replay: the confirmation is the approval of the exact SQL shown to the user. */
export const replayExperiment = (experimentId: string) =>
  apiFetch<ReplayAttempt>(`/experiments/${experimentId}/replay`, {
    method: "POST",
    body: { confirmDdl: true },
  });
export const cancelReplayAttempt = (id: string) =>
  apiFetch<ReplayAttempt>(`/replay-attempts/${id}/cancel`, { method: "POST" });
/** A new LLM run on the same inputs: never started by a replay, always by explicit consent. */
export const reinvestigate = (investigationId: string, idempotencyKey: string) =>
  apiFetch<CreateInvestigationResponse>(`/investigations/${investigationId}/reinvestigate`, {
    method: "POST",
    body: { confirmNewLlmRun: true },
    headers: { "Idempotency-Key": idempotencyKey },
  });
