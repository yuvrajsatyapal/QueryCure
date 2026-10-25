"use client";

import { useRef } from "react";
import type { Approval, Hypothesis, OptimizationCandidate } from "@/lib/api/types";
import { ApprovalCard } from "./ApprovalCard";
import { ApprovalDrawer } from "./ApprovalDrawer";
import { useApprovalDecision } from "./useApprovalDecision";

/** The inline approval card plus its review drawer, sharing one selection and one decision
 * request. The drawer stays open after a decision (showing the result) even though the card,
 * shown only while the request is pending, has gone. Key it by approval id. */
export function ApprovalReview({
  approval,
  runId,
  showCard,
  open,
  onOpen,
  onClose,
  investigationTitle,
  candidates,
  hypotheses,
  onEvidence,
}: {
  approval: Approval;
  runId: string;
  showCard: boolean;
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
  investigationTitle: string;
  candidates: OptimizationCandidate[];
  hypotheses: Hypothesis[];
  onEvidence: (id: string) => void;
}) {
  const review = useApprovalDecision(approval, runId);
  const opener = useRef<HTMLButtonElement>(null);
  return (
    <>
      {showCard ? <ApprovalCard approval={approval} runId={runId} review={review} onReview={onOpen} reviewRef={opener} /> : null}
      {open ? (
        <ApprovalDrawer
          review={review}
          investigationTitle={investigationTitle}
          candidates={candidates}
          hypotheses={hypotheses}
          onClose={onClose}
          onEvidence={onEvidence}
        />
      ) : null}
    </>
  );
}
