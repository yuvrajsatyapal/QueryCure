# Design System

Status: Implemented; direction revised by [ADR-0030](../engineering/adr/ADR-0030-linear-langsmith-ui-direction.md) (2026-10-19): Linear-style structure and typography, a LangSmith-style trace for agent execution, dark-first. These tokens are **binding**: no raw Tailwind palette colors (`bg-blue-500`), no ad-hoc hex values, no fonts outside this file. The same tokens skin the designed diagrams in [docs/diagrams/](../diagrams/system-architecture.html) (light skin; IBM Plex for labels, Instrument Serif for diagram titles).

## 1. Direction

QueryCure is an instrument, not a chatbot. The UI should feel like a well-built profiler or observability console: dense, calm, precise, and honest about uncertainty.

**References.** Linear for navigation, typography, spacing, dashboards, history and forms. LangSmith for live multi-agent execution, tool calls and traces. QueryCure's own patterns for plans, approvals and benchmarks. Dark-first with a designed light theme.

- **Evidence over decoration.** Color carries meaning (claim status, verdict); everything else is neutral.
- **One accent.** A clinical teal used for primary actions, focus, and the single most important element on screen.
- **Typography does the hierarchy.** Weight and size contrast, not boxes inside boxes.
- **Monospace only for technical content** (SQL, plan nodes, numbers in tables, hashes).
- **No** gradients, glow, glassmorphism, chat bubbles, purple-on-white, or decorative animation.

## 2. Color tokens

Defined as CSS variables in `frontend/src/styles/tokens.css`, mapped into Tailwind via `theme.extend.colors` (`bg-surface`, `text-muted`, …) and into shadcn/ui's variable names.

### Neutrals & brand

| Token | Light | Dark | Usage |
|---|---|---|---|
| `--bg` | `#FBFBFC` | `#08090A` | Page background |
| `--sidebar` | `#F4F5F6` | `#0D0E10` | App sidebar, mobile top bar |
| `--surface` | `#FFFFFF` | `#111214` | Panels, cards |
| `--surface-2` | `#F2F3F5` | `#17181B` | Nested regions, table header, code blocks, segmented controls |
| `--hover` | `#ECEEF1` | `#1D1F22` | Row and nav hover, active nav item |
| `--border` | `#E4E6EA` | `#222428` | Hairlines (1px) |
| `--border-strong` | `#CFD2D8` | `#34373D` | Hovered inputs, focused panels |
| `--ink` | `#16171A` | `#F2F3F5` | Primary text |
| `--muted` | `#5D6270` | `#8F95A1` | Secondary text, axis labels (≥ 5.2:1 on every surface, both themes) |
| `--faint` | `#8B909B` | `#636873` | Icons and non-text marks only (≈ 2.8–3.0:1, below text contrast). Never text |
| `--accent` | `#0A6F6A` | `#3CC3B4` | Primary buttons, focus ring, active nav, focal element (5.8:1 / 8.8:1) |
| `--accent-tint` | `rgba(10,111,106,0.08)` | `rgba(60,195,180,0.12)` | Selected rows, accent-bordered boxes |
| `--accent-fg` | `#FFFFFF` | `#06211F` | Text on accent fills |
| `--link` | `#2A59B0` | `#8AB0F0` | Links, external/API references |

The teal accent is kept as the brand color (ADR-0030); Linear's indigo is deliberately not adopted.

### Semantic: run status

The five meanings color may carry in the app chrome. Tints are the same token at 10% (`bg-running/10`), borders at 30–40%.

| Meaning | Token | Light | Dark | Icon |
|---|---|---|---|---|
| Running | `--running` | `#1F5FBF` | `#6EA8FE` | spinning `loader` |
| Completed | `--verified` | `#1E7240` | `#5BC584` | `check-circle` |
| Failed | `--rejected` | `#B3261E` | `#F2837A` | `x-circle` |
| Warning | `--inconclusive` | `#8F5300` | `#E0A84A` | `alert-triangle` |
| Approval required | `--approval` | `#6A46CC` | `#B39CFF` | `hand` |

`components/ui/StatusPill.tsx` maps run statuses to these (`awaiting_approval` → approval required, `cancelling` → warning, `queued`/`cancelled` → neutral).

