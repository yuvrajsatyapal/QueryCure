"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ErrorNotice } from "@/components/common/ErrorNotice";
import { LineageDrawer, type LineageSource } from "@/components/lineage/LineageDrawer";
import { ApiError } from "@/lib/api/client";
import {
  SUPPORTED_REPORT_SCHEMAS,
  getReport,
  getReportMarkdown,
  reportExportUrl,
  reportKeys,
  verifyReport,
} from "@/lib/api/reports";
import { REPLAY_CODE_TEXT, REPORT_REPLAY_STATUS } from "@/lib/report/labels";
import type { ReportV1 } from "@/lib/report/types";
import { ReportView } from "./ReportView";

/** Report tab / page: the stored, digest-verified report JSON rendered for reading; the stored
 * Markdown when this client does not know the report schema (REPLAY_ENGINE §7 rule 4). */
export function ReportPanel({
  runId,
  onPlanNode,
}: {
  runId: string;
  onPlanNode?: (artifactSha256: string, nodeId: number) => void;
}) {
  const [why, setWhy] = useState<LineageSource | null>(null);
  const report = useQuery({ queryKey: reportKeys.report(runId), queryFn: ({ signal }) => getReport(runId, signal), retry: false });
  const unsupported = report.data ? !SUPPORTED_REPORT_SCHEMAS.includes(report.data.reportSchemaVersion) : false;
  const markdown = useQuery({
    queryKey: reportKeys.markdown(runId),
    queryFn: ({ signal }) => getReportMarkdown(runId, signal),
    enabled: unsupported,
  });
  const verify = useMutation({ mutationFn: () => verifyReport(runId) });

  if (report.isLoading) return <p className="text-muted">Loading report…</p>;
  if (report.error instanceof ApiError && report.error.code === "NOT_FINALIZED") {
    return (
      <p className="qc-panel p-6 text-muted">
        The final report is written when the run ends. Runs created before Phase 4 are never sealed and only show their interim findings.
      </p>
    );
  }
  if (report.error) return <ErrorNotice error={report.error} />;
  if (!report.data) return null;
  const attempt = verify.data;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <a href={reportExportUrl(runId, "md")} className="qc-btn-secondary" download>
          Export Markdown
        </a>
        <a href={reportExportUrl(runId, "json")} className="qc-btn-secondary" download>
          Export JSON
        </a>
        <button
          type="button"
          onClick={() => verify.mutate()}
          disabled={verify.isPending}
          className="qc-btn-secondary text-accent"
        >
          {verify.isPending ? "Verifying…" : "Verify report"}
        </button>
        <span className="break-all font-mono text-[11px] text-muted">manifest sha256:{report.data.manifestSha256.slice(0, 16)}…</span>
      </div>
      <ErrorNotice error={verify.error} />
      {attempt ? (
        <section aria-label="Report verification" className="rounded-md border border-border bg-surface-2 p-3 text-sm">
          <p className={`font-medium ${attempt.status.startsWith("verified") ? "text-verified" : "text-rejected"}`}>
            {REPORT_REPLAY_STATUS[attempt.status] ?? attempt.status}
          </p>
          {attempt.failureCode ? <p>{REPLAY_CODE_TEXT[attempt.failureCode] ?? attempt.failureCode}</p> : null}
          {attempt.warnings.map((w) => (
            <p key={w} className="text-xs text-inconclusive">
              Warning: {w.replaceAll("_", " ")}
            </p>
          ))}
          <ul className="mt-1 text-xs">
            {((attempt.result as { checks?: { name: string; status: string; code: string | null; detail: string }[] }).checks ?? []).map((c) => (
              <li key={`${c.name}:${c.code ?? ""}`}>
                {c.status === "ok" ? "✓" : c.status === "failed" ? "✕" : "–"} {c.name.replaceAll("_", " ")}
                {c.code ? ` · ${c.code}` : ""} {c.detail ? <span className="text-muted">{c.detail}</span> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {unsupported ? (
        <section aria-label="Archived report" className="flex flex-col gap-2">
          <p role="note" className="rounded-md border border-inconclusive p-2 text-sm text-inconclusive">
            {report.data.reportSchemaVersion > Math.max(...SUPPORTED_REPORT_SCHEMAS)
              ? "This report was written by a newer version than this page understands; showing the stored Markdown."
              : "Archived format: showing the stored Markdown."}
          </p>
          <pre className="whitespace-pre-wrap rounded-md border border-border bg-surface p-3 font-mono text-xs">{markdown.data ?? "Loading…"}</pre>
        </section>
      ) : (
        <ReportView report={report.data.report as unknown as ReportV1} onWhy={setWhy} />
      )}
      {why ? (
        <LineageDrawer
          runId={runId}
          source={why}
          onClose={() => setWhy(null)}
          onPlanNode={
            onPlanNode
              ? (sha, node) => {
                  setWhy(null);
                  onPlanNode(sha, node);
                }
              : undefined
          }
        />
      ) : null}
    </div>
  );
}
