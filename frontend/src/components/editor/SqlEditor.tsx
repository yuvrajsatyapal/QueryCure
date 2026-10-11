"use client";

import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { PostgreSQL, sql } from "@codemirror/lang-sql";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { EditorState } from "@codemirror/state";
import { EditorView, keymap, lineNumbers, placeholder as cmPlaceholder } from "@codemirror/view";
import { tags } from "@lezer/highlight";
import { useEffect, useRef } from "react";

// Syntax colors come from design tokens (DESIGN_SYSTEM §2), so they follow light/dark mode.
const highlight = HighlightStyle.define([
  { tag: tags.keyword, color: "var(--accent)", fontWeight: "500" },
  { tag: [tags.string, tags.special(tags.string)], color: "var(--link)" },
  { tag: [tags.number, tags.bool, tags.null], color: "var(--hypothesis)" },
  { tag: tags.comment, color: "var(--muted)", fontStyle: "italic" },
  { tag: tags.operator, color: "var(--ink)" },
]);

const theme = EditorView.theme({
  "&": { backgroundColor: "var(--surface)", color: "var(--ink)", fontSize: "13px", borderRadius: "6px" },
  ".cm-content": { fontFamily: "var(--font-plex-mono), ui-monospace, monospace", padding: "8px 0" },
  ".cm-gutters": { backgroundColor: "var(--surface-2)", color: "var(--muted)", border: "none" },
  "&.cm-focused": { outline: "2px solid var(--accent)", outlineOffset: "2px" },
  ".cm-cursor": { borderLeftColor: "var(--ink)" },
  ".cm-selectionBackground, &.cm-focused .cm-selectionBackground": { backgroundColor: "var(--accent-tint)" },
});

export function SqlEditor({
  value,
  onChange,
  readOnly = false,
  ariaLabel = "SQL query",
  placeholder = "SELECT …",
}: {
  value: string;
  onChange?: (value: string) => void;
  readOnly?: boolean;
  ariaLabel?: string;
  placeholder?: string;
}) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const onChangeRef = useRef(onChange);

  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  useEffect(() => {
    if (!host.current) return;
    const editor = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          lineNumbers(),
          history(),
          keymap.of([...defaultKeymap, ...historyKeymap]),
          sql({ dialect: PostgreSQL }),
          syntaxHighlighting(highlight),
          theme,
          cmPlaceholder(placeholder),
          EditorState.readOnly.of(readOnly),
          EditorView.editable.of(!readOnly),
          EditorView.contentAttributes.of({ "aria-label": ariaLabel }),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) onChangeRef.current?.(update.state.doc.toString());
          }),
        ],
      }),
    });
    view.current = editor;
    return () => {
      editor.destroy();
      view.current = null;
    };
    // The editor owns its document after mount; external changes are synced below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readOnly, ariaLabel, placeholder]);

  useEffect(() => {
    const editor = view.current;
    if (editor && editor.state.doc.toString() !== value) {
      editor.dispatch({ changes: { from: 0, to: editor.state.doc.length, insert: value } });
    }
  }, [value]);

  return <div ref={host} className="rounded-md border border-border-strong" />;
}
