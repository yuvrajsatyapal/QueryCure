"use client";

import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { ErrorNotice } from "@/components/common/ErrorNotice";
import { deleteInvestigation, listInvestigations, restoreInvestigation } from "@/lib/api/investigations";
import type { InvestigationSummary } from "@/lib/api/types";

const STATUSES = ["", "queued", "running", "completed", "failed", "cancelled"] as const;
const PAGE = 20;

function outcomeLabel(item: InvestigationSummary): string {
  const run = item.latestRun;
  if (!run) return "no run";
  return run.outcome ? `${run.status} · ${run.outcome.replaceAll("_", " ")}` : run.status;
}

export function HistoryView() {
  const client = useQueryClient();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<(typeof STATUSES)[number]>("");
  const [deleted, setDeleted] = useState<InvestigationSummary | null>(null);
  const params = { q: q.trim() || undefined, status: status || undefined, limit: PAGE };

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
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold">History</h1>
      <div className="flex flex-wrap gap-2">
        <input
          aria-label="Search titles"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search titles"
          className="min-w-0 flex-1 rounded-md border border-border-strong bg-surface px-3 py-2 text-sm"
        />
        <select
          aria-label="Status"
          value={status}
          onChange={(e) => setStatus(e.target.value as (typeof STATUSES)[number])}
          className="rounded-md border border-border-strong bg-surface px-3 py-2 text-sm"
        >
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s || "Any status"}
            </option>
          ))}
        </select>
      </div>
      {deleted ? (
        <div role="status" className="flex items-center justify-between gap-2 rounded-md border border-border bg-surface-2 px-3 py-2 text-sm">
          <span>Deleted “{deleted.title}”.</span>
          <button type="button" onClick={() => undo.mutate(deleted)} disabled={undo.isPending} className="rounded-md border border-border-strong px-3 py-1">
            Undo
          </button>
        </div>
      ) : null}
      <ErrorNotice error={list.error ?? remove.error ?? undo.error} />
      {list.isSuccess && items.length === 0 ? (
        <p className="rounded-lg border border-border bg-surface p-6 text-muted">
          No investigations{q || status ? " match these filters" : " yet"}.{" "}
          <Link href="/app/investigations/new" className="text-link">
            Start one
          </Link>
          .
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left font-mono text-[11px] uppercase tracking-wider text-muted">
                <th className="py-2 pr-3">Title</th>
                <th className="py-2 pr-3">Latest run</th>
                <th className="py-2 pr-3">Created</th>
                <th className="py-2" aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id} className="h-8 border-t border-border">
                  <td className="py-1 pr-3">
                    <Link href={`/app/investigations/${item.id}`} className="text-link">
                      {item.title}
                    </Link>
                  </td>
                  <td className="py-1 pr-3 text-muted">{outcomeLabel(item)}</td>
                  <td className="py-1 pr-3 font-mono text-[11px] text-muted">
                    <time dateTime={item.createdAt}>{new Date(item.createdAt).toLocaleString()}</time>
                  </td>
                  <td className="py-1 text-right">
                    <button
                      type="button"
                      onClick={() => remove.mutate(item)}
                      disabled={remove.isPending}
                      aria-label={`Delete ${item.title}`}
                      className="rounded-md border border-rejected/60 px-2 py-0.5 text-xs text-rejected"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {list.hasNextPage ? (
        <button type="button" onClick={() => void list.fetchNextPage()} disabled={list.isFetchingNextPage} className="w-fit rounded-md border border-border-strong px-4 py-2 text-sm">
          {list.isFetchingNextPage ? "Loading…" : "Load more"}
        </button>
      ) : null}
    </div>
  );
}
