/* History rows grouped by local creation day (UI_UX §3.9): Today, Yesterday, Earlier this week
 * (weeks start Monday), then one group per month. Input order is kept inside each group. */

const month = new Intl.DateTimeFormat("en-US", { month: "long", year: "numeric" });

function startOfDay(t: number): number {
  const d = new Date(t);
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

export function groupByDay<T extends { createdAt: string }>(items: T[], now = Date.now()): { label: string; items: T[] }[] {
  const today = startOfDay(now);
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const weekStart = new Date(today);
  weekStart.setDate(weekStart.getDate() - ((weekStart.getDay() + 6) % 7));

  const groups: { label: string; items: T[] }[] = [];
  for (const item of items) {
    const t = Date.parse(item.createdAt);
    const label =
      t >= today
        ? "Today"
        : t >= yesterday.getTime()
          ? "Yesterday"
          : t >= weekStart.getTime()
            ? "Earlier this week"
            : month.format(new Date(t));
    const group = groups.find((g) => g.label === label);
    if (group) group.items.push(item);
    else groups.push({ label, items: [item] });
  }
  return groups;
}
