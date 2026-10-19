# ADR-0030: Linear-style structure, LangSmith-style trace, dark-first UI

- Status: Accepted (2026-10-19); amends DESIGN_SYSTEM §2, §3, §5, §6, §7 and UI_UX §3.6
- Area: Frontend design

## Context

The owner set a visual direction for the web app: Linear's simplicity for navigation, typography, dashboards, history and forms; LangSmith's depth for live multi-agent execution, tool calls and traces; and QueryCure's own identity for plans, approvals and benchmarks. The UI should be dark-first with a designed light theme, use Tailwind with reusable tokens, use color only for run meaning (running, completed, failed, warning, approval required), and stay dense but uncluttered by putting detail behind expansion.

Before this change the app had one teal accent, IBM Plex, light-by-default theming, a top bar with a horizontal or left link list, and a flat event timeline.

## Decision

1. **Tokens.** Linear-style neutral grays (`--sidebar`, `--hover`, `--faint` added). Five status tokens: `--running`, `--verified` (completed), `--rejected` (failed), `--inconclusive` (warning) and `--approval` (approval required, new). The teal `--accent` stays as the brand color: it is QueryCure's identity, and Linear's indigo is not ours.
2. **Theme.** Dark is the default (`next-themes` `defaultTheme="dark"`); light is a designed counterpart, not an inversion.
3. **Type.** Inter (UI) and JetBrains Mono (SQL, plan nodes, IDs, numbers), self-hosted through `next/font`.
4. **Shared controls.** Tailwind `@utility` classes (`qc-btn-primary`, `qc-btn-secondary`, `qc-btn-ghost`, `qc-input`, `qc-panel`, `qc-eyebrow`) replace the repeated per-component class strings.
5. **Shell.** A fixed 240px sidebar (brand, theme toggle, "New investigation", grouped navigation, account footer); below `md` it becomes a drawer. Page headers carry the breadcrumb and actions.
6. **Trace.** The investigation timeline becomes a span tree built on the client from the existing SSE events (`lib/events/trace.ts`): run → graph nodes → tool calls and log events, with tool calls joining the open node of their agent (analysts run in parallel). Rows show a latency waterfall and expand into details (type, agent, status, start, latency, evidence chips, raw events). No backend or event-schema change.
7. **Icons.** A small inline SVG set in the lucide style (`components/ui/Icon.tsx`) instead of an icon package.

## Alternatives considered

- **Adopt Linear's indigo accent.** Rejected: it would erase the brand and clash with `--approval`.
- **Add `lucide-react`.** Rejected for now: about 40 icons are needed, and inlining them avoids a dependency (CODING_STANDARDS: no dependency without need).
- **Server-built span tree (a new endpoint).** Rejected: every field needed is already in `node.*` and `tool.*` events. A client fold is pure, testable and keeps the API unchanged.
- **Keep light-by-default.** Rejected by the owner's direction.

## Consequences

- Status remains icon + word + color. The trace writes span status for screen readers, and the region keeps its name ("Agent timeline").
- Tests and e2e assertions that read the old flat-timeline wording or the `Status: <status>` line were updated to the new UI text.
- The span tree is only as accurate as the events. A node that emits `error` without `node.completed` is closed as failed at the error. Spans left open by a finished run read "did not finish".
- Recharts series colors in DESIGN_SYSTEM §2 are unchanged.
