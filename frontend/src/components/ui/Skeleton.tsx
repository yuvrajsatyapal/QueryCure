/** A placeholder bar while data loads (UI_UX §2). `label` is announced once for the region. */
export function Skeleton({ label, lines = 1, className = "" }: { label: string; lines?: number; className?: string }) {
  return (
    <div role="status" aria-label={label} className={`flex flex-col gap-1.5 ${className}`}>
      {Array.from({ length: lines }, (_, i) => (
        <span key={i} aria-hidden="true" className={`qc-pulse block h-7 rounded-md bg-surface-2 ${i > 0 ? "w-2/3" : "w-full"}`} />
      ))}
    </div>
  );
}
