"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { ErrorNotice } from "@/components/common/ErrorNotice";
import { createInvestigation, getModels, investigationKeys } from "@/lib/api/investigations";
import type { CreateInvestigationInput } from "@/lib/api/types";
import { ParamSetsEditor, parseParamSets, type ParamSetRow } from "./ParamSetsEditor";

export function StartInvestigation({
  query,
  planArtifactSha256,
  connectionId,
}: {
  query: string;
  planArtifactSha256?: string;
  connectionId?: string;
}) {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [objective, setObjective] = useState("Why is this query slow, and what should change?");
  const [rows, setRows] = useState<ParamSetRow[]>([{ name: "", values: "" }]);
  const [formError, setFormError] = useState<string | null>(null);
  // One key per form instance: retries and double submits reuse it (API idempotency).
  const [idempotencyKey] = useState(() => crypto.randomUUID());
  const models = useQuery({ queryKey: investigationKeys.models, queryFn: ({ signal }) => getModels(signal) });

  const start = useMutation({
    mutationFn: (input: CreateInvestigationInput) => createInvestigation(input, idempotencyKey),
    onSuccess: (r) => router.push(`/app/investigations/${r.investigation.id}`),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const { sets, error } = parseParamSets(rows);
    if (title.trim() === "") return setFormError("Give the investigation a title.");
    if (error) return setFormError(error);
    setFormError(null);
    start.mutate({
      title: title.trim(),
      objective: objective.trim(),
      modes: [connectionId ? "live_inspection" : "offline"],
      query,
      paramSets: sets,
      ...(connectionId ? { connectionId } : {}),
      ...(planArtifactSha256 ? { planArtifactSha256 } : {}),
    });
  }

  return (
    <form onSubmit={submit} aria-label="Start investigation" className="flex flex-col gap-3 rounded-lg border border-border bg-surface p-4">
      <label className="flex flex-col gap-1 text-sm">
        Title
        <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} className="rounded-md border border-border-strong bg-surface px-3 py-2" />
      </label>
      <label className="flex flex-col gap-1 text-sm">
        Objective
        <textarea value={objective} onChange={(e) => setObjective(e.target.value)} maxLength={2000} rows={2} className="rounded-md border border-border-strong bg-surface px-3 py-2" />
      </label>
      <ParamSetsEditor rows={rows} onChange={setRows} />
      <p className="text-xs text-muted">
        Mode: {connectionId ? "live inspection (plain EXPLAIN on your connection)" : "offline"}
        {planArtifactSha256 ? " · with the uploaded plan" : ""}. Nothing is executed or benchmarked yet.
      </p>
      {models.data ? (
        <p className={`text-xs ${models.data.configured ? "text-muted" : "text-inconclusive"}`}>
          {models.data.configured
            ? `Model: ${models.data.model} (free, via ${models.data.provider})`
            : `No API key configured for ${models.data.provider}: the run will stop with a configuration error.`}
        </p>
      ) : null}
      {formError ? (
        <p role="alert" className="text-sm text-rejected">
          {formError}
        </p>
      ) : null}
      <ErrorNotice error={start.error} />
      <button type="submit" disabled={start.isPending || query.trim() === ""} className="w-fit rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-fg disabled:opacity-60">
        {start.isPending ? "Starting…" : "Start investigation"}
      </button>
    </form>
  );
}
