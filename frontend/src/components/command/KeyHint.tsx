/** Keys rendered as small caps; "Mod" reads ⌘ on macOS and Ctrl elsewhere. Visual only. */
export function KeyHint({ keys, mac = false }: { keys: readonly string[]; mac?: boolean }) {
  return (
    <span aria-hidden="true" className="flex shrink-0 items-center gap-1">
      {keys.map((k, i) => (
        <kbd key={`${k}-${i}`} className="min-w-5 rounded border border-border bg-surface-2 px-1 text-center font-mono text-[11px] text-muted">
          {k === "Mod" ? (mac ? "⌘" : "Ctrl") : k}
        </kbd>
      ))}
    </span>
  );
}
