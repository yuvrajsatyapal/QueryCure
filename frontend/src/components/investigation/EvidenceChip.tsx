/** Mono evidence id; activating it opens the evidence and, for plan nodes, highlights the
 * node in the Plan tab. */
export function EvidenceChip({
  id,
  onOpen,
  active = false,
}: {
  id: string;
  onOpen: (id: string) => void;
  active?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={() => onOpen(id)}
      aria-pressed={active}
      aria-label={`Evidence ${id}`}
      className={`rounded border px-1.5 py-0.5 font-mono text-[11px] ${
        active ? "border-accent bg-accent-tint text-ink" : "border-border-strong text-link hover:bg-surface-2"
      }`}
    >
      {id.slice(0, 9)}…
    </button>
  );
}
