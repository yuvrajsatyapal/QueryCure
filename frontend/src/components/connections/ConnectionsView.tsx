"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ErrorNotice } from "@/components/common/ErrorNotice";
import {
  connectionKeys,
  createConnection,
  deleteConnection,
  listConnections,
  testConnection,
} from "@/lib/api/connections";
import type { ConnectionSummary, ConnectionTestResult } from "@/lib/api/types";
import { CapabilityChecklist } from "./CapabilityChecklist";
import { ConnectionForm } from "./ConnectionForm";
import { RoleSnippet } from "./RoleSnippet";

function TestPanel({ connection }: { connection: ConnectionSummary }) {
  const [result, setResult] = useState<ConnectionTestResult | null>(null);
  const queryClient = useQueryClient();
  const test = useMutation({
    mutationFn: () => testConnection(connection.id),
    onSuccess: (r) => setResult(r),
    onSettled: () => queryClient.invalidateQueries({ queryKey: connectionKeys.all }),
  });
  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        onClick={() => test.mutate()}
        disabled={test.isPending}
        className="w-fit qc-btn-secondary"
      >
        {test.isPending ? "Testing…" : "Test connection"}
      </button>
      {test.isError ? <ErrorNotice error={test.error} /> : null}
      {result ? <CapabilityChecklist capabilities={result.capabilities} /> : null}
    </div>
  );
}

function DeleteButton({ connection }: { connection: ConnectionSummary }) {
  const [confirming, setConfirming] = useState(false);
  const queryClient = useQueryClient();
  const remove = useMutation({
    mutationFn: () => deleteConnection(connection.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: connectionKeys.all }),
  });
  if (!confirming) {
    return (
      <button type="button" onClick={() => setConfirming(true)} className="text-sm text-muted hover:text-rejected">
        Delete
      </button>
    );
  }
  return (
    <span className="flex items-center gap-2 text-sm">
      <button type="button" onClick={() => remove.mutate()} className="rounded-md border border-rejected px-2 py-1 text-rejected">
        Confirm delete
      </button>
      <button type="button" onClick={() => setConfirming(false)} className="text-muted">
        Cancel
      </button>
    </span>
  );
}

export function ConnectionsView() {
  const queryClient = useQueryClient();
  const [adding, setAdding] = useState(false);
  const connections = useQuery({ queryKey: connectionKeys.all, queryFn: ({ signal }) => listConnections(signal) });

  async function create(input: Parameters<typeof createConnection>[0]) {
    await createConnection(input);
    await queryClient.invalidateQueries({ queryKey: connectionKeys.all });
    setAdding(false);
  }

  const items = connections.data?.items ?? [];
  return (
    <div className="flex max-w-4xl flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Connections</h1>
        <button
          type="button"
          onClick={() => setAdding((a) => !a)}
          className="qc-btn-primary"
        >
          {adding ? "Close" : "Add connection"}
        </button>
      </div>
      {adding ? (
        <section className="flex flex-col gap-4 qc-panel p-4">
          <RoleSnippet />
          <ConnectionForm onSubmit={create} />
        </section>
      ) : null}
      {connections.isPending ? <p className="text-muted">Loading connections…</p> : null}
      {connections.isError ? <ErrorNotice error={connections.error} /> : null}
      {connections.isSuccess && items.length === 0 ? (
        <p className="qc-panel p-6 text-muted">
          No connections yet. Add a restricted read-only role to inspect a live database, or use plan
          upload in the workspace.
        </p>
      ) : null}
      <ul className="flex flex-col gap-3">
        {items.map((c) => (
          <li key={c.id} className="flex flex-col gap-3 qc-panel p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <div>
                <p className="font-medium">{c.name}</p>
                <p className="font-mono text-xs text-muted">
                  {c.username}@{c.host}:{c.port}/{c.dbname} · {c.environment} · tls {c.sslmode}
                </p>
              </div>
              <div className="flex items-center gap-3">
                {c.lastTestStatus ? (
                  <span className="qc-eyebrow">
                    last test: {c.lastTestStatus}
                  </span>
                ) : null}
                <DeleteButton connection={c} />
              </div>
            </div>
            <TestPanel connection={c} />
          </li>
        ))}
      </ul>
    </div>
  );
}
