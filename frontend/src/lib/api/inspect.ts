import { apiFetch } from "./client";
import type { PlanInspection, SqlAnalysis } from "./types";

/** The plan text is sent verbatim: PostgreSQL keys ("Node Type") must not be case-converted. */
export function inspectPlan(planJson: string): Promise<PlanInspection> {
  return apiFetch<PlanInspection>("/inspect/plan", { method: "POST", rawJsonBody: planJson });
}

export function inspectSql(query: string): Promise<SqlAnalysis> {
  return apiFetch<SqlAnalysis>("/inspect/sql", { method: "POST", body: { query } });
}