### Semantic: claim status & verdicts

Status is **never color-only**: every status also has an icon and a text label.

| Token | Light | Dark | Claim status / meaning | Icon (lucide) |
|---|---|---|---|---|
| `--observed` | `--ink` | `--ink` | Observed fact (solid border) | `eye` |
| `--hypothesis` | `#3F5577` | `#9DB2D6` | Hypothesis (dashed border) | `circle-dashed` |
| `--recommended` | `--accent` | `--accent` | Recommendation, unverified | `lightbulb` |
| `--verified` | `#1E7240` | `#5BC584` | Verified within tested scope | `badge-check` |
| `--rejected` | `#B3261E` | `#F2837A` | Rejected (with reason) | `circle-x` |
| `--inconclusive` | `#8F5300` | `#E0A84A` | Inconclusive / insufficient evidence | `circle-help` |

All semantic tokens clear 4.5:1 as text on `--bg` and `--surface-2` in both themes (computed; re-check with any change). Tints for badges: same hue at 10% (light) / 14% (dark) alpha.

### Charts (Recharts)

Baseline series = `--muted`; candidates = `--accent`, `--link`, `--hypothesis`, `--inconclusive` in that order (max 4 candidates per round matches the tournament budget). CI whiskers in the series color at 60% opacity. Gridlines `--border`.

## 3. Typography

| Role | Font | Size / line-height | Weight |
|---|---|---|---|
| Display (landing only) | Inter | 48/52 | 600, tight tracking |
| H1 page title | Inter | 20/28 | 600, tight tracking |
| H2 section | Inter | 14/20 | 600 |
| Body | Inter | 14/22 | 400 |
| Small / meta | Inter | 12/18 | 400–500 |
| Eyebrow / tag (`qc-eyebrow`) | JetBrains Mono | 11/16 | 500, uppercase, wide tracking |
| Code, SQL, plan nodes, span names, numbers | JetBrains Mono | 13/20 | 400–500, `tabular-nums` |

Loaded via `next/font/google` (self-hosted at build, no runtime Google request). Numeric table columns are right-aligned and tabular.

## 4. Spacing, radius, elevation

- Base unit 4px. Scale: `1=4, 2=8, 3=12, 4=16, 6=24, 8=32, 12=48`. No arbitrary values (`p-[13px]` is forbidden).
- Panel padding 16; dense table cell 8×12; page gutter 24 desktop / 16 mobile.
- Radius: inputs/buttons 6px, panels 8px, badges 4px. Nothing larger than 10px.
- Elevation: **borders, not shadows.** One exception: popovers/menus/dialogs use `0 8px 24px rgba(0,0,0,0.12)` (dark: `rgba(0,0,0,0.5)`) to separate from content.

## 5. Component patterns

Shared Tailwind utilities in `globals.css` (`@utility`): `qc-btn-primary`, `qc-btn-secondary`, `qc-btn-ghost`, `qc-input`, `qc-panel`, `qc-eyebrow`. Use them instead of repeating class strings. Icons come from `components/ui/Icon.tsx` (inline, lucide-style, decorative; always paired with a word or `aria-label`).

