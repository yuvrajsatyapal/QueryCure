"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ErrorNotice } from "@/components/common/ErrorNotice";
import { getModels } from "@/lib/api/investigations";
import { addCredential, deleteCredential, listCredentials, settingsKeys } from "@/lib/api/settings";

const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

export function SettingsView() {
  const client = useQueryClient();
  const credentials = useQuery({ queryKey: settingsKeys.credentials, queryFn: ({ signal }) => listCredentials(signal) });
  const models = useQuery({ queryKey: settingsKeys.models, queryFn: ({ signal }) => getModels(signal) });
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const refresh = () => {
    void client.invalidateQueries({ queryKey: settingsKeys.credentials });
    void client.invalidateQueries({ queryKey: settingsKeys.models });
  };
  const add = useMutation({
    mutationFn: () => addCredential({ apiKey: apiKey.trim(), defaultModel: model.trim() || undefined }),
    onSuccess: () => {
      setApiKey(""); // the key leaves the page's memory as soon as it is stored
      setModel("");
      refresh();
    },
  });
  const remove = useMutation({ mutationFn: (id: string) => deleteCredential(id), onSuccess: refresh });
  const items = credentials.data?.items ?? [];

  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <header>
        <p className="qc-eyebrow">Settings</p>
        <h1 className="text-2xl font-semibold">Model key</h1>
        <p className="text-sm text-muted">
          Investigations call a free OpenRouter model with your own key. QueryCure stores it encrypted, shows only its last four characters, and uses it
          only for your runs. Paid models are refused.
        </p>
      </header>

      <section aria-label="Saved key" className="qc-panel p-4">
        <h2 className="mb-2 font-medium">Saved key</h2>
        {credentials.isLoading ? <p className="text-sm text-muted">Loading…</p> : null}
        <ErrorNotice error={credentials.error} />
        {!credentials.isLoading && items.length === 0 ? (
          <p className="text-sm text-muted">
            No key saved.{" "}
            {models.data?.configured ? "Runs use this deployment's local key." : "Add one to start investigations."}
          </p>
        ) : null}
        <ul className="flex flex-col gap-2">
          {items.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border p-3 text-sm">
              <span className="flex min-w-0 flex-col">
                <span className="font-medium">
                  {c.provider} · <span className="font-mono">…{c.keyHint}</span>
                </span>
                <span className="text-xs text-muted">
                  model {c.defaultModel ?? models.data?.model ?? "default"} · added {dateTime.format(new Date(c.createdAt))}
                  {c.lastUsedAt ? ` · last used ${dateTime.format(new Date(c.lastUsedAt))}` : " · not used yet"}
                </span>
              </span>
              <button
                type="button"
                onClick={() => remove.mutate(c.id)}
                disabled={remove.isPending}
                className="rounded-md border border-rejected px-3 py-1 text-rejected"
              >
                Delete key
              </button>
            </li>
          ))}
        </ul>
        <ErrorNotice error={remove.error} />
      </section>

      <form
        aria-label="Add a key"
        className="flex flex-col gap-3 qc-panel p-4"
        onSubmit={(e) => {
          e.preventDefault();
          add.mutate();
        }}
      >
        <h2 className="font-medium">{items.length ? "Replace the key" : "Add a key"}</h2>
        <label className="flex flex-col gap-1 text-sm">
          OpenRouter API key
          <input
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            className="qc-input bg-surface-2 font-mono"
            required
            minLength={8}
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Free model (optional)
          <input
            type="text"
            placeholder={models.data?.model ?? "provider/model:free"}
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="qc-input bg-surface-2 font-mono"
            pattern=".*(:free|^openrouter/free)$"
            title="Only free models (ending in :free) are allowed"
          />
        </label>
        <ErrorNotice error={add.error} />
        <button type="submit" disabled={add.isPending || apiKey.trim().length < 8} className="w-fit qc-btn-primary">
          {add.isPending ? "Saving…" : "Save key"}
        </button>
        {add.isSuccess ? <p role="status" className="text-sm text-verified">Key saved; only its last four characters are kept visible.</p> : null}
      </form>
    </div>
  );
}
