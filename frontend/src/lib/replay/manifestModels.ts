export interface ManifestModelRow {
  key: string;
  agent: string;
  model: string;
  promptVersion: string;
  calls: number;
}

type ManifestModel = Omit<ManifestModelRow, "key">;

/** The manifest's `llm` list for display: entries with the same agent, model and prompt
 * version merge (calls summed), since a sealed manifest may repeat them and React needs
 * unique keys. Display only; the stored manifest is never rewritten. */
export function manifestModelRows(llm: unknown): ManifestModelRow[] {
  if (!Array.isArray(llm)) return [];
  const rows = new Map<string, ManifestModelRow>();
  for (const c of llm as ManifestModel[]) {
    const key = `${c.agent}|${c.model}|${c.promptVersion}`;
    const seen = rows.get(key);
    if (seen) seen.calls += c.calls;
    else rows.set(key, { key, agent: c.agent, model: c.model, promptVersion: c.promptVersion, calls: c.calls });
  }
  return [...rows.values()];
}