| Pattern | Spec |
|---|---|
| **ClaimBadge** | Icon + label + optional confidence (`Hypothesis · medium`). Border style encodes status (solid observed, dashed hypothesis). |
| **EvidenceChip** | Mono `ev_3f2a…` + kind icon; click opens lineage drawer. Every finding renders its chips. |
| **VerdictPill** | Verified / Rejected / Inconclusive + reason code tooltip (`result_mismatch`). |
| **MetricCell** | Value + unit + provenance marker (`measured` none, `prerecorded` ◆ with tooltip, `n/a` with reason). |
| **SpeedupBar** | Horizontal CI interval around 1.0× reference line; point = median ratio. |
| **PlanNode** (React Flow) | Node type (mono), relation, est vs actual rows with error ratio badge (≥10× highlighted `--inconclusive`), self-time bar. Hottest node gets the accent border (only one). |
| **StatusPill** | Tinted pill: status icon + word, tone from the run-status table. Used in page headers and the approval card. |
| **Trace** (LangSmith-style split) | Left: span tree built client-side from run events (`lib/events/trace.ts`), a WAI-ARIA `tree` with roving focus (↑/↓, →/←, Home/End; selection follows focus). The first row is the run. Each row: chevron (pointer only), glyph (status or kind), mono name, evidence count, latency waterfall, duration. Right: run results tabs when the run row is selected, otherwise **StepDetails** with Input · Output · Metadata · Evidence, where data the browser does not have (prompts, redacted tool arguments, raw model output) is stated in a dashed "unavailable" row, never filled in. |
| **RunSelector** | Header dropdown wrapping the run list; trigger text is the run meta (`run 2 · Experiment replay of run #1`); a single run is a plain label. Closes on select, Escape (focus returns), outside click. |
| **Usage meters** | Three compact meters (LLM calls, tokens, tool calls) against the run budget from `GET /runs/{id}`; bar turns `--inconclusive` at 80%. |
| **Cited by** | In plan node details: findings and hypotheses whose evidence resolves to the node, with pending and failed resolutions stated; the tree table shows `cited by N`. |
| **InvestigationRow** | Linear-style 44px list row: status icon, run number, title, mode tags, outcome (≥ xl), compact age (`14h`). |
| **ApprovalCard** | `--approval` border with an inset left bar, hand icon, "Waiting on you" pill; exact SQL, target sandbox, risk list, Approve selected / Decline. Primary button is the only accent on screen while pending. |
| **EmptyState** | One sentence of what's missing + one primary action + optional demo link. |
| **Button hierarchy** | One primary (accent) per view; secondary = bordered; ghost for toolbars; destructive = `--rejected` outline. |

## 6. Dark / light mode

`next-themes` with `class` strategy; **default dark** (ADR-0030), light is a designed counterpart; toggle persisted in `localStorage` (convenience only). Every token has both values; charts and React Flow read CSS variables at render so they switch without reload. Plan graph background: `--bg` with a 16px dot grid at `--border` 50%.

## 7. Layout rules (dashboard & workspace)

- App shell (Linear): fixed 240px sidebar on `--sidebar` (brand + theme toggle, "New investigation", grouped nav with active state, Settings and account at the bottom). Below `md` the sidebar is a drawer behind a 48px top bar. No global top bar on desktop: each page header carries its breadcrumb, title, status pill and actions. Content max width none for the workspace and investigation (tools), 1152px for dashboard and history.
- Investigation page (UI_UX §3.6): a header sticky from `md` up (breadcrumb, title, status pill, run selector, model, usage meters, actions; static on phones, where it is too tall to pin), then objective and notices, the approval card when pending, and the split trace: a 340–420px tree column (sticky below the header on ≥ 1280) and the selection details. Below 1280 the tree stacks above the details at up to 60vh.
- Information density: tables at 32px row height; no card grids for primary data — use tables.
- Asymmetry over symmetry: summary rows use varied widths (e.g. `1.4fr 1fr 0.8fr`), not three identical cards.

## 8. Responsive behaviour

| Breakpoint | Behaviour |
|---|---|
| ≥ 1280 | Results and trace side by side |
| 768–1279 | Single column; the trace follows the results |
| < 768 | Single column with tabs (Query · Plan · Agents · Results); plan explorer defaults to **tree-table** view; SQL editor full width; approval card full screen |

Touch targets ≥ 44×44 on mobile. Horizontal scroll only inside tables/plan canvas, never the page.

## 9. Accessibility

- WCAG 2.2 AA: contrast verified per token; focus ring 2px `--accent` + 2px offset on every interactive element.
- Plan graph has an equivalent **tree-table** (keyboard navigable, `role="treegrid"`), because canvas graphs aren't accessible.
- Charts have a data-table toggle and `aria-describedby` summaries ("Candidate A median 3.1 ms vs baseline 41 ms, CI 11.2–14.0×").
- SSE timeline is an `aria-live="polite"` region, throttled to one announcement per 5 s.
- Respect `prefers-reduced-motion`: disable graph auto-fit animation and progress shimmer.
- Status never conveyed by color alone (icon + text).
