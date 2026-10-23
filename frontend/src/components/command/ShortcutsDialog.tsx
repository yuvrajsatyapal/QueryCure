"use client";

import { useEffect, useRef } from "react";
import { Icon } from "@/components/ui/Icon";
import type { Command } from "./CommandProvider";
import { KeyHint } from "./KeyHint";
import { useModal } from "./useModal";

// Keys handled outside the command list: the palette itself, the wizard and dialogs.
const FIXED: { label: string; keys: string[] }[] = [
  { label: "Command palette", keys: ["Mod", "K"] },
  { label: "Next step / Start (New investigation, outside the SQL editor)", keys: ["Mod", "Enter"] },
  { label: "Close a dialog or the palette", keys: ["Esc"] },
];

/** Every bound shortcut, read from the live command list so it cannot drift from what works. */
export function ShortcutsDialog({ commands, mac, onClose }: { commands: Command[]; mac: boolean; onClose: () => void }) {
  const dialog = useRef<HTMLDivElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  useModal(dialog, onClose);
  useEffect(() => {
    close.current?.focus();
  }, []);

  const rows = [...FIXED, ...commands.flatMap((c) => (c.keys ? [{ label: c.label, keys: [...c.keys] }] : []))];

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[10vh]">
      <div aria-hidden="true" onClick={onClose} className="absolute inset-0 bg-black/40" />
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="shortcuts-title"
        className="relative flex max-h-[80vh] w-full max-w-lg flex-col overflow-hidden rounded-lg border border-border bg-surface shadow-pop"
      >
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 id="shortcuts-title" className="text-sm font-semibold">
            Keyboard shortcuts
          </h2>
          <button ref={close} type="button" onClick={onClose} aria-label="Close keyboard shortcuts" className="qc-btn-ghost size-7 p-0">
            <Icon name="close" size={15} />
          </button>
        </div>
        <p className="px-4 pt-3 text-xs text-muted">
          Single-key shortcuts are ignored while you type in a field or the SQL editor. Two-key sequences such as{" "}
          <kbd className="font-mono">g</kbd> then <kbd className="font-mono">d</kbd> must be pressed within a second.
        </p>
        <dl className="overflow-y-auto px-4 py-3 text-sm">
          {rows.map((r) => (
            <div key={r.label} className="flex items-center justify-between gap-4 border-b border-border py-2 last:border-b-0">
              <dt className="text-ink">{r.label}</dt>
              <dd>
                <span className="sr-only">{r.keys.map((k) => (k === "Mod" ? (mac ? "Command" : "Control") : k)).join(r.keys.length === 2 && r.keys[0] !== "Mod" ? " then " : " plus ")}</span>
                <KeyHint keys={r.keys} mac={mac} />
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
