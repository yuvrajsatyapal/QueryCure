"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTheme } from "next-themes";
import { useState, useSyncExternalStore } from "react";
import { ErrorNotice } from "@/components/common/ErrorNotice";
import { getModels } from "@/lib/api/investigations";
import { addCredential, deleteCredential, listCredentials, settingsKeys } from "@/lib/api/settings";
import { Icon, type IconName } from "@/components/ui/Icon";
import { PageHeader, SettingsSection } from "@/components/ui/SettingsSection";

const subscribe = () => () => {};

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
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <PageHeader title="Settings" description="Your model key and how QueryCure looks. Investigation defaults are set per run." />

      <div className="flex flex-col">
        <SettingsSection
          title="Model key"
          description="Investigations call a free OpenRouter model with your own key. QueryCure stores it encrypted, shows only its last four characters, and uses it only for your runs. Paid models are refused."
        >
          {credentials.isLoading ? <p className="text-sm text-muted">Loading…</p> : null}
          <ErrorNotice error={credentials.error} />
          {!credentials.isLoading && items.length === 0 ? (
            <p className="rounded-md border border-dashed border-border px-3 py-2 text-sm text-muted">
              No key saved.{" "}
              {models.data?.configured ? "Runs use this deployment's local key." : "Add one to start investigations."}
            </p>
          ) : null}
          {items.length ? (
            <ul aria-label="Saved key" className="qc-panel overflow-hidden">
              {items.map((c) => (
                <li key={c.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm">
                  <span className="flex min-w-0 items-center gap-3">
                    <Icon name="sparkles" size={16} className="text-faint" />
                    <span className="flex min-w-0 flex-col">
                      <span className="font-medium">
                        {c.provider} · <span className="font-mono">…{c.keyHint}</span>
                      </span>
                      <span className="text-xs text-muted">
                        model {c.defaultModel ?? models.data?.model ?? "default"} · added {dateTime.format(new Date(c.createdAt))}
                        {c.lastUsedAt ? ` · last used ${dateTime.format(new Date(c.lastUsedAt))}` : " · not used yet"}
                      </span>
                    </span>
                  </span>
                  <button
                    type="button"
                    onClick={() => remove.mutate(c.id)}
                    disabled={remove.isPending}
                    className="qc-btn border border-rejected/40 py-1 text-xs text-rejected hover:bg-rejected/10"
                  >
                    Delete key
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          <ErrorNotice error={remove.error} />
        </SettingsSection>

        <SettingsSection
          title={items.length ? "Replace the key" : "Add a key"}
          description="The key leaves this page as soon as it is saved; it is never shown again."
        >
          <form
            aria-label="Add a key"
            className="flex max-w-lg flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              add.mutate();
            }}
          >
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted">OpenRouter API key</span>
              <input
                type="password"
                aria-label="OpenRouter API key"
                autoComplete="off"
                spellCheck={false}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                className="qc-input font-mono"
                required
                minLength={8}
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted">Free model (optional)</span>
              <input
                type="text"
                aria-label="Free model (optional)"
                placeholder={models.data?.model ?? "provider/model:free"}
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="qc-input font-mono"
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
        </SettingsSection>

        <SettingsSection title="Appearance" description="Dark is the default. The choice is kept in this browser only.">
          <ThemeChoice />
        </SettingsSection>
      </div>
    </div>
  );
}

/** Same setting as the sidebar toggle, as native radios (arrow keys move between them). */
function ThemeChoice() {
  const { theme, setTheme } = useTheme();
  const mounted = useSyncExternalStore(subscribe, () => true, () => false);
  const current = mounted ? (theme ?? "dark") : "dark";
  const options: [string, string, IconName][] = [
    ["dark", "Dark", "moon"],
    ["light", "Light", "sun"],
    ["system", "Match system", "settings"],
  ];
  return (
    <div role="radiogroup" aria-label="Theme" className="flex w-fit gap-0.5 rounded-md border border-border bg-surface-2 p-0.5">
      {options.map(([value, label, icon]) => (
        <label
          key={value}
          className={`flex cursor-pointer items-center gap-1.5 rounded px-3 py-1.5 text-xs has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent ${
            current === value ? "bg-surface font-medium text-ink shadow-sm" : "text-muted hover:text-ink"
          }`}
        >
          <input type="radio" name="theme" value={value} checked={current === value} onChange={() => setTheme(value)} className="sr-only" />
          <Icon name={icon} size={13} />
          {label}
        </label>
      ))}
    </div>
  );
}
