/** Chart geometry for the benchmark studio (UI_UX §3.17): log domains, ticks that adapt to the
 * width, label collision, sample dodging and Tukey outliers. Pure functions; the charts only
 * draw what these return, and every value they position is the recorded one. */

export interface LogDomain {
  lo: number;
  hi: number;
  /** The values spanned less than the minimum, so the axis was widened symmetrically. */
  widened: boolean;
}

const usable = (v: number) => Number.isFinite(v) && v > 0;

/** Log domain over `values` with 8% padding, never narrower than `minDecades` (a near-1× cluster
 * is widened around its centre rather than stretched across the chart). */
export function logDomain(values: number[], { minDecades = 0.1, pad = 0.08 }: { minDecades?: number; pad?: number } = {}): LogDomain | null {
  const logs = values.filter(usable).map(Math.log10);
  if (logs.length === 0) return null;
  const lo0 = Math.min(...logs);
  const hi0 = Math.max(...logs);
  const span = hi0 - lo0;
  let lo = lo0 - span * pad;
  let hi = hi0 + span * pad;
  const widened = hi - lo < minDecades;
  if (widened) {
    const mid = (lo0 + hi0) / 2;
    lo = mid - minDecades / 2;
    hi = mid + minDecades / 2;
  }
  return { lo: 10 ** lo, hi: 10 ** hi, widened };
}

/** Position of `v` on the domain, 0 at `lo` and 1 at `hi`. */
export function fraction(d: LogDomain, v: number): number {
  return (Math.log10(v) - Math.log10(d.lo)) / (Math.log10(d.hi) - Math.log10(d.lo));
}

// Mantissas per decade, from sparse to dense.
const range = (from: number, to: number, step: number) => Array.from({ length: Math.round((to - from) / step) }, (_, i) => from + i * step);
const LEVELS: number[][] = [
  [1],
  [1, 2, 5],
  [1, 1.5, 2, 3, 5, 7],
  [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 7, 8, 9],
  [1, 1.1, 1.2, 1.3, 1.4, 1.5, 1.7, 2, 2.5, 3, 3.5, 4, 5, 6, 7, 8, 9],
  [...range(1, 2, 0.1), ...range(2, 5, 0.5), ...range(5, 10, 1)],
  [...range(1, 2, 0.05), ...range(2, 5, 0.25), ...range(5, 10, 0.5)],
];
function ticksAt(d: LogDomain, mantissas: number[]): number[] {
  const out: number[] = [];
  for (let e = Math.floor(Math.log10(d.lo)) - 1; e <= Math.ceil(Math.log10(d.hi)); e++) {
    for (const m of mantissas) {
      const v = Number((m * 10 ** e).toPrecision(3));
      if (v >= d.lo * (1 - 1e-9) && v <= d.hi * (1 + 1e-9)) out.push(v);
    }
  }
  return [...new Set(out)].sort((a, b) => a - b);
}

function minGap(d: LogDomain, ticks: number[], width: number): number {
  let gap = Infinity;
  for (let i = 1; i < ticks.length; i++) gap = Math.min(gap, (fraction(d, ticks[i]!) - fraction(d, ticks[i - 1]!)) * width);
  return gap;
}

/** The richest tick set whose neighbours are at least `minGapPx` apart at this width. `must`
 * values inside the domain (the 1× reference) are always kept; ticks crowding them are dropped. */
export function adaptiveLogTicks(d: LogDomain, width: number, { must = [], minGapPx = 44, maxTicks = 9 }: { must?: number[]; minGapPx?: number; maxTicks?: number } = {}): number[] {
  const w = width > 0 ? width : 600;
  // The level with the most ticks that still fit; a denser level can fail where a sparser one
  // with different steps (1, 1.2, 1.5, 2…) fits, so every level is tried.
  let best: number[] = [];
  for (const level of LEVELS) {
    const t = ticksAt(d, level);
    if (t.length > maxTicks || (t.length > 1 && minGap(d, t, w) < minGapPx)) continue;
    if (t.length > best.length) best = t;
  }
  const required = must.filter((m) => m >= d.lo && m <= d.hi);
  const x = (v: number) => fraction(d, v) * w;
  const kept = best.filter((t) => required.includes(t) || required.every((m) => Math.abs(x(t) - x(m)) >= minGapPx));
  return [...new Set([...kept, ...required])].sort((a, b) => a - b);
}

/** At most three significant digits, without trailing zeros. */
export function tickText(v: number): string {
  return String(Number(v.toPrecision(3)));
}

export interface AxisLabel {
  key: string;
  x: number;
  text: string;
  priority?: boolean;
}

/** Monospace axis labels at 10px are about 6.1px per character. */
export const labelWidth = (text: string) => text.length * 6.1 + 6;

/** Labels that fit without overlapping, priority ones first; edge labels are anchored inside. */
export function placeLabels(labels: AxisLabel[], width: number): (AxisLabel & { anchor: "start" | "middle" | "end" })[] {
  const placed: (AxisLabel & { anchor: "start" | "middle" | "end"; from: number; to: number })[] = [];
  const order = [...labels.filter((l) => l.priority), ...labels.filter((l) => !l.priority)];
  for (const l of order) {
    const w = labelWidth(l.text);
    const anchor = l.x - w / 2 < 0 ? "start" : l.x + w / 2 > width ? "end" : "middle";
    const from = anchor === "start" ? Math.max(0, l.x - 3) : anchor === "end" ? Math.min(width, l.x + 3) - w : l.x - w / 2;
    const to = from + w;
    if (placed.some((p) => from < p.to + 4 && to > p.from - 4)) continue;
    placed.push({ ...l, anchor, from, to });
  }
  return placed.sort((a, b) => a.x - b.x).map((p) => ({ key: p.key, x: p.x, text: p.text, priority: p.priority, anchor: p.anchor }));
}

/** Vertical lanes for sample dots: each dot goes to the first lane (0, -1, 1, -2, 2, …) with no
 * dot within `gap` of it; with none free, the lane whose nearest dot is furthest away. Only the
 * vertical position moves; the horizontal position is always the recorded latency. */
export function dodgeLanes(fractions: number[], gap: number, maxLanes: number): number[] {
  const lanes = Array.from({ length: Math.max(1, maxLanes) }, (_, i) => (i === 0 ? 0 : i % 2 ? -Math.ceil(i / 2) : i / 2));
  const occupied = new Map<number, number[]>(lanes.map((l) => [l, []]));
  const order = fractions.map((p, i) => [p, i] as const).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const out = new Array<number>(fractions.length).fill(0);
  for (const [p, i] of order) {
    const distance = (l: number) => Math.min(Infinity, ...occupied.get(l)!.map((q) => Math.abs(p - q)));
    const free = lanes.find((l) => distance(l) >= gap);
    const lane = free ?? lanes.reduce((a, b) => (distance(b) > distance(a) ? b : a));
    occupied.get(lane)!.push(p);
    out[i] = lane;
  }
  return out;
}

/** Tukey's fences: below Q1 − 1.5·IQR or above Q3 + 1.5·IQR. Marks samples; removes none. */
export function tukeyOutliers(samples: number[], q1: number, q3: number): boolean[] {
  const iqr = q3 - q1;
  return samples.map((v) => v < q1 - 1.5 * iqr || v > q3 + 1.5 * iqr);
}
