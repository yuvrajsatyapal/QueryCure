import type { Span } from "@/lib/events/trace";

/* Geometry for the waterfall trace (UI_UX §3.6). Every bar comes from a recorded timestamp:
 * node and tool spans from their started/completed events, approval waits from
 * approval.requested → approval.decided. LLM calls emit no event, so nothing here is drawn
 * as a model call; an agent node is one bar with its recorded tool calls laid over it. */

export interface TimeWindow {
  startMs: number;
  endMs: number;
  /** Compressed time only: knots mapping real time to drawn position. Absent means linear. */
  axis?: Knot[];
}

/** A point of a piecewise-linear axis: real time `t` is drawn at position `v` (ms-equivalents). */
export interface Knot {
  t: number;
  v: number;
}

/** A real-time interval drawn shorter than it lasted (an approval wait). */
export interface Break {
  startMs: number;
  endMs: number;
}

export type SegmentKind = "run" | "agent" | "step" | "tool" | "wait" | "live" | "failed" | "unfinished";

export interface Segment {
  kind: SegmentKind;
  leftPct: number;
  widthPct: number;
  /** The bar continues before / after the visible window. */
  clipStart: boolean;
  clipEnd: boolean;
}

const MIN_WIDTH_PCT = 0.4;
const ms = (iso: string) => Date.parse(iso);

/** The run's time range: first event to the run's end, or to now while it is live (never
 * shorter than what was recorded, whatever the local clock says). */
export function traceBounds(root: Span, nowMs: number): TimeWindow {
  const startMs = ms(root.startTs);
  if (root.endTs) return { startMs, endMs: Math.max(ms(root.endTs), startMs + 1) };
  return { startMs, endMs: Math.max(nowMs, latestTs(root), startMs + 1) };
}

function latestTs(span: Span): number {
  let latest = ms(span.startTs);
  for (const e of span.events) latest = Math.max(latest, ms(e.ts));
  if (span.endTs) latest = Math.max(latest, ms(span.endTs));
  for (const c of span.children) latest = Math.max(latest, latestTs(c));
  return latest;
}

/** Drawn position of real time `t` (identity on a linear axis; slope 1 outside the knots). */
function toV(axis: Knot[] | undefined, t: number): number {
  if (!axis?.length) return t;
  const first = axis[0]!;
  if (t <= first.t) return first.v + (t - first.t);
  for (let i = 1; i < axis.length; i += 1) {
    const a = axis[i - 1]!;
    const b = axis[i]!;
    if (t <= b.t) return b.t === a.t ? b.v : a.v + ((t - a.t) / (b.t - a.t)) * (b.v - a.v);
  }
  const last = axis.at(-1)!;
  return last.v + (t - last.t);
}

function fromV(axis: Knot[] | undefined, v: number): number {
  if (!axis?.length) return v;
  const first = axis[0]!;
  if (v <= first.v) return first.t + (v - first.v);
  for (let i = 1; i < axis.length; i += 1) {
    const a = axis[i - 1]!;
    const b = axis[i]!;
    if (v <= b.v) return b.v === a.v ? b.t : a.t + ((v - a.v) / (b.v - a.v)) * (b.t - a.t);
  }
  const last = axis.at(-1)!;
  return last.t + (v - last.v);
}

/** Where real time `t` falls across the window, in percent (may be outside 0–100). */
function pct(win: TimeWindow, t: number): number {
  const a = toV(win.axis, win.startMs);
  const b = toV(win.axis, win.endMs);
  return b > a ? ((toV(win.axis, t) - a) / (b - a)) * 100 : 0;
}

/** A window `zoom` times narrower than the run on the drawn axis, centred on `focusMs` and kept
 * inside it. On a compressed axis the zoom is of drawn distance, not of elapsed time. */
export function zoomWindow(bounds: TimeWindow, zoom: number, focusMs?: number): TimeWindow {
  if (zoom <= 1) return bounds;
  const lo = toV(bounds.axis, bounds.startMs);
  const hi = toV(bounds.axis, bounds.endMs);
  const width = (hi - lo) / zoom;
  const centre = focusMs !== undefined ? toV(bounds.axis, focusMs) : lo + (hi - lo) / 2;
  const start = Math.min(Math.max(centre - width / 2, lo), hi - width);
  const win: TimeWindow = { startMs: fromV(bounds.axis, start), endMs: fromV(bounds.axis, start + width) };
  return bounds.axis ? { ...win, axis: bounds.axis } : win;
}

/** Approval waits (recorded `approval.requested` → `approval.decided`, or to now while pending)
 * that take at least `minShare` of the run: the ones worth compressing. Overlaps are merged. */
