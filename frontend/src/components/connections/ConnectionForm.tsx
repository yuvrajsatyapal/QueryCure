"use client";

import { useState, type FormEvent } from "react";
import { ErrorNotice } from "@/components/common/ErrorNotice";
import type { CreateConnectionInput } from "@/lib/api/types";

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

const inputClass =
  "w-full qc-input text-ink focus:border-accent";

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

  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {field("name", "Name")}
        {field("host", "Host")}
        {field("port", "Port", "number")}
        {field("dbname", "Database")}
        {field("username", "Username")}
        {field("password", "Password", "password")}
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-muted">TLS</span>
          <select
            aria-label="TLS"
            className={inputClass}
            value={values.sslmode}
            onChange={(e) => set("sslmode", e.target.value as CreateConnectionInput["sslmode"])}
          >
            <option value="verify-full">verify-full (recommended)</option>
            <option value="require">require</option>
            <option value="verify-ca">verify-ca</option>
            <option value="disable">disable (local only)</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-muted">Environment</span>
          <select
            aria-label="Environment"
            className={inputClass}
            value={values.environment}
            onChange={(e) => set("environment", e.target.value as CreateConnectionInput["environment"])}
          >
            <option value="development">development</option>
            <option value="staging">staging</option>
            <option value="production">production (EXPLAIN needs approval)</option>
          </select>
        </label>
      </div>
      {missing.length > 0 ? (
        <ul className="text-sm text-rejected">
          {missing.map((label) => (
            <li key={label}>{label} is required.</li>
          ))}
        </ul>
      ) : null}
      <ErrorNotice error={error} />
      <button
        type="submit"
        disabled={saving}
        className="w-fit qc-btn-primary"
      >
        {saving ? "Saving…" : "Save connection"}
      </button>
    </form>
  );
}
