"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { Icon } from "@/components/ui/Icon";
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
/** Links between this report, its run, the replay page and related runs, from the sealed report
 * itself (UI_UX §3.11). Only links the report states are shown. */
function ReplayNav({ runId, report }: { runId: string; report: ReportV1 }) {
  const original = report.replay?.replayOf?.runId ?? null;
  const parent = report.run.parentRunId;
  const link = "flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted no-underline hover:bg-hover hover:text-ink";
  return (
    <nav aria-label="Report navigation" className="flex flex-wrap items-center gap-1 rounded-lg border border-border bg-surface p-1 print:hidden">
      <Link className={link} href={`/app/investigations/${report.run.investigationId}?run=${runId}`}>
        <Icon name="node" size={13} />
        Open the run
      </Link>
      <Link className={link} href={`/app/replay/${runId}`}>
        <Icon name="replay" size={13} />
        Reproducibility & replay
      </Link>
      {original ? (
        <Link className={link} href={`/app/reports/${original}`}>
          <Icon name="report" size={13} />
          Original run&apos;s report
        </Link>
      ) : null}
      {parent && parent !== original ? (
        <Link className={link} href={`/app/investigations/${report.run.investigationId}?run=${parent}`}>
          <Icon name="arrowRight" size={13} className="rotate-180" />
          Parent run
        </Link>
      ) : null}
    </nav>
  );
}

export function ReportPanel({
  runId,
  onPlanNode,
  standalone = false,
}: {
  runId: string;
  onPlanNode?: (artifactSha256: string, nodeId: number) => void;
  /** The /app/reports page: breadcrumb, replay navigation and a contents list. */
  standalone?: boolean;
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
  const sealed = unsupported ? null : (report.data.report as unknown as ReportV1);

  return (
    <div className="flex flex-col gap-4">
      {standalone && sealed ? (
        <>
          <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 text-xs text-muted print:hidden">
            <Link href="/app/history" className="shrink-0 hover:text-ink">
              Investigations
            </Link>
            <Icon name="chevronRight" size={12} />
            <Link href={`/app/investigations/${sealed.run.investigationId}?run=${runId}`} className="truncate hover:text-ink">
              {sealed.investigation.title}
            </Link>
            <Icon name="chevronRight" size={12} />
            <span className="shrink-0 text-ink">Report · run {sealed.run.runNumber}</span>
          </nav>
          <ReplayNav runId={runId} report={sealed} />
        </>
      ) : null}
      <div className="flex flex-wrap items-center gap-2 print:hidden">
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
        <ReportView report={report.data.report as unknown as ReportV1} onWhy={setWhy} toc={standalone} />
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
