# ADR-0011: CodeMirror 6 for the SQL editor (not Monaco)

- Status: Accepted (2026-10-11)
- Area: Frontend

## Context
The workspace needs a SQL editor with PostgreSQL highlighting, read-only mode, light/dark theming via CSS variables, and acceptable mobile behaviour.

## Alternatives
1. **Monaco** — VS Code experience, rich IntelliSense; multi-MB bundle, workers to configure in Next.js, weak mobile support, theming via its own API.
2. **CodeMirror 6** (`@codemirror/lang-sql` with PostgreSQL dialect) — modular, small, good mobile/touch support, styles via CSS, extensible autocompletion from our schema snapshot.
3. Plain textarea + highlighter — minimal; poor editing UX.

## Decision
CodeMirror 6 with a thin React wrapper (`components/editor/SqlEditor.tsx`).

## Rationale & trade-offs
- + Smaller bundle, simpler SSR story, token-based theming, mobile usable.
- − Less "IDE-like" out of the box; schema-aware completion is ours to write (small: table/column names from the snapshot).

## Consequences
Read-only editors (approval cards, reports) reuse the same component with `editable=false`.
