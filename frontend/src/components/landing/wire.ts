const NS = "http://www.w3.org/2000/svg";

type CometOptions = {
  ms: number;
  delay?: number;
  /** Rest between passes; the comet loops forever when set. */
  gap?: number;
  cls?: string;
  color?: string;
};

/** A bright, glowing segment that travels the length of `path` (the glow comes from CSS on `.comet`). */
export function comet(svg: SVGElement, path: SVGPathElement, { ms, delay = 0, gap, cls, color }: CometOptions): Animation {
  const L = path.getTotalLength();
  const seg = Math.min(64, L * 0.3);
  const p = path.cloneNode() as SVGPathElement;
  p.removeAttribute("style");
  p.setAttribute("class", `comet${cls ? ` ${cls}` : ""}`);
  p.style.strokeDasharray = `${seg} ${L + seg}`;
  if (color) p.style.stroke = color;
  svg.appendChild(p);
  const loop = gap !== undefined;
  const anim = p.animate([{ strokeDashoffset: seg }, { strokeDashoffset: -L }], {
    duration: ms,
    delay,
    endDelay: gap ?? 0,
    iterations: loop ? Infinity : 1,
    easing: "cubic-bezier(.45,0,.25,1)",
    fill: "backwards",
  });
  if (!loop) anim.onfinish = () => p.remove();
  return anim;
}

/** An expanding ring on a connector end, timed to when a comet arrives (`ms` into a pass of `ms + gap`). */
export function flash(svg: SVGElement, x: number, y: number, { ms, delay = 0, gap, cls }: CometOptions): Animation {
  const ring = document.createElementNS(NS, "circle");
  ring.setAttribute("cx", String(x));
  ring.setAttribute("cy", String(y));
  ring.setAttribute("r", "3.2");
  ring.setAttribute("class", `port-ring${cls ? ` ${cls}` : ""}`);
  svg.appendChild(ring);
  const loop = gap !== undefined;
  const total = ms + (gap ?? 0);
  const a = Math.max(0, (ms - 120) / total);
  const b = Math.min(1, a + 520 / total);
  const anim = ring.animate(
    [
      { opacity: 0, transform: "scale(1)", offset: 0 },
      { opacity: 0, transform: "scale(1)", offset: a },
      { opacity: 0.85, transform: "scale(1.4)", offset: a + 0.0001 },
      { opacity: 0, transform: "scale(3.6)", offset: b },
      { opacity: 0, transform: "scale(3.6)", offset: 1 },
    ],
    { duration: total, delay, iterations: loop ? Infinity : 1, fill: "backwards" },
  );
  if (!loop) anim.onfinish = () => ring.remove();
  return anim;
}

/** A single ring burst at a point, for a pulse that has just arrived. */
export function burst(svg: SVGElement, x: number, y: number, color?: string): void {
  const ring = document.createElementNS(NS, "circle");
  ring.setAttribute("cx", String(x));
  ring.setAttribute("cy", String(y));
  ring.setAttribute("r", "3.2");
  ring.setAttribute("class", "port-ring");
  if (color) ring.style.stroke = color;
  svg.appendChild(ring);
  const anim = ring.animate(
    [
      { opacity: 0.85, transform: "scale(1.4)" },
      { opacity: 0, transform: "scale(3.6)" },
    ],
    { duration: 600, easing: "ease-out" },
  );
  anim.onfinish = () => ring.remove();
}
