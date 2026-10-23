"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ErrorNotice } from "@/components/common/ErrorNotice";
import { Icon } from "@/components/ui/Icon";
import { StatusPill } from "@/components/ui/StatusPill";
import { investigationKeys } from "@/lib/api/investigations";
import { decideApproval, optimizationKeys } from "@/lib/api/optimization";
import type { Approval, DecisionInput } from "@/lib/api/types";
import { describeCandidate } from "@/lib/benchmark/candidate";

/** The human-in-the-loop step (AGENT_SYSTEM §8): shows exactly the SQL that will run in the
 * sandbox. Nothing runs until one of these buttons records a decision. */
export function ApprovalCard({ approval, runId }: { approval: Approval; runId: string }) {
  const client = useQueryClient();
  const candidates = approval.payload.candidates;
  const [chosen, setChosen] = useState<Set<string>>(() => new Set(candidates.map((c) => c.candidateId)));
  const decide = useMutation({
    mutationFn: (input: DecisionInput) => decideApproval(approval.id, input),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: optimizationKeys.approvals(runId) });
      void client.invalidateQueries({ queryKey: optimizationKeys.candidates(runId) });
      void client.invalidateQueries({ queryKey: investigationKeys.run(runId), exact: true });
    },
  });
  const toggle = (id: string) =>
    setChosen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const all = chosen.size === candidates.length;

  return (
    <section aria-label="Approval required" className="flex flex-col gap-3 rounded-lg border border-approval/40 bg-surface p-4 shadow-[inset_3px_0_0_var(--approval)]">
      <div className="flex flex-col gap-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="flex size-7 items-center justify-center rounded-md bg-approval/10 text-approval">
            <Icon name="hand" size={15} />
          </span>
          <h2 className="text-base font-semibold">Approve sandbox experiment · round {approval.round + 1}</h2>
          <StatusPill tone="approval" label="Waiting on you" />
        </div>
        <p className="text-sm text-muted">
          The SQL below would run only in {approval.payload.sandbox}, on workload{" "}
          <span className="font-mono">{approval.payload.workloadId}</span>. Nothing has run yet. Expires{" "}
          {new Date(approval.expiresAt).toLocaleString()}. If the measurements are too noisy to decide, the same approved SQL
          may be re-measured up to two more times in new disposable clones.
        </p>
      </div>
      <ul className="flex flex-col gap-2">
        {candidates.map((c) => (
          <li key={c.candidateId} className="rounded-md border border-border bg-surface-2 p-3 has-[:checked]:border-border-strong">
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                checked={chosen.has(c.candidateId)}
                onChange={() => toggle(c.candidateId)}
                aria-label={`Include ${c.key}`}
                className="mt-1 accent-[var(--accent)]"
              />
              <span className="flex min-w-0 flex-col gap-1">
                <span>
                  <span className="font-medium">{describeCandidate({ kind: c.kind, ddl: c.ddl, querySql: c.querySql })}</span>{" "}
                  <span className="font-mono text-xs text-muted">{c.key}</span>
                </span>
                <code className="block whitespace-pre-wrap break-words rounded border border-border bg-surface px-2 py-1.5 font-mono text-xs">
                  {(c.ddl.length ? c.ddl : [c.querySql ?? ""]).join(";\n")}
                </code>
                <span className="text-xs text-muted">{c.expectedBenefit}</span>
                {c.risks.length ? <span className="text-xs text-inconclusive">Risks: {c.risks.join("; ")}</span> : null}
              </span>
            </label>
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted">
        Baseline query and {approval.payload.paramSets.length} parameter set(s) are benchmarked alongside. Results are
        verified only within the tested data, parameters and sandbox.
      </p>
      <ErrorNotice error={decide.error} />
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={decide.isPending || chosen.size === 0}
          onClick={() =>
            decide.mutate(
              all ? { decision: "approve", candidateIds: [] } : { decision: "partial", candidateIds: [...chosen] },
            )
          }
          className="qc-btn-primary"
        >
          {all ? "Approve and run" : `Approve ${chosen.size} selected`}
        </button>
        <button
          type="button"
          disabled={decide.isPending}
          onClick={() => decide.mutate({ decision: "decline", candidateIds: [] })}
          className="qc-btn-secondary"
        >
          Decline
        </button>
      </div>
    </section>
  );
}
