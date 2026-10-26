/* What moves on screen, as observed in the DOM. An indicator that animates says so with
 * `data-motion="live"`; the class checks catch any older animation that bypasses the contract.
 * Each moving indicator is counted once, however many of its parts carry a class. */
const MOVING = '[data-motion="live"], .animate-spin, .qc-orb-live, .qc-seg-moving, .qc-pulse';

export function moving(root: ParentNode): Element[] {
  const all = [...root.querySelectorAll(MOVING)];
  return all.filter((el) => !all.some((other) => other !== el && other.contains(el)));
}
