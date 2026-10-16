/** Shown on every demo page: prerecorded data must never read as a live run. */
export function PrerecordedBanner({ label }: { label: string }) {
  return (
    <p role="note" aria-label="Prerecorded demonstration" className="rounded-md border border-inconclusive/50 bg-surface-2 p-3 text-sm">
      <span className="mr-2 rounded border border-inconclusive px-1.5 py-0.5 font-mono text-[11px] font-medium uppercase tracking-wider text-ink">
        Prerecorded
      </span>
      {label}
    </p>
  );
}
