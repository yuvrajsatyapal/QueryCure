/** QueryCure mark: a Q whose ring is broken like a circuit, a tail that steps like a trace (the investigation
 * path), and one accent point where it ends (the verified result). The ring follows the text colour, so the
 * mark works in both themes (it inherits `color`). Three optically adjusted cuts (docs/design/prototypes/landing): the full mark
 * from 19px up, a lighter-detail cut at 17–18px and a heavier one at 16px and below. */
const CUTS = {
  full: { w: 3, ring: "M22.43 12.25A9.5 9.5 0 1 1 17.52 6.89", tail: "M17.1 19.1L21.4 23.4H23.2", dot: [25.7, 23.4, 2.6] },
  small: { w: 3.6, ring: "M21.96 10.22A9 9 0 1 1 16.58 4.84", tail: "M17.3 17.1L21.4 21.2", dot: [26.8, 26.6, 3.4] },
  tiny: { w: 4.1, ring: "M21.96 10.22A9 9 0 1 1 16.58 4.84", tail: "M17.3 17.1L21.4 21.2", dot: [27.2, 27, 3.85] },
} as const;

/** `animated` gives the point one subtle pulse on load (landing page only; reduced motion skips it). */
export function Logo({ size = 20, animated = false, className = "" }: { size?: number; animated?: boolean; className?: string }) {
  const c = size <= 16 ? CUTS.tiny : size <= 18 ? CUTS.small : CUTS.full;
  const [cx, cy, r] = c.dot;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      aria-hidden="true"
      focusable="false"
      className={`qc-mark shrink-0 overflow-visible${animated ? " qc-anim" : ""} ${className}`}
    >
      <g fill="none" stroke="currentColor" strokeWidth={c.w} strokeLinecap="round" strokeLinejoin="round">
        <path d={c.ring} />
        <path d={c.tail} />
      </g>
      <circle className="qc-dot" cx={cx} cy={cy} r={r} fill="var(--accent)" />
    </svg>
  );
}
