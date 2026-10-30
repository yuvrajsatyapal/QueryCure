"use client";

import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { ErrorNotice } from "@/components/common/ErrorNotice";
import { deleteInvestigation, listInvestigations, restoreInvestigation } from "@/lib/api/investigations";
import type { InvestigationSummary } from "@/lib/api/types";
import { Icon } from "@/components/ui/Icon";
import { groupByDay } from "@/lib/investigations/grouping";
import { useCachedReplayReports } from "@/lib/report/useCachedReplayReports";
import { InvestigationRow } from "./InvestigationRow";

const STATUSES = ["", "queued", "running", "awaiting_approval", "completed", "failed", "cancelled"] as const;
// Server-side filters only (UI_UX §3.9): the endpoint filters by latest-run status and outcome.
const OUTCOMES = ["", "verified_recommendation", "unverified_recommendations", "no_action_needed", "inconclusive"] as const;
const words = (v: string) => v.replaceAll("_", " ");
const PAGE = 20;

export function HistoryView() {
  const client = useQueryClient();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<(typeof STATUSES)[number]>("");
  const [outcome, setOutcome] = useState<(typeof OUTCOMES)[number]>("");
  const [deleted, setDeleted] = useState<InvestigationSummary | null>(null);
  const params = { q: q.trim() || undefined, status: status || undefined, outcome: outcome || undefined, limit: PAGE };
  const filtered = Boolean(q.trim() || status || outcome);

  const list = useInfiniteQuery({
    queryKey: ["investigations", "list", params],
    queryFn: ({ pageParam, signal }) => listInvestigations({ ...params, cursor: pageParam }, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.nextCursor ?? undefined,
  });
  const refresh = () => client.invalidateQueries({ queryKey: ["investigations"] });
  const remove = useMutation({
    mutationFn: (item: InvestigationSummary) => deleteInvestigation(item.id),
    onSuccess: (_, item) => {
      setDeleted(item);
      void refresh();
    },
  });
  const undo = useMutation({
    mutationFn: (item: InvestigationSummary) => restoreInvestigation(item.id),
    onSuccess: () => {
      setDeleted(null);
      void refresh();
    },
  });

  const items = list.data?.pages.flatMap((p) => p.items) ?? [];
  const replayReports = useCachedReplayReports(items.map((i) => i.latestRun));
  // The endpoint filters by the latest run's stored outcome. A replay is never a latest run today
  // (§18.2); should that change, say why it matches a "verified" filter.
  const replayMatches = outcome === "verified_recommendation" && items.some((i) => i.latestRun?.kind === "experiment_replay");
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">History</h1>
          <p className="text-sm text-muted">Every investigation and its latest run, newest first.</p>
        </div>
        <Link href="/app/investigations/new" className="qc-btn-primary">
          <Icon name="plus" size={14} />
          New investigation
        </Link>
      </div>
      <div className="flex flex-wrap gap-2">
        <label className="relative min-w-0 flex-1">
          <Icon name="search" size={14} className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-faint" />
          <input
            aria-label="Search titles"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search titles"
            className="qc-input w-full pl-8"
          />
        </label>
        <select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value as (typeof STATUSES)[number])} className="qc-input">
          {STATUSES.map((v) => (
            <option key={v} value={v}>
              {v ? words(v) : "Any status"}
            </option>
          ))}
        </select>
        <select aria-label="Outcome" value={outcome} onChange={(e) => setOutcome(e.target.value as (typeof OUTCOMES)[number])} className="qc-input">
          {OUTCOMES.map((v) => (
            <option key={v} value={v}>
              {v ? words(v) : "Any outcome"}
            </option>
          ))}
        </select>
        {filtered ? (
          <button
            type="button"
            onClick={() => {
              setQ("");
              setStatus("");
              setOutcome("");
            }}
            className="qc-btn-ghost"
          >
            Clear filters
          </button>
        ) : null}
      </div>
      {list.isSuccess && items.length ? (
        <p className="-mt-2 text-xs text-muted">
          {items.length} shown{list.hasNextPage ? " · more available" : ""} · newest first (the only order the list endpoint provides)
        </p>
      ) : null}
      {replayMatches ? (
        <p className="-mt-2 text-xs text-muted">
          Experiment replays match this filter by their stored outcome; a replay never verifies a recommendation on its own, and each row says what the replay found.
        </p>
      ) : null}
      {deleted ? (
        <div role="status" className="flex items-center justify-between gap-2 rounded-md border border-border bg-surface-2 px-3 py-2 text-sm">
          <span>Deleted “{deleted.title}”.</span>
          <button type="button" onClick={() => undo.mutate(deleted)} disabled={undo.isPending} className="qc-btn-secondary py-1">
            Undo
          </button>
        </div>
      ) : null}
      <ErrorNotice error={list.error ?? remove.error ?? undo.error} />
      {list.isSuccess && items.length === 0 ? (
        <div className="qc-panel flex flex-col items-start gap-2 p-8">
          <Icon name="history" size={20} className="text-faint" />
          <p className="text-sm text-muted">
            No investigations{filtered ? " match these filters" : " yet"}.{" "}
            <Link href="/app/investigations/new" className="text-link">
              Start one
            </Link>
            .
          </p>
        </div>
      ) : list.isPending ? (
        <p className="text-sm text-muted">Loading investigations…</p>
      ) : (
        <div className="flex flex-col gap-5">
          {groupByDay(items).map((group) => (
            <section key={group.label} aria-label={group.label} className="flex flex-col gap-1.5">
              <h2 className="px-1 text-xs font-medium text-muted">
                {group.label} <span className="font-mono tabular-nums">· {group.items.length}</span>
              </h2>
              <ul className="qc-panel overflow-hidden">
                {group.items.map((item) => (
                  <InvestigationRow
                    key={item.id}
                    item={item}
                    report={item.latestRun ? replayReports.get(item.latestRun.id) : undefined}
                    actions={
                      <button
                        type="button"
                        onClick={() => remove.mutate(item)}
                        disabled={remove.isPending}
                        aria-label={`Delete ${item.title}`}
                        title="Delete"
                        className="qc-btn-ghost size-7 shrink-0 p-0 hover:text-rejected sm:opacity-0 sm:group-hover:opacity-100 sm:focus-visible:opacity-100"
                      >
                        <Icon name="close" size={14} />
                      </button>
                    }
                  />
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
      {list.hasNextPage ? (
        <button type="button" onClick={() => void list.fetchNextPage()} disabled={list.isFetchingNextPage} className="qc-btn-secondary w-fit">
          {list.isFetchingNextPage ? "Loading…" : "Load more"}
        </button>
      ) : null}
    </div>
  );
}
