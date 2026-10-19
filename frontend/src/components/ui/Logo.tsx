/** QueryCure mark: a plan tree whose hottest branch is cured (accent). */
export function Logo({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" aria-hidden="true" focusable="false" className="shrink-0">
      <rect width="20" height="20" rx="5" className="fill-ink" />
      <path d="M10 5v3.5M10 8.5 6 12.5M10 8.5l4 4" stroke="var(--bg)" strokeWidth="1.6" strokeLinecap="round" fill="none" />
      <circle cx="10" cy="5" r="1.6" fill="var(--bg)" />
      <circle cx="6" cy="13.5" r="1.6" fill="var(--bg)" />
      <circle cx="14" cy="13.5" r="1.9" fill="var(--accent)" />
    </svg>
  );
}