export function longWaits(root: Span, bounds: TimeWindow, nowMs: number, minShare = 0.25): Break[] {
  const total = bounds.endMs - bounds.startMs;
  const waits: Break[] = [];
  const visit = (s: Span) => {
    if (s.wait) {
      const startMs = Math.max(ms(s.wait.startTs), bounds.startMs);
      const endMs = Math.min(s.wait.endTs ? ms(s.wait.endTs) : Math.max(nowMs, startMs), bounds.endMs);
      if (endMs > startMs) waits.push({ startMs, endMs });
    }
    s.children.forEach(visit);
  };
  visit(root);
  waits.sort((a, b) => a.startMs - b.startMs);
  const merged: Break[] = [];
  for (const w of waits) {
    const last = merged.at(-1);
    if (last && w.startMs <= last.endMs) last.endMs = Math.max(last.endMs, w.endMs);
    else merged.push({ ...w });
  }
  return total > 0 ? merged.filter((w) => w.endMs - w.startMs >= total * minShare) : [];
}

/** The bounds with each break drawn at `share` of the axis instead of its real length. A break
 * no longer than that width stays linear; with nothing to compress the bounds are returned. */
export function compressAxis(bounds: TimeWindow, breaks: Break[], share = 0.06): TimeWindow {
  let kept = breaks.filter((b) => b.startMs >= bounds.startMs && b.endMs <= bounds.endMs && b.endMs > b.startMs);
  let width = 0;
  for (;;) {
    const linear = bounds.endMs - bounds.startMs - kept.reduce((t, b) => t + b.endMs - b.startMs, 0);
    width = kept.length * share < 1 ? (linear * share) / (1 - kept.length * share) : 0;
    const next = kept.filter((b) => b.endMs - b.startMs > width);
    if (next.length === kept.length) break;
    kept = next;
  }
  if (!kept.length || width <= 0) return bounds;
  const axis: Knot[] = [{ t: bounds.startMs, v: 0 }];
  let v = 0;
  let t = bounds.startMs;
  for (const b of kept) {
    v += b.startMs - t;
    axis.push({ t: b.startMs, v });
    v += width;
    axis.push({ t: b.endMs, v });
    t = b.endMs;
  }
  axis.push({ t: bounds.endMs, v: v + (bounds.endMs - t) });
  return { ...bounds, axis };
}

/** The compressed breaks visible in the window, with their real length for labelling. */
export function axisBreaks(win: TimeWindow): { startPct: number; endPct: number; ms: number }[] {
  const axis = win.axis ?? [];
  const out: { startPct: number; endPct: number; ms: number }[] = [];
  for (let i = 1; i < axis.length; i += 1) {
    const a = axis[i - 1]!;
    const b = axis[i]!;
    // A break is the only kind of knot pair drawn shorter than it lasted.
    if (b.t - a.t > b.v - a.v + 1e-6 && b.t > win.startMs && a.t < win.endMs) {
      out.push({ startPct: Math.max(0, pct(win, a.t)), endPct: Math.min(100, pct(win, b.t)), ms: b.t - a.t });
    }
  }
  return out;
}

function place(kind: SegmentKind, from: number, to: number, win: TimeWindow): Segment | null {
  if (to < win.startMs || from > win.endMs || win.endMs <= win.startMs) return null;
  const a = pct(win, Math.max(from, win.startMs));
  const b = pct(win, Math.min(to, win.endMs));
  return {
    kind,
    leftPct: a,
    widthPct: Math.max(MIN_WIDTH_PCT, b - a),
    clipStart: from < win.startMs,
    clipEnd: to > win.endMs,
  };
}

/** Bars for one waterfall row, in paint order. */
export function spanSegments(span: Span, win: TimeWindow, nowMs: number): Segment[] {
  const out: (Segment | null)[] = [];
  const start = ms(span.startTs);
  const end = span.endTs ? ms(span.endTs) : undefined;
  const waitStart = span.wait ? ms(span.wait.startTs) : undefined;
  const waitEnd = span.wait?.endTs ? ms(span.wait.endTs) : undefined;
  const now = Math.max(nowMs, start);

  if (span.kind === "run") {
    out.push(place("run", start, end ?? now, win));
  } else if (span.status === "unfinished") {
    // No end was recorded: drawn to the edge of the view and named as unfinished.
    out.push(place("unfinished", start, win.endMs, win));
  } else if (end === undefined && span.status === "running") {
    out.push(place("live", start, now, win));
  } else {
    const base: SegmentKind = span.status === "error" ? "failed" : span.kind === "tool" ? "tool" : span.agent ? "agent" : "step";
    out.push(place(base, start, end ?? waitStart ?? now, win));
  }
  if (waitStart !== undefined) out.push(place("wait", waitStart, waitEnd ?? end ?? now, win));
  if (span.kind === "node") {
    for (const tool of span.children) {
      if (tool.kind !== "tool") continue;
      const tStart = ms(tool.startTs);
      const tEnd = tool.endTs ? ms(tool.endTs) : tool.status === "running" ? now : undefined;
      if (tEnd !== undefined) out.push(place(tool.status === "error" ? "failed" : "tool", tStart, tEnd, win));
    }
  }
  return out.filter((s): s is Segment => s !== null);
}

