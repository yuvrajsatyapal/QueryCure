/** Rect fields the connector helpers need (a DOMRect satisfies it). */
export type Rect = { left: number; top: number; right: number; bottom: number; width: number; height: number };

/** S-curve from `a` to `b` in `box` coordinates: vertical when `b` sits below `a` (or `dir` is "v"), else horizontal. */
export function curve(a: Rect, b: Rect, box: Pick<Rect, "left" | "top">, dir?: "v" | "h"): string {
  if (dir === "v" || (dir !== "h" && b.top >= a.bottom - 4)) {
    const x1 = a.left + a.width / 2 - box.left;
    const y1 = a.bottom - box.top;
    const x2 = b.left + b.width / 2 - box.left;
    const y2 = b.top - box.top;
    const m = (y2 - y1) / 2;
    return `M${x1},${y1} C${x1},${y1 + m} ${x2},${y2 - m} ${x2},${y2}`;
  }
  const x1 = a.right - box.left;
  const y1 = a.top + a.height / 2 - box.top;
  const x2 = b.left - box.left;
  const y2 = b.top + b.height / 2 - box.top;
  const m = (x2 - x1) / 2;
  return `M${x1},${y1} C${x1 + m},${y1} ${x2 - m},${y2} ${x2},${y2}`;
}
