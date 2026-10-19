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
import { Icon } from "@/components/ui/Icon";
import { PageHeader, SettingsSection } from "@/components/ui/SettingsSection";
import { StatusPill, type Tone } from "@/components/ui/StatusPill";

const TEST_STATUS: Record<string, { tone: Tone; label: string }> = {
  ok: { tone: "success", label: "Test passed" },
  failed: { tone: "failed", label: "Test failed" },
  refused: { tone: "failed", label: "Role refused" },
};
const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

function TestPanel({ connection }: { connection: ConnectionSummary }) {
  const [result, setResult] = useState<ConnectionTestResult | null>(null);
  const queryClient = useQueryClient();
  const test = useMutation({
    mutationFn: () => testConnection(connection.id),
    onSuccess: (r) => setResult(r),
    onSettled: () => queryClient.invalidateQueries({ queryKey: connectionKeys.all }),
  });
  return (
    <>
      <button type="button" onClick={() => test.mutate()} disabled={test.isPending} className="qc-btn-secondary py-1 text-xs">
        <Icon name="plug" size={13} />
        {test.isPending ? "Testing…" : "Test connection"}
      </button>
      {test.isError || result ? (
        <div className="basis-full border-t border-border pt-3">
          {test.isError ? <ErrorNotice error={test.error} /> : null}
          {result ? <CapabilityChecklist capabilities={result.capabilities} /> : null}
        </div>
      ) : null}
    </>
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
      <button type="button" onClick={() => setConfirming(true)} className="qc-btn-ghost py-1 text-xs hover:text-rejected">
        Delete
      </button>
    );
  }
  return (
    <span className="flex items-center gap-1 text-xs">
      <button type="button" onClick={() => remove.mutate()} className="qc-btn border border-rejected/40 py-1 text-xs text-rejected hover:bg-rejected/10">
        Confirm delete
      </button>
      <button type="button" onClick={() => setConfirming(false)} className="qc-btn-ghost py-1 text-xs">
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
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <PageHeader
        title="Connections"
        description="Restricted, read-only database connections for live inspection. QueryCure only runs plain EXPLAIN and catalog reads in read-only sessions."
        action={
          <button type="button" onClick={() => setAdding((a) => !a)} aria-expanded={adding} className="qc-btn-primary">
            {adding ? null : <Icon name="plus" size={14} />}
            {adding ? "Close" : "Add connection"}
          </button>
        }
      />
      {adding ? (
        <section aria-label="Add connection" className="qc-panel flex flex-col p-5">
          <SettingsSection group title="Read-only role" description="Create this role on your database first. Superuser, CREATEROLE and BYPASSRLS roles are refused.">
            <RoleSnippet />
          </SettingsSection>
          <div className="border-t border-border pt-6">
            <ConnectionForm onSubmit={create} />
          </div>
        </section>
      ) : null}
      {connections.isPending ? <p className="text-sm text-muted">Loading connections…</p> : null}
      {connections.isError ? <ErrorNotice error={connections.error} /> : null}
      {connections.isSuccess && items.length === 0 ? (
        <div className="qc-panel flex flex-col items-start gap-2 p-8">
          <Icon name="plug" size={20} className="text-faint" />
          <p className="text-sm text-muted">
            No connections yet. Add a restricted read-only role to inspect a live database, or use plan upload in the workspace.
          </p>
        </div>
      ) : null}
      {items.length ? (
        <ul aria-label="Saved connections" className="qc-panel overflow-hidden">
          {items.map((c) => {
            const status = c.lastTestStatus ? TEST_STATUS[c.lastTestStatus] : null;
            return (
              <li key={c.id} className="flex flex-wrap items-center gap-x-4 gap-y-3 border-b border-border px-4 py-3 last:border-b-0">
                <Icon name="database" size={16} className="text-faint" />
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
                    {c.name}
                    <span className="rounded border border-border px-1.5 text-[11px] font-normal text-muted">{c.environment}</span>
                  </p>
                  <p className="truncate font-mono text-xs text-muted">
                    {c.username}@{c.host}:{c.port}/{c.dbname} · tls {c.sslmode}
                  </p>
                </div>
                <span className="flex flex-col items-end gap-0.5">
                  {status ? <StatusPill tone={status.tone} label={status.label} /> : <StatusPill tone="neutral" label="Never tested" />}
                  {c.lastTestedAt ? <span className="text-[11px] text-muted">{dateTime.format(new Date(c.lastTestedAt))}</span> : null}
                </span>
                <div className="flex items-center gap-1">
                  <TestPanel connection={c} />
                  <DeleteButton connection={c} />
                </div>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