/** Where a point-in-time event sits in the window, or null outside it. */
export function eventPosition(span: Span, win: TimeWindow): number | null {
  const t = ms(span.startTs);
  if (t < win.startMs || t > win.endMs) return null;
  return pct(win, t);
}

const STEPS = [100, 200, 500, 1000, 2000, 5000, 10_000, 15_000, 30_000, 60_000, 120_000, 300_000, 600_000, 900_000, 1_800_000, 3_600_000];

function tickLabel(offset: number): string {
  if (offset < 60_000) {
    const s = offset / 1000;
    return `${Number.isInteger(s) ? s : s.toFixed(1).replace(/\.0$/, "")}s`;
  }
  const m = Math.floor(offset / 60_000);
  const s = Math.round((offset % 60_000) / 1000);
  return s ? `${m}m ${s}s` : `${m}m`;
}

/** Axis ticks at round steps, labelled as time since `originMs` (the run's start). On a
 * compressed axis the step follows the drawn range and no tick falls inside a break. */
export function timeTicks(win: TimeWindow, originMs: number, target = 6): { pct: number; label: string }[] {
  const range = toV(win.axis, win.endMs) - toV(win.axis, win.startMs);
  if (range <= 0) return [];
  const step = STEPS.find((s) => range / s <= target) ?? STEPS.at(-1)!;
  const breaks = (win.axis ?? []).flatMap((b, i, all) => {
    const a = all[i - 1];
    return a && b.t - a.t > b.v - a.v + 1e-6 ? [{ startMs: a.t, endMs: b.t }] : [];
  });
  const ticks: { pct: number; label: string }[] = [];
  let off = Math.ceil((win.startMs - originMs) / step) * step;
  while (originMs + off <= win.endMs + 1e-6) {
    const t = originMs + off;
    const inside = breaks.find((b) => t >= b.startMs && t <= b.endMs);
    if (inside) {
      // Resume at the first round step after the break.
      off = Math.floor((inside.endMs - originMs) / step) * step + step;
      continue;
    }
    ticks.push({ pct: pct(win, t), label: tickLabel(off) });
    off += step;
  }
  return ticks;
}

/** A short real length for a break label: "9h 11m", "12m", "45s". */
export function breakLabel(msLength: number): string {
  const s = Math.round(msLength / 1000);
  if (s < 60) return `≈ ${s}s`;
  const m = Math.round(s / 60);
  if (m < 60) return `≈ ${m}m`;
  const h = Math.floor(m / 60);
  return `≈ ${h}h${m % 60 ? ` ${m % 60}m` : ""}`;
}

/** Axis labels laid out without overlap on an axis `axisPx` wide (11px mono, 0.6em advance):
 * break labels are placed first, centred on the break (right-anchored near the end); a tick is
 * kept only if its label clears every label already placed. Labels past 85% are right-anchored. */
export function spacedTicks<T extends { pct: number; label: string }>(
  ticks: T[],
  breaks: { startPct: number; endPct: number; ms: number }[],
  axisPx: number,
  padPx = 10,
): T[] {
  if (axisPx <= 0) return [];
  const widthPct = (label: string) => ((label.length * 6.6 + padPx) / axisPx) * 100;
  // A break label near the end sits against the right edge; a tick label there ends at its tick.
  const placed: [number, number][] = breaks.map((b) => {
    const at = (b.startPct + b.endPct) / 2;
    const w = widthPct(breakLabel(b.ms));
    return at > 85 ? [100 - w, 100] : [at - w / 2, at + w / 2];
  });
  const kept: T[] = [];
  for (const t of ticks) {
    const w = widthPct(t.label);
    const [a, b] = t.pct > 85 ? [t.pct - w, t.pct] : [t.pct, t.pct + w];
    if (placed.some(([c, d]) => a < d && c < b)) continue;
    placed.push([a, b]);
    kept.push(t);
  }
  return kept;
}
