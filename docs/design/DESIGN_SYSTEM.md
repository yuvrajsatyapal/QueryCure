# Design System

Status: Planned. These tokens are **binding** once Phase 1 UI work begins: no raw Tailwind palette colors (`bg-blue-500`), no ad-hoc hex values, no fonts outside this file. The same tokens skin the designed diagrams in [docs/diagrams/](../diagrams/system-architecture.html) (light skin; IBM Plex for labels, Instrument Serif for diagram titles).

## 1. Direction

QueryCure is an instrument, not a chatbot. The UI should feel like a well-built profiler or observability console: dense, calm, precise, and honest about uncertainty.

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
| `--bg` | `#FAFAF9` | `#0E1013` | Page background |
| `--surface` | `#FFFFFF` | `#15181D` | Panels, cards |
| `--surface-2` | `#F1F2F1` | `#1B1F25` | Nested regions, table header, code blocks |
| `--border` | `#E2E4E6` | `#2A2F37` | Hairlines (1px) |
| `--border-strong` | `#C9CDD2` | `#3A414B` | Inputs, focused panels |
| `--ink` | `#15181D` | `#E6E8EB` | Primary text (17.0:1 / 15.5:1) |
| `--muted` | `#566070` | `#9AA3AF` | Secondary text, axis labels (6.1:1 / 7.5:1) |
| `--accent` | `#0A6F6A` | `#3CC3B4` | Primary buttons, focus ring, active nav, focal element (5.8:1 / 8.8:1) |
| `--accent-tint` | `rgba(10,111,106,0.08)` | `rgba(60,195,180,0.12)` | Selected rows, accent-bordered boxes |
| `--accent-fg` | `#FFFFFF` | `#06211F` | Text on accent fills |
| `--link` | `#2C5BA8` | `#7EA6E8` | Links, external/API references |

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
| Display (landing only) | IBM Plex Sans | 40/48 | 600 |
| H1 page title | IBM Plex Sans | 24/32 | 600 |
| H2 section | IBM Plex Sans | 18/26 | 600 |
| H3 panel title | IBM Plex Sans | 14/20 | 600, `letter-spacing: 0.01em` |
| Body | IBM Plex Sans | 14/22 | 400 |
| Small / meta | IBM Plex Sans | 12/18 | 400–500 |
| Eyebrow / tag | IBM Plex Mono | 11/16 | 500, uppercase, `0.06em` |
| Code, SQL, plan nodes, numbers | IBM Plex Mono | 13/20 | 400–500, `font-variant-numeric: tabular-nums` |

Loaded via `next/font/google` (self-hosted at build, no runtime Google request). Numeric table columns are right-aligned and tabular.

## 4. Spacing, radius, elevation

- Base unit 4px. Scale: `1=4, 2=8, 3=12, 4=16, 6=24, 8=32, 12=48`. No arbitrary values (`p-[13px]` is forbidden).
- Panel padding 16; dense table cell 8×12; page gutter 24 desktop / 16 mobile.
- Radius: inputs/buttons 6px, panels 8px, badges 4px. Nothing larger than 10px.
- Elevation: **borders, not shadows.** One exception: popovers/menus/dialogs use `0 8px 24px rgba(0,0,0,0.12)` (dark: `rgba(0,0,0,0.5)`) to separate from content.

## 5. Component patterns

Built on shadcn/ui primitives (Radix), restyled with tokens.

| Pattern | Spec |
|---|---|
| **ClaimBadge** | Icon + label + optional confidence (`Hypothesis · medium`). Border style encodes status (solid observed, dashed hypothesis). |
| **EvidenceChip** | Mono `ev_3f2a…` + kind icon; click opens lineage drawer. Every finding renders its chips. |
| **VerdictPill** | Verified / Rejected / Inconclusive + reason code tooltip (`result_mismatch`). |
| **MetricCell** | Value + unit + provenance marker (`measured` none, `prerecorded` ◆ with tooltip, `n/a` with reason). |
| **SpeedupBar** | Horizontal CI interval around 1.0× reference line; point = median ratio. |
| **PlanNode** (React Flow) | Node type (mono), relation, est vs actual rows with error ratio badge (≥10× highlighted `--inconclusive`), self-time bar. Hottest node gets the accent border (only one). |
| **TimelineItem** | Time, agent, action, status icon; collapsible tool details; failures in `--rejected` text with retry count. |
| **ApprovalCard** | Exact SQL (read-only editor), target sandbox, risk list, Approve selected / Decline. Primary button is the only accent on screen while pending. |
| **EmptyState** | One sentence of what's missing + one primary action + optional demo link. |
| **Button hierarchy** | One primary (accent) per view; secondary = bordered; ghost for toolbars; destructive = `--rejected` outline. |

## 6. Dark / light mode

`next-themes` with `class` strategy; default follows system; toggle persisted in `localStorage` (convenience only). Every token has both values; charts and React Flow read CSS variables at render so they switch without reload. Plan graph background: `--bg` with a 16px dot grid at `--border` 50%.

## 7. Layout rules (dashboard & workspace)

- App shell: 56px top bar + 224px collapsible left nav (icons-only at 64px). Content max width none for workspace (it's a tool), 1200px for reading pages (reports, settings).
- Workspace uses resizable panels (`react-resizable-panels`): left = editor/context, center = plan/results tabs, right = agent timeline. Panel sizes persisted per user locally.
- Information density: tables at 32px row height; no card grids for primary data — use tables.
- Asymmetry over symmetry: summary rows use varied widths (e.g. `1.4fr 1fr 0.8fr`), not three identical cards.

## 8. Responsive behaviour

| Breakpoint | Behaviour |
|---|---|
| ≥ 1280 | Three-panel workspace |
| 768–1279 | Two panels; timeline becomes a toggleable right sheet |
| < 768 | Single column with tabs (Query · Plan · Agents · Results); plan explorer defaults to **tree-table** view; SQL editor full width; approval card full screen |

Touch targets ≥ 44×44 on mobile. Horizontal scroll only inside tables/plan canvas, never the page.

## 9. Accessibility

- WCAG 2.2 AA: contrast verified per token; focus ring 2px `--accent` + 2px offset on every interactive element.
- Plan graph has an equivalent **tree-table** (keyboard navigable, `role="treegrid"`), because canvas graphs aren't accessible.
- Charts have a data-table toggle and `aria-describedby` summaries ("Candidate A median 3.1 ms vs baseline 41 ms, CI 11.2–14.0×").
- SSE timeline is an `aria-live="polite"` region, throttled to one announcement per 5 s.
- Respect `prefers-reduced-motion`: disable graph auto-fit animation and progress shimmer.
- Status never conveyed by color alone (icon + text).
