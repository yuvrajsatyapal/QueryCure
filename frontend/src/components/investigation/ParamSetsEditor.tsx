"use client";

import type { ParamSetInput } from "@/lib/api/types";

export interface ParamSetRow {
  name: string;
  values: string; // JSON array text, e.g. [1024]
  edgeCase?: boolean; // NULL-bearing or empty-result set (needed to verify rewrites)
}

const NAME = /^[A-Za-z0-9_-]{1,64}$/;

/** Rows → API param sets, or the first problem in words. Values are a JSON array of scalars,
 * one per $n placeholder. */
export function parseParamSets(rows: ParamSetRow[]): { sets: ParamSetInput[]; error: string | null } {
  const sets: ParamSetInput[] = [];
  for (const [i, row] of rows.entries()) {
    if (row.name === "" && row.values.trim() === "") continue;
    if (!NAME.test(row.name)) {
      return { sets: [], error: `Row ${i + 1}: name must be letters, digits, - or _ (max 64).` };
    }
    let values: unknown;
    try {
      values = JSON.parse(row.values);
    } catch {
      return { sets: [], error: `Row ${i + 1}: values must be a JSON array such as [1024].` };
    }
    const scalar = (v: unknown) => v === null || ["string", "number", "boolean"].includes(typeof v);
    if (!Array.isArray(values)) {
      return { sets: [], error: `Row ${i + 1}: values must be a JSON array such as [1024].` };
    }
    if (!values.every(scalar)) {
      return { sets: [], error: `Row ${i + 1}: values must be an array of numbers, strings, booleans or null.` };
    }
    sets.push({
      name: row.name,
      values: values as ParamSetInput["values"],
      ...(row.edgeCase ? { edgeCase: true } : {}),
    });
  }
  return { sets, error: null };
}

export function ParamSetsEditor({ rows, onChange }: { rows: ParamSetRow[]; onChange: (rows: ParamSetRow[]) => void }) {
  const update = (i: number, patch: Partial<ParamSetRow>) =>
    onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="text-sm text-muted">Parameter sets (one value per $n placeholder)</legend>
      {rows.map((row, i) => (
        <div key={i} className="flex flex-wrap gap-2">
          <input
            aria-label={`Parameter set ${i + 1} name`}
            value={row.name}
            onChange={(e) => update(i, { name: e.target.value })}
            placeholder="hot_customer"
            className="w-40 rounded-md border border-border-strong bg-surface px-2 py-1 font-mono text-xs"
          />
          <input
            aria-label={`Parameter set ${i + 1} values`}
            value={row.values}
            onChange={(e) => update(i, { values: e.target.value })}
            placeholder="[1024]"
            className="min-w-0 flex-1 rounded-md border border-border-strong bg-surface px-2 py-1 font-mono text-xs"
          />
          <button
            type="button"
            onClick={() => onChange(rows.filter((_, j) => j !== i))}
            className="rounded-md border border-border-strong px-2 text-xs"
            aria-label={`Remove parameter set ${i + 1}`}
          >
            Remove
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={() => onChange([...rows, { name: "", values: "" }])}
        className="w-fit rounded-md border border-border-strong px-3 py-1 text-xs"
      >
        Add parameter set
      </button>
    </fieldset>
  );
}
