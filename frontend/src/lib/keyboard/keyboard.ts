/* Keyboard helpers for the command palette and shortcuts (UI_UX §3.15). Pure where possible so the
 * conflict rules (no shortcut while typing) are unit-tested rather than assumed. */

const NON_TEXT_INPUTS = new Set(["checkbox", "radio", "button", "submit", "reset", "file", "range", "color", "image"]);

/** True when a plain key press belongs to the focused control: text inputs, selects, editors. */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.closest(".cm-editor")) return true;
  if (target.isContentEditable || target.getAttribute("contenteditable") === "true") return true;
  if (target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) return true;
  return target instanceof HTMLInputElement && !NON_TEXT_INPUTS.has(target.type);
}

export interface KeyBinding {
  id: string;
  keys: readonly string[];
}

/** Matches single keys and two-key sequences ("g d"). A pending prefix expires after `timeoutMs`. */
export function createSequenceMatcher(
  bindings: () => readonly KeyBinding[],
  timeoutMs: number,
  now: () => number = Date.now,
): (key: string) => string | null {
  let pending: { key: string; at: number } | null = null;
  return (key) => {
    const list = bindings();
    const t = now();
    if (pending && t - pending.at <= timeoutMs) {
      const prefix = pending.key;
      pending = null;
      const hit = list.find((b) => b.keys.length === 2 && b.keys[0] === prefix && b.keys[1] === key);
      if (hit) return hit.id;
    }
    pending = null;
    if (list.some((b) => b.keys.length === 2 && b.keys[0] === key)) {
      pending = { key, at: t };
      return null;
    }
    return list.find((b) => b.keys.length === 1 && b.keys[0] === key)?.id ?? null;
  };
}

export interface Searchable {
  label: string;
  keywords?: readonly string[];
}

/** Every word of the query must occur in the label or a keyword; order is preserved. */
export function filterCommands<T extends Searchable>(commands: readonly T[], query: string): T[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return [...commands];
  return commands.filter((c) => {
    const haystack = [c.label, ...(c.keywords ?? [])].join(" ").toLowerCase();
    return words.every((w) => haystack.includes(w));
  });
}
