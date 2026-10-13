"use client";

import { useQueries } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { getEvidence, investigationKeys } from "@/lib/api/investigations";

export interface LineageSource {
  /** What the claim is ("Speed-up 12.4×", "Hypothesis: missing_index", "Check rescore"). */
  claim: string;
  /** Who produced it: measured, derived, agent claim… (never colour alone). */
  provenance: string;
  evidenceIds: string[];
  /** For measurements: the stored artifact and JSON pointer the number was read from. */
  artifact?: { sha256: string; pointer: string; label: string } | null;
}

/** "Why?": walks a claim back to its evidence, the artifact each piece of evidence points into,
 * and for plan nodes the node itself (REPLAY_ENGINE §3 lineage DAG). */
export function LineageDrawer({
  runId,
  source,
  onClose,
  onPlanNode,
}: {
  runId: string;
  source: LineageSource;
  onClose: () => void;
  onPlanNode?: (artifactSha256: string, nodeId: number) => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const details = useQueries({
    queries: source.evidenceIds.map((id) => ({
      queryKey: investigationKeys.evidence(runId, id),
      queryFn: ({ signal }: { signal: AbortSignal }) => getEvidence(runId, id, signal),
    })),
  });
  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <aside
      role="dialog"
      aria-modal="false"
      aria-label="Why: lineage of this claim"
      className="fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col gap-3 overflow-y-auto border-l border-border bg-surface p-4 shadow-lg"
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-mono text-[11px] uppercase tracking-wider text-muted">Why? · lineage</p>
          <h2 className="text-base font-semibold">{source.claim}</h2>
          <p className="text-xs text-muted">Source: {source.provenance}</p>
        </div>
        <button ref={closeRef} type="button" onClick={onClose} className="rounded-md border border-border px-2 py-1 text-sm">
          Close
        </button>
      </div>
      {source.artifact ? (
        <section aria-label="Stored artifact" className="rounded-md border border-border bg-surface-2 p-3 text-sm">
          <p className="font-medium">{source.artifact.label}</p>
          <p className="break-all font-mono text-[11px] text-muted">sha256:{source.artifact.sha256}</p>
          <p className="font-mono text-[11px] text-muted">pointer {source.artifact.pointer}</p>
        </section>
      ) : null}
      {source.evidenceIds.length === 0 ? (
        <p className="text-sm text-muted">This claim cites no evidence: it is derived from the stored records shown above.</p>
      ) : (
        <ol className="flex flex-col gap-2" aria-label="Cited evidence">
          {source.evidenceIds.map((id, i) => {
            const q = details[i];
            const d = q?.data;
            const nodeId = d ? (d.evidence.data as { nodeId?: unknown }).nodeId : undefined;
            return (
              <li key={id} className="rounded-md border border-border p-3 text-sm">
                <p className="font-mono text-xs">
                  {id}
                  {d ? ` · ${d.evidence.kind} · ${d.evidence.provenance}` : ""}
                </p>
                {q?.isLoading ? <p className="text-muted">Loading…</p> : null}
                {q?.error ? <p className="text-rejected">This evidence could not be loaded.</p> : null}
                {d ? (
                  <>
                    <p className="mt-1">{d.evidence.summary}</p>
                    {d.artifact ? (
                      <p className="mt-1 break-all font-mono text-[11px] text-muted">
                        {d.artifact.kind} sha256:{d.artifact.sha256} · {d.evidence.locator}
                      </p>
                    ) : (
                      <p className="mt-1 font-mono text-[11px] text-muted">no source artifact · {d.evidence.locator}</p>
                    )}
                    {d.citedByHypotheses.length + d.citedByFindings.length > 0 ? (
                      <p className="mt-1 text-xs text-muted">
                        Cited by {d.citedByHypotheses.length} hypothesis(es), {d.citedByFindings.length} finding(s)
                      </p>
                    ) : null}
                    {onPlanNode && d.evidence.kind === "plan_node" && d.artifact && typeof nodeId === "number" ? (
                      <button
                        type="button"
                        onClick={() => onPlanNode(d.artifact?.sha256 ?? "", nodeId)}
                        className="mt-2 rounded-md border border-border-strong px-2 py-1 text-xs text-link"
                      >
                        Show node {nodeId} in the plan
                      </button>
                    ) : null}
                  </>
                ) : null}
              </li>
            );
          })}
        </ol>
      )}
    </aside>
  );
}
