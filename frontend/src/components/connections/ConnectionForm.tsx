"use client";

import { useState, type FormEvent } from "react";
import { ErrorNotice } from "@/components/common/ErrorNotice";
import type { CreateConnectionInput } from "@/lib/api/types";
import { SettingsSection } from "@/components/ui/SettingsSection";

const REQUIRED: Array<[keyof CreateConnectionInput, string]> = [
  ["name", "Name"],
  ["host", "Host"],
  ["dbname", "Database"],
  ["username", "Username"],
  ["password", "Password"],
];

const EMPTY: CreateConnectionInput = {
  name: "",
  host: "",
  port: 5432,
  dbname: "",
  username: "",
  password: "",
  sslmode: "verify-full",
  environment: "development",
};

const inputClass = "w-full qc-input";

export function ConnectionForm({ onSubmit }: { onSubmit: (input: CreateConnectionInput) => Promise<void> }) {
  const [values, setValues] = useState<CreateConnectionInput>(EMPTY);
  const [missing, setMissing] = useState<string[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);

  const set = <K extends keyof CreateConnectionInput>(key: K, value: CreateConnectionInput[K]) =>
    setValues((v) => ({ ...v, [key]: value }));

  async function submit(event: FormEvent) {
    event.preventDefault();
    const absent = REQUIRED.filter(([key]) => String(values[key]).trim() === "").map(([, label]) => label);
    setMissing(absent);
    if (absent.length > 0) return;
    setSaving(true);
    setError(null);
    try {
      await onSubmit({ ...values, name: values.name.trim(), host: values.host.trim() });
      setValues(EMPTY);
    } catch (e) {
      setError(e);
    } finally {
      setSaving(false);
    }
  }

  const field = (key: keyof CreateConnectionInput, label: string, type = "text") => (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-muted">{label}</span>
      <input
        aria-label={label}
        className={inputClass}
        type={type}
        autoComplete={type === "password" ? "new-password" : "off"}
        value={String(values[key])}
        onChange={(e) =>
          set(key, (key === "port" ? Number(e.target.value) || 0 : e.target.value) as never)
        }
      />
    </label>
  );

  const select = <K extends "sslmode" | "environment">(key: K, label: string, options: [string, string][]) => (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-muted">{label}</span>
      <select
        aria-label={label}
        className={inputClass}
        value={values[key]}
        onChange={(e) => set(key, e.target.value as CreateConnectionInput[K])}
      >
        {options.map(([value, text]) => (
          <option key={value} value={value}>
            {text}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <form onSubmit={submit} noValidate className="flex flex-col">
      <SettingsSection group title="Identity" description="How this connection appears in QueryCure. Production connections need approval before each EXPLAIN.">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {field("name", "Name")}
          {select("environment", "Environment", [
            ["development", "development"],
            ["staging", "staging"],
            ["production", "production (EXPLAIN needs approval)"],
          ])}
        </div>
      </SettingsSection>
      <SettingsSection group title="Server" description="Checked against this deployment's network rules before any connection is made.">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,1fr)_7rem]">
          {field("host", "Host")}
          {field("port", "Port", "number")}
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {field("dbname", "Database")}
          {select("sslmode", "TLS", [
            ["verify-full", "verify-full (recommended)"],
            ["require", "require"],
            ["verify-ca", "verify-ca"],
            ["disable", "disable (local only)"],
          ])}
        </div>
      </SettingsSection>
      <SettingsSection group title="Credentials" description="Use the restricted read-only role. The password is stored encrypted and never shown again.">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {field("username", "Username")}
          {field("password", "Password", "password")}
        </div>
      </SettingsSection>
      <div className="flex flex-col gap-3 border-t border-border pt-5 md:pl-[calc(15rem+2.5rem)]">
        {missing.length > 0 ? (
          <ul className="text-sm text-rejected">
            {missing.map((label) => (
              <li key={label}>{label} is required.</li>
            ))}
          </ul>
        ) : null}
        <ErrorNotice error={error} />
        <button type="submit" disabled={saving} className="w-fit qc-btn-primary">
          {saving ? "Saving…" : "Save connection"}
        </button>
      </div>
    </form>
  );
}
