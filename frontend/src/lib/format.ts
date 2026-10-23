const rows = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

export function formatRows(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : rows.format(value);
}

export function formatMs(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value >= 100 ? `${value.toFixed(0)} ms` : `${value.toFixed(value >= 10 ? 1 : 2)} ms`;
}

export function formatPct(share: number | null | undefined): string {
  return share === null || share === undefined ? "—" : `${(share * 100).toFixed(1)}%`;
}

/** Wall-clock span latency for the trace: 840ms, 2.4s, 1m 05s. */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return "—";
  const v = Math.max(0, ms);
  if (v < 1000) return `${Math.round(v)}ms`;
  if (v < 60_000) return `${(v / 1000).toFixed(v < 10_000 ? 1 : 0)}s`;
  const m = Math.floor(v / 60_000);
  const s = Math.floor((v % 60_000) / 1000);
  return `${m}m ${String(s).padStart(2, "0")}s`;
}

/** Benchmark latencies are recorded in nanoseconds; they are shown in milliseconds. */
export function formatNs(value: number | null | undefined): string {
  return value === null || value === undefined || !Number.isFinite(value) ? "—" : formatMs(value / 1e6);
}

/** Speedup ratio (median baseline / median candidate): 1.59×, 13.8×. */
export function formatSpeedup(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${value >= 10 ? value.toFixed(1) : value.toFixed(2)}×`;
}

const cost = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** Planner cost units, as EXPLAIN prints them. */
export function formatCost(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : cost.format(value);
}
