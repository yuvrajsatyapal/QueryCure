/** Landing background depth. `intensity` is the only knob: 0 removes the far dot layer entirely, 1 is the
 * designed strength, and it scales both the far layer's visibility and how far it travels with scroll. */
export interface DotDepthConfig {
  intensity: number;
  parallax: number;
  tile: number;
}

export const DOT_DEPTH: DotDepthConfig = {
  intensity: 1,
  /** Far layer travel as a fraction of scroll distance at intensity 1. */
  parallax: 0.1,
  /** Far-grid pitch in px. Not a multiple of the 28px foreground pitch, so the two never beat into moiré. */
  tile: 72,
};

/** Vertical offset of the far layer for a scroll position. Wrapped to one tile so the pattern repeats
 * seamlessly, and snapped to whole device pixels so the soft dots step cleanly instead of shimmering. */
export function farLayerOffset(scrollY: number, dpr: number, depth: DotDepthConfig = DOT_DEPTH): number {
  const travel = scrollY * depth.parallax * depth.intensity;
  const wrapped = -(travel % depth.tile);
  const snapped = Math.round(wrapped * dpr) / dpr;
  // Rounding can land exactly on a full tile, which is the same picture as 0.
  return snapped <= -depth.tile ? 0 : snapped;
}
