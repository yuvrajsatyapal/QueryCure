"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { ErrorNotice } from "@/components/common/ErrorNotice";
import { PlanTreeTable } from "@/components/plan/PlanTreeTable";
import { ReportView } from "@/components/report/ReportView";
import { demoKeys, getDemo, verifyDemo } from "@/lib/api/demo";
import type { ReportV1 } from "@/lib/report/types";
import { PrerecordedBanner } from "./PrerecordedBanner";

export function DemoDetailView({ slug }: { slug: string }) {
  const demo = useQuery({ queryKey: demoKeys.detail(slug), queryFn: ({ signal }) => getDemo(slug, signal), retry: false });
  const [checking, setChecking] = useState(false);
  const verification = useQuery({
    queryKey: demoKeys.verification(slug),
    queryFn: ({ signal }) => verifyDemo(slug, signal),
    enabled: checking,
  });
  if (demo.error) return <ErrorNotice error={demo.error} />;
  if (!demo.data) return <p className="text-muted">Loading…</p>;
  const d = demo.data;
  const plan = d.plans[0];
  return (
    <div className="flex flex-col gap-6">
      <Link href="/demo" className="text-sm text-link">
        ← Demo gallery
      </Link>
      <PrerecordedBanner label={d.label} />
      <section aria-label="Integrity" className="flex flex-col gap-2 qc-panel p-4 text-sm">
        <p>
          Manifest <span className="font-mono">sha256:{d.manifestSha256.slice(0, 16)}…</span> · run <span className="font-mono">{d.runId.slice(0, 8)}</span>
        </p>
        <button type="button" onClick={() => setChecking(true)} className="w-fit qc-btn-secondary">
          Check stored digests
        </button>
        {verification.data ? (
          <div role="status">
            <p className={verification.data.status === "consistent" ? "text-verified" : "text-rejected"}>
              {verification.data.status === "consistent"
                ? `All ${verification.data.checks.length} shipped artifacts match the manifest.`
                : "Some shipped artifacts do not match the manifest."}
            </p>
            <p className="text-xs text-muted">{verification.data.scope}</p>
          </div>
        ) : null}
        <ErrorNotice error={verification.error} />
      </section>
      <ReportView report={d.report as unknown as ReportV1} toc />
      {plan ? (
        <section aria-label="Plan explorer" className="flex flex-col gap-2">
          <h2 className="font-medium">Execution plan ({plan.role === "context.plan" ? "sandbox EXPLAIN" : "uploaded"})</h2>
          <PlanTreeTable plan={plan.plan} metrics={plan.metrics} />
        </section>
      ) : null}
    </div>
  );
}
