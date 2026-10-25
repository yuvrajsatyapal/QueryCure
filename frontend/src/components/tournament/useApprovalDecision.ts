"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { investigationKeys } from "@/lib/api/investigations";
import { decideApproval, optimizationKeys } from "@/lib/api/optimization";
import type { Approval, DecisionInput } from "@/lib/api/types";
import { decisionOutcome, isRefusal, reviewPhase, type DecisionOutcome } from "@/lib/approval/review";

// setTimeout overflows past ~24.8 days; such deadlines are left to the interval.
const MAX_TIMEOUT_MS = 2 ** 31 - 1;

/** Wall clock for countdowns, refreshed on an interval and once more right after `deadline`, so a
 * request stops being actionable at its expiry time rather than up to one interval later. */
export function useNow(intervalMs = 15_000, deadline?: string): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  useEffect(() => {
    if (!deadline) return;
    const ms = Date.parse(deadline) - Date.now();
    if (!(ms > 0) || ms > MAX_TIMEOUT_MS) return;
    const t = setTimeout(() => setNow(Date.now()), ms + 50);
    return () => clearTimeout(t);
  }, [deadline]);
  return now;
}

/** One approval's selection and decision request, shared by the inline card and the review
 * drawer so both show the same selection and the same pending request. Decisions go only through
 * the existing endpoint; the server stays the authority on what is valid. */
export function useApprovalDecision(approval: Approval, runId: string) {
  const client = useQueryClient();
  const offered = approval.payload.candidates.map((c) => c.candidateId);
  const [chosen, setChosen] = useState<Set<string>>(() => new Set(offered));
  const [mine, setMine] = useState<{ approval: Approval; outcome: DecisionOutcome } | null>(null);
  // The server's message when it refused a decision (409); the request is closed from then on.
  const [refused, setRefused] = useState<string | null>(null);
  // Set synchronously on submit, so a second call in the same tick (double click, Enter then
  // click, card and drawer) cannot send a second request before React re-renders.
  const inFlight = useRef(false);
  const refresh = () => {
    void client.invalidateQueries({ queryKey: optimizationKeys.approvals(runId) });
    void client.invalidateQueries({ queryKey: optimizationKeys.candidates(runId) });
    void client.invalidateQueries({ queryKey: investigationKeys.run(runId), exact: true });
  };
  const decide = useMutation({
    mutationFn: (input: DecisionInput) => decideApproval(approval.id, input),
    onSuccess: (response, input) => {
      setMine({ approval: response, outcome: decisionOutcome(input, response, offered) });
      refresh();
    },
    onError: (error) => {
      // Expired or decided elsewhere: stop offering a decision now, then refetch so the server's
      // own status replaces the refusal. Other failures leave the request open for a retry.
      if (isRefusal(error)) {
        setRefused(error.message);
        refresh();
      } else {
        void client.invalidateQueries({ queryKey: optimizationKeys.approvals(runId) });
      }
    },
    onSettled: () => {
      inFlight.current = false;
    },
  });
  const now = useNow(15_000, approval.expiresAt);
  const phase = reviewPhase(approval, now, mine, refused);
  const submit = (input: DecisionInput) => {
    if (inFlight.current || phase.kind !== "pending") return;
    inFlight.current = true;
    decide.mutate(input);
  };
  const toggle = (id: string) =>
    setChosen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const setAll = (on: boolean) => setChosen(new Set(on ? offered : []));
  return { approval, offered, chosen, toggle, setAll, decide, submit, mine, now, phase };
}

export type ApprovalDecision = ReturnType<typeof useApprovalDecision>;
