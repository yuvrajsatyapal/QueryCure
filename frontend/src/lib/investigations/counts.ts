/* Dashboard counts from the filtered list endpoint (UI_UX §3.2). The endpoint returns a page and
 * a cursor but no total, so a full page with a cursor is only a lower bound and says so. */

export interface CountResult {
  value: number;
  capped: boolean;
  label: string;
}

export function cappedCount(page: { items: unknown[]; nextCursor?: string | null } | undefined): CountResult | null {
  if (!page) return null;
  const capped = Boolean(page.nextCursor);
  return { value: page.items.length, capped, label: `${page.items.length}${capped ? "+" : ""}` };
}

/** Sum of several status counts; null while any is still unknown. */
export function sumCounts(parts: (CountResult | null)[]): CountResult | null {
  if (parts.some((p) => p === null)) return null;
  const value = parts.reduce((n, p) => n + (p?.value ?? 0), 0);
  const capped = parts.some((p) => p?.capped);
  return { value, capped, label: `${value}${capped ? "+" : ""}` };
}
