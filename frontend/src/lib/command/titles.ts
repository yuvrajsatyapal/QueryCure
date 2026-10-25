/* Palette investigation results that share a title (UI_UX §3.15): each gets its recorded creation
 * time, plus the start of its ID when even that repeats. Only fields the list already returns. */

const SHORT_ID = 8;

export function disambiguateTitles(items: readonly { id: string; title: string; createdAt: string }[], timeZone?: string): Map<string, string> {
  const stamp = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone });
  const byTitle = new Map<string, typeof items>();
  for (const item of items) {
    const key = item.title.trim().toLowerCase();
    byTitle.set(key, [...(byTitle.get(key) ?? []), item]);
  }
  const out = new Map<string, string>();
  for (const same of byTitle.values()) {
    if (same.length < 2) continue;
    const stamps = same.map((i) => stamp.format(new Date(i.createdAt)));
    same.forEach((item, n) => {
      const at = stamps[n] ?? "";
      out.set(item.id, stamps.filter((s) => s === at).length > 1 ? `${at} · ${item.id.slice(0, SHORT_ID)}` : at);
    });
  }
  return out;
}
