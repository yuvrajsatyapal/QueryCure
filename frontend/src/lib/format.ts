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
